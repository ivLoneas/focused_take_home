"""Cookie sessions own question threads and commit completed turns atomically."""

import json
from copy import deepcopy
from hashlib import sha256
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.app import SERVICE_UNAVAILABLE_DETAIL, create_app
from backend.config import Settings


class MemorySessions:
    """Deterministic durable store with the production CAS boundary."""

    def __init__(self):
        self.rows = {}
        self.lock = Lock()
        self.initializations = 0
        self.reject_save = False
        self.failure = None

    def initialize(self):
        self.initializations += 1

    def create(self, session_hash, ttl_seconds):
        from backend.models import SessionRecord, SessionState
        with self.lock:
            record = SessionRecord(state=SessionState(active_thread_id=None, threads=[]), version=0)
            self.rows[session_hash] = deepcopy(record)
            return record

    def load(self, session_hash, ttl_seconds):
        if self.failure:
            raise self.failure
        with self.lock:
            return deepcopy(self.rows.get(session_hash))

    def save(self, session_hash, state, expected_version, ttl_seconds):
        if self.failure:
            raise self.failure
        with self.lock:
            record = self.rows.get(session_hash)
            if self.reject_save or record is None or record.version != expected_version:
                return False
            record.state = deepcopy(state)
            record.version += 1
            return True


class Agent:
    def __init__(self):
        self.questions = []
        self.status = "needs_clarification"
        self.failure = False

    def invoke(self, question):
        self.questions.append(question)
        if self.failure:
            raise RuntimeError("secret-credentials")
        return SimpleNamespace(status=self.status, answer="Which company?" if self.status == "needs_clarification" else "Revenue 10",
                               citations=(), retrieval_attempts=0)

    def stream(self, question):
        yield {"type": "token", "text": "Partial"}
        yield {"type": "result", "result": self.invoke(question)}


def client_for(store=None, agent=None, **settings):
    store = store or MemorySessions()
    agent = agent or Agent()
    app = create_app(settings=Settings(_env_file=None, **settings), session_store_factory=lambda: store,
                     agent_factory=lambda: agent, v2_agent_factory=lambda: agent)
    return TestClient(app), store, agent


def bootstrap(client):
    response = client.get("/api/session")
    assert response.status_code == 200, response.text
    return response


def test_session_store_is_lazy_and_cookie_contains_only_opaque_token_hash():
    store = MemorySessions()
    factory = Mock(return_value=store)
    client = TestClient(create_app(settings=Settings(_env_file=None), session_store_factory=factory))
    assert client.get("/health").status_code == 200
    assert client.get("/api/agents").status_code == 200
    factory.assert_not_called()
    response = bootstrap(client)
    assert response.json() == {"active_thread_id": None, "threads": []}
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api" in cookie
    assert "Max-Age" not in cookie and "expires=" not in cookie.lower()
    token = client.cookies.get("focused_session")
    assert len(token) >= 40 and set(store.rows) == {sha256(token.encode()).hexdigest()}
    assert token not in repr(store.rows)
    assert "no-store" in response.headers["cache-control"]
    again = bootstrap(client)
    assert "set-cookie" not in again.headers and store.initializations == 1


def test_secure_cookie_setting_and_expired_cookie_rotation():
    client, store, _ = client_for(session_cookie_secure=True)
    assert "Secure" in bootstrap(client).headers["set-cookie"]
    old = client.cookies.get("focused_session")
    store.rows.clear()
    assert bootstrap(client).status_code == 200
    assert client.cookies.get("focused_session") != old


@pytest.mark.parametrize("method,path,body", [
    ("put", "/api/session/active-thread", {"thread_id": None}),
    ("delete", "/api/session/threads", None),
    ("post", "/api/session/run", {"agent_id": "agent_v2", "question": "Revenue?"}),
])
def test_mutations_require_valid_cookie(method, path, body):
    client, _, _ = client_for()
    response = client.request(method, path, json=body)
    assert response.status_code == 401


