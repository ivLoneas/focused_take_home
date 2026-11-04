"""Web thread IDs are allocated before paid calls and reused for clarification tracing."""

import json
from contextvars import Context
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.models import RunResponse, SessionRecord, SessionState


class Store:
    def __init__(self):
        self.rows = {}

    def initialize(self):
        pass

    def create(self, session_hash, ttl_seconds):
        self.rows[session_hash] = SessionRecord(state=SessionState(), version=0)
        return deepcopy(self.rows[session_hash])

    def load(self, session_hash, ttl_seconds):
        return deepcopy(self.rows.get(session_hash))

    def save(self, session_hash, state, expected_version, ttl_seconds):
        row = self.rows[session_hash]
        if row.version != expected_version:
            return False
        row.state = deepcopy(state)
        row.version += 1
        return True


class ObservedAgent:
    def __init__(self):
        self.observed = []
        self.status = "needs_clarification"
        self.fail = False

    def invoke(self, question):
        from agents.tracing import thread_metadata
        self.observed.append(thread_metadata())
        if self.fail:
            raise RuntimeError("private-cookie-token")
        return SimpleNamespace(status=self.status, answer="Which company?", citations=(), retrieval_attempts=0)

    def stream(self, question):
        from agents.tracing import thread_metadata
        self.observed.append(thread_metadata())
        yield {"type": "token", "text": "Which company?"}
        yield {"type": "result", "result": self.invoke(question)}


@pytest.mark.parametrize("agent_id,endpoint", [("baseline", "/api/session/run"),
                                                 ("agent_v2", "/api/session/run"),
                                                 ("agent_v2", "/api/session/run/stream")])
def test_saved_question_thread_id_groups_initial_clarification_and_distinct_new_questions(agent_id, endpoint):
    agent, store = ObservedAgent(), Store()
    client = TestClient(create_app(settings=Settings(_env_file=None), session_store_factory=lambda: store,
                                   agent_factory=lambda: agent, v2_agent_factory=lambda: agent))
    assert client.get("/api/session").status_code == 200

    def run(question, thread_id=None):
        response = client.post(endpoint, json={"agent_id": agent_id, "question": question, "thread_id": thread_id})
        assert response.status_code == 200
        payload = response.json() if endpoint.endswith("/run") else json.loads(response.text.splitlines()[-1])
        assert payload.get("type", "result") == "result", payload
        return payload["state"]["active_thread_id"]

    first = run("Revenue?")
    assert str(UUID(first)) == first
    assert agent.observed and all(value == {"session_id": first} for value in agent.observed)
    agent.status = "answered"
    before = len(agent.observed)
    assert run("Apple FY2025", first) == first
    assert all(value == {"session_id": first} for value in agent.observed[before:])
    before = len(agent.observed)
    second = run("Amazon revenue?")
    assert second != first and str(UUID(second)) == second
    assert all(value == {"session_id": second} for value in agent.observed[before:])
    cookie = client.cookies.get("focused_session")
    assert cookie not in repr(agent.observed) and sha256(cookie.encode()).hexdigest() not in repr(agent.observed)
    agent.observed.clear()
    client.post("/api/run", json={"agent_id": agent_id, "question": "One-shot eval-style request"})
    assert agent.observed == [{}]


def test_error_clears_trace_context_before_a_following_one_shot_call():
    agent, store = ObservedAgent(), Store()
    agent.fail = True
    client = TestClient(create_app(settings=Settings(_env_file=None), session_store_factory=lambda: store,
                                   v2_agent_factory=lambda: agent))
    client.get("/api/session")
    response = client.post("/api/session/run", json={"agent_id": "agent_v2", "question": "Revenue?"})
    assert response.status_code == 503
    assert agent.observed[0].get("session_id")
    assert client.get("/api/session").json()["threads"] == []
    agent.fail = False
    client.post("/api/run", json={"agent_id": "agent_v2", "question": "Fresh"})
    assert agent.observed[-1] == {}


def test_stream_steps_restore_context_before_yield_and_between_worker_contexts():
    from agents.tracing import thread_metadata
    from backend.session_api import register_session_routes

    store = Store()
    cookie = b"b" * 43
    session_hash = sha256(cookie).hexdigest()
    store.create(session_hash, 1800)
    observed = []

    def stream(request):
        observed.append(thread_metadata())
        yield {"type": "token", "text": "10"}
        observed.append(thread_metadata())
        yield {"type": "result", "result": RunResponse(status="answered", answer="10", citations=[], retrieval_attempts=0)}

    app = FastAPI()
    register_session_routes(app, Settings(_env_file=None), session_store_factory=lambda: store,
                            invoke=lambda _: None, stream=stream, unavailable_detail="Unavailable")
    route = next(route for route in app.routes if route.path == "/api/session/run/stream")
    from starlette.requests import Request

    from backend.models import SessionRunRequest
    request = Request({"type": "http", "method": "POST", "scheme": "http", "path": "/api/session/run/stream",
                       "server": ("testserver", 80), "headers": [(b"cookie", b"focused_session=" + cookie)]})
    # Exercise the synchronous generator before StreamingResponse wraps it for AnyIO.
    captured = []
    import backend.session_api as module
    original = module.StreamingResponse
    module.StreamingResponse = lambda iterator, **kwargs: captured.append(iterator)
    try:
        route.endpoint(request=request, payload=SessionRunRequest(agent_id="agent_v2", question="Revenue?"))
    finally:
        module.StreamingResponse = original
    iterator = iter(captured[0])
    worker = Context()
    assert json.loads(worker.run(next, iterator))["type"] == "token"
    assert worker.run(thread_metadata) == {} and thread_metadata() == {}
    terminal = json.loads(Context().run(next, iterator))
    assert terminal["type"] == "result"
    identifier = terminal["state"]["active_thread_id"]
    assert observed == [{"session_id": identifier}, {"session_id": identifier}]
    assert thread_metadata() == {}
