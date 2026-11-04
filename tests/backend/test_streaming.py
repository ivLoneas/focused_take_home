"""Independent HTTP streaming and v2 dependency acceptance tests."""

import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from agents.models import AgentResult
from backend import dependencies
from backend.app import SERVICE_UNAVAILABLE_DETAIL, create_app
from backend.config import Settings
from evals import agent_v2_provider
from evals.provider import ProviderSettings


@pytest.fixture
def settings():
    return Settings(openai_api_key="test-key", max_question_length=80, _env_file=None)


class StreamingAgent:
    def __init__(self, status="answered", failure=None):
        self.questions = []
        self.status = status
        self.failure = failure

    def invoke(self, question):
        self.questions.append(question)
        return AgentResult(self.status, "Revenue £10.\nDone.", ("Report p. 1",), 2,
                           ({"name": "listed_companies", "arguments": {}},))

    def stream(self, question):
        self.questions.append(question)
        if self.status == "answered":
            yield {"type": "token", "text": "Revenue £10.\n"}
            if self.failure:
                raise self.failure
            yield {"type": "token", "text": "Done."}
        yield {"type": "result", "result": AgentResult(self.status, "Revenue £10.\nDone.", ("Report p. 1",), 2)}


def make_client(settings, agent=None, factory=None):
    return TestClient(create_app(settings=settings, v2_agent_factory=factory or (lambda: agent or StreamingAgent())))


def test_stream_endpoint_sends_tokens_and_complete_http_result(settings):
    agent = StreamingAgent()
    response = make_client(settings, agent).post("/api/run/stream", json={"agent_id": "agent_v2", "question": "Revenue?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.iter_lines()]
    assert events[:2] == [{"type": "token", "text": "Revenue £10.\n"}, {"type": "token", "text": "Done."}]
    assert events[2] == {"type": "result", "result": {
        "status": "answered", "answer": "Revenue £10.\nDone.", "citations": ["Report p. 1"], "retrieval_attempts": 2,
    }}
    assert len(events) == 3
    assert agent.questions == ["Revenue?"]


@pytest.mark.parametrize("status", ["needs_clarification", "out_of_domain"])
def test_stream_endpoint_supports_static_final_outcomes(settings, status):
    response = make_client(settings, StreamingAgent(status)).post(
        "/api/run/stream", json={"agent_id": "agent_v2", "question": "Question?"},
    )
    events = [json.loads(line) for line in response.iter_lines()]
    assert len(events) == 1 and events[0]["result"]["status"] == status


@pytest.mark.parametrize("agent_id,question,code", [
    ("missing", "Question?", 404), ("baseline", "Question?", 400),
    ("agent_v2", "", 422), ("agent_v2", " \n", 422), ("agent_v2", "x" * 81, 422),
])
def test_invalid_stream_request_is_rejected_before_agent_construction(settings, agent_id, question, code):
    factory = Mock()
    response = make_client(settings, factory=factory).post(
        "/api/run/stream", json={"agent_id": agent_id, "question": question},
    )
    assert response.status_code == code
    factory.assert_not_called()


def test_stream_construction_failure_is_sanitized_503(settings):
    factory = Mock(side_effect=RuntimeError("OPENAI_API_KEY=secret-value"))
    response = make_client(settings, factory=factory).post(
        "/api/run/stream", json={"agent_id": "agent_v2", "question": "Question?"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": SERVICE_UNAVAILABLE_DETAIL}
    assert "secret-value" not in response.text


def test_midstream_failure_has_sanitized_error_and_no_success_result(settings):
    response = make_client(settings, StreamingAgent(failure=RuntimeError("secret-value"))).post(
        "/api/run/stream", json={"agent_id": "agent_v2", "question": "Question?"},
    )
    events = [json.loads(line) for line in response.iter_lines()]
    assert events == [{"type": "token", "text": "Revenue £10.\n"},
                      {"type": "error", "detail": SERVICE_UNAVAILABLE_DETAIL}]
    assert "secret-value" not in response.text


def test_regular_run_endpoint_also_supports_v2(settings):
    agent = StreamingAgent()
    response = make_client(settings, agent).post("/api/run", json={"agent_id": "agent_v2", "question": "Revenue?"})
    assert response.status_code == 200
    assert response.json()["answer"] == "Revenue £10.\nDone."
    assert "tool_calls" not in response.json()
    assert agent.questions == ["Revenue?"]


def test_app_builder_enables_streaming_without_opening_database(settings, monkeypatch):
    monkeypatch.setenv("AGENT_V2_STREAMING", "false")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-typesafe-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGSMITH_AGENT_ID", raising=False)
    monkeypatch.delenv("LANGSMITH_AGENT_ENVIRONMENT", raising=False)
    for name in ("ChatOpenAI", "OpenAIEmbeddings", "PgVectorRetriever", "DatabaseCoverage", "BaselineRetrieverAdapter"):
        monkeypatch.setattr(dependencies, name, Mock())
    monkeypatch.setattr(dependencies.psycopg, "connect", Mock())
    gate = Mock()
    factory = Mock()
    monkeypatch.setattr(dependencies, "JevDomainGate", gate, raising=False)
    monkeypatch.setattr(dependencies, "AgentV2", factory, raising=False)
    dependencies.build_agent_v2(settings)
    assert factory.call_args.kwargs["config"].streaming is True
    assert factory.call_args.kwargs["config"].model == settings.chat_model
    assert gate.call_args.args[0].streaming is True
    assert any(call.kwargs.get("stream_usage") is True for call in dependencies.ChatOpenAI.call_args_list)
    dependencies.psycopg.connect.assert_not_called()


def test_eval_builder_forces_streaming_off_even_when_environment_enables_it(monkeypatch):
    monkeypatch.setenv("AGENT_V2_STREAMING", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGSMITH_AGENT_ID", raising=False)
    monkeypatch.delenv("LANGSMITH_AGENT_ENVIRONMENT", raising=False)
    for name in ("ChatOpenAI", "OpenAIEmbeddings", "PgVectorRetriever", "DatabaseCoverage", "BaselineRetrieverAdapter",
                 "JevDomainGate", "AgentV2"):
        monkeypatch.setattr(agent_v2_provider, name, Mock())
    settings = ProviderSettings(OPENAI_API_KEY="test-key", _env_file=None)
    agent_v2_provider.build_agent(settings)
    assert agent_v2_provider.AgentV2.call_args.kwargs["config"].streaming is False