@pytest.mark.parametrize("path", ["/api/session", "/api/session/active-thread"])
def test_disallowed_origin_rejected_before_session_access(path):
    client, _, _ = client_for()
    response = client.get(path, headers={"Origin": "https://attacker.example"}) if path == "/api/session" else client.put(
        path, json={"thread_id": None}, headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("endpoint", ["/api/session/run", "/api/session/run/stream"])
def test_session_run_reconstructs_clarification_and_survives_new_app_instance(endpoint):
    client, store, agent = client_for()
    bootstrap(client)
    first = client.post(endpoint, json={"agent_id": "agent_v2", "question": "What was revenue?"})
    payload = first.json() if endpoint.endswith("/run") else json.loads(first.text.splitlines()[-1])
    state = payload["state"]
    thread_id = state["active_thread_id"]
    assert len(state["threads"]) == 1 and len(state["threads"][0]["turns"]) == 1
    assert payload["result"]["metrics"]["response_ms"] >= 0
    agent.status = "answered"
    reply = client.post(endpoint, json={"agent_id": "agent_v2", "question": "Apple FY2025", "thread_id": thread_id})
    payload = reply.json() if endpoint.endswith("/run") else json.loads(reply.text.splitlines()[-1])
    assert payload.get("type", "result") == "result"
    assert len(payload["state"]["threads"][0]["turns"]) == 2
    context = json.loads(agent.questions[-1][agent.questions[-1].index("{"):agent.questions[-1].rindex("}") + 1])
    assert context["clarification_history"] == [{"question": "What was revenue?", "clarification": "Which company?"}]
    assert context["latest_reply"] == "Apple FY2025"
    fresh_app, _, _ = client_for(store=store)
    restored = fresh_app.get("/api/session", headers={"Cookie": f"focused_session={client.cookies.get('focused_session')}"})
    assert restored.json() == payload["state"]
    foreign, _, foreign_agent = client_for(store=store)
    bootstrap(foreign)
    assert foreign.get("/api/session").json()["threads"] == []
    assert foreign.post(endpoint, json={"agent_id": "agent_v2", "question": "Apple", "thread_id": thread_id}).status_code == 404
    assert not foreign_agent.questions


@pytest.mark.parametrize("endpoint", ["/api/session/run", "/api/session/run/stream"])
@pytest.mark.parametrize("failure", ["model", "store", "conflict"])
def test_failed_or_conflicting_run_never_commits_or_emits_success(endpoint, failure):
    client, store, agent = client_for()
    before = bootstrap(client).json()
    agent.failure = failure == "model"
    if failure == "store":
        # Loading succeeds; only the persistence boundary fails.
        store.save = Mock(side_effect=RuntimeError("secret-credentials"))
    store.reject_save = failure == "conflict"
    response = client.post(endpoint, json={"agent_id": "agent_v2", "question": "Revenue?"})
    if endpoint.endswith("/stream"):
        frames = [json.loads(line) for line in response.iter_lines()]
        assert not any(frame["type"] == "result" for frame in frames)
        assert frames[-1]["type"] == "error"
        if failure == "conflict":
            assert frames[-1]["status"] == 409
    else:
        assert response.status_code == (409 if failure == "conflict" else 503)
    assert "secret-credentials" not in response.text
    assert bootstrap(client).json() == before


def test_completed_or_wrong_agent_thread_rejected_before_model_and_mutations_persist():
    client, _, agent = client_for()
    bootstrap(client)
    state = client.post("/api/session/run", json={"agent_id": "agent_v2", "question": "Revenue?"}).json()["state"]
    thread_id = state["active_thread_id"]
    count = len(agent.questions)
    assert client.post("/api/session/run", json={"agent_id": "baseline", "question": "Apple", "thread_id": thread_id}).status_code == 409
    assert len(agent.questions) == count
    agent.status = "answered"
    assert client.post("/api/session/run", json={"agent_id": "agent_v2", "question": "Apple", "thread_id": thread_id}).status_code == 200
    count = len(agent.questions)
    assert client.post("/api/session/run", json={"agent_id": "agent_v2", "question": "More", "thread_id": thread_id}).status_code == 409
    assert len(agent.questions) == count
    assert client.put("/api/session/active-thread", json={"thread_id": None}).json()["active_thread_id"] is None
    assert client.put("/api/session/active-thread", json={"thread_id": thread_id}).json()["active_thread_id"] == thread_id
    assert client.delete(f"/api/session/threads/{thread_id}").json()["threads"] == []
    assert client.put("/api/session/active-thread", json={"thread_id": thread_id}).status_code == 404
    assert client.delete("/api/session/threads").json() == {"active_thread_id": None, "threads": []}


@pytest.mark.parametrize("extra", [{"clarification_history": []}, {"messages": []}, {"state": {}}, {"history": []}])
def test_session_run_never_accepts_client_transcripts(extra):
    client, _, agent = client_for()
    bootstrap(client)
    assert client.post("/api/session/run", json={"agent_id": "agent_v2", "question": "Revenue?", **extra}).status_code == 422
    assert not agent.questions


def test_store_read_failure_is_sanitized_and_session_settings_are_validated():
    from pydantic import ValidationError
    client, store, _ = client_for()
    bootstrap(client)
    store.failure = RuntimeError("secret-credentials")
    response = client.get("/api/session")
    assert response.status_code == 503 and response.json()["detail"] == SERVICE_UNAVAILABLE_DETAIL
    assert "secret-credentials" not in response.text
    assert Settings(_env_file=None).session_ttl_seconds == 1800
    with pytest.raises(ValidationError):
        Settings(session_ttl_seconds=59, _env_file=None)


def test_import_is_validated_once_and_never_overwrites_server_history():
    client, _, _ = client_for()
    bootstrap(client)
    state = {"active_thread_id": "legacy", "threads": [{
        "id": "legacy", "agent_id": "baseline", "created_at": "2026-11-04T10:00:00Z", "updated_at": "2026-11-04T10:00:00Z",
        "turns": [{"question": "Old question", "status": "answered", "answer": "10", "citations": [],
                   "retrieval_attempts": 0, "created_at": "2026-11-04T10:00:00Z"}],
    }]}
    response = client.post("/api/session/import", json=state)
    assert response.status_code == 200 and response.json()["threads"][0]["id"] == "legacy"
    assert client.post("/api/session/import", json=state).status_code == 409
    assert bootstrap(client).json()["threads"][0]["id"] == "legacy"


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://testserver"])
def test_allowed_frontend_and_same_api_origin_can_mutate_session(origin):
    client, _, _ = client_for()
    bootstrap(client)
    assert client.put("/api/session/active-thread", json={"thread_id": None}, headers={"Origin": origin}).status_code == 200


def test_expired_session_mutation_is_401_and_old_run_never_opens_session_store():
    client, store, _ = client_for()
    bootstrap(client)
    store.rows.clear()
    assert client.delete("/api/session/threads").status_code == 401
    factory = Mock(side_effect=AssertionError("Session store must stay lazy"))
    agent = Agent()
    independent = TestClient(create_app(settings=Settings(_env_file=None), session_store_factory=factory,
                                        agent_factory=lambda: agent))
    assert independent.post("/api/run", json={"agent_id": "baseline", "question": "Revenue?"}).status_code == 200
    factory.assert_not_called()


@pytest.mark.parametrize("invalid", ["unknown_agent", "blank_question", "extra_turn_field", "completed_chain", "too_many_turns"])
def test_import_rejects_malformed_or_invalid_thread_chains(invalid):
    client, _, _ = client_for()
    bootstrap(client)
    turn = {"question": "Revenue?", "status": "answered", "answer": "10", "citations": [],
            "retrieval_attempts": 0, "created_at": "2026-11-04T10:00:00Z"}
    thread = {"id": "legacy", "agent_id": "baseline", "created_at": "2026-11-04T10:00:00Z",
              "updated_at": "2026-11-04T10:00:00Z", "turns": [turn]}
    if invalid == "unknown_agent":
        thread["agent_id"] = "unknown"
    elif invalid == "blank_question":
        turn["question"] = " \n"
    elif invalid == "extra_turn_field":
        turn["messages"] = []
    elif invalid == "completed_chain":
        thread["turns"] = [deepcopy(turn), deepcopy(turn)]
    else:
        turn["status"] = "needs_clarification"
        thread["turns"] = [deepcopy(turn) for _ in range(7)]
    response = client.post("/api/session/import", json={"active_thread_id": "legacy", "threads": [thread]})
    assert response.status_code == 422
    assert bootstrap(client).json()["threads"] == []
