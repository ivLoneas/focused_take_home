"""Independent HTTP, probability-routing and settings contracts for Jev."""

import json

import httpx
import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda
from pydantic import SecretStr, ValidationError

from agents.agent_v2.domain import JevDomainGate
from agents.agent_v2.settings import AgentV2Config


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for name in (
        "AGENT_MODEL", "AGENT_V2_ROUTING_MODEL", "TYPESAFE_MODEL", "TYPESAFE_API_KEY",
        "TYPESAFE_TIMEOUT_SECONDS", "LANGSMITH_TRACING", "LANGSMITH_API_KEY",
        "LANGSMITH_AGENT_ID", "LANGSMITH_AGENT_ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)


def config(**kwargs):
    return AgentV2Config(_env_file=None, **kwargs)


def body(report=0.9, advice=0.1):
    return {
        "model": "jev-test", "answers": {
            "report_question": {"type": "noul", "noul": report},
            "financial_advice": {"type": "noul", "noul": advice},
        }, "usage": {"input_tokens": 123, "output_tokens": 4},
    }


def test_defaults_keep_answer_model_but_use_smaller_routing_model():
    settings = config()
    assert settings.model == "gpt-5-mini"
    assert settings.routing_model == "gpt-5-nano"
    assert settings.typesafe_model == "jev-latest"
    assert settings.typesafe_api_key is None
    assert settings.typesafe_timeout_seconds > 0


def test_configuration_reads_documented_environment_names_and_hides_key(monkeypatch):
    for key, value in {
        "AGENT_V2_ROUTING_MODEL": "  smaller-model  ", "TYPESAFE_MODEL": "  jev-test  ",
        "TYPESAFE_API_KEY": "  private-test-key  ", "TYPESAFE_TIMEOUT_SECONDS": "12.5",
    }.items():
        monkeypatch.setenv(key, value)
    settings = config()
    assert settings.routing_model == "smaller-model" and settings.typesafe_model == "jev-test"
    assert settings.typesafe_timeout_seconds == 12.5
    assert isinstance(settings.typesafe_api_key, SecretStr)
    assert settings.typesafe_api_key.get_secret_value() == "private-test-key"
    assert "private-test-key" not in repr(settings)
    assert "private-test-key" not in repr(settings.model_dump())


@pytest.mark.parametrize("field,value", [
    ("routing_model", ""), ("routing_model", "  "), ("routing_model", 123),
    ("typesafe_model", ""), ("typesafe_model", "\t"), ("typesafe_model", None),
    ("typesafe_timeout_seconds", 0), ("typesafe_timeout_seconds", -1),
    ("typesafe_timeout_seconds", float("inf")), ("typesafe_timeout_seconds", float("nan")),
])
def test_invalid_configuration_fails_clearly(field, value):
    with pytest.raises((ValidationError, TypeError, ValueError), match=field):
        config(**{field: value})


@pytest.mark.parametrize("value", [None, "", " \t"])
def test_real_gate_requires_nonblank_api_key(value):
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY|typesafe_api_key"):
        JevDomainGate(config(typesafe_api_key=value))


def test_v2_inherits_langsmith_configuration_validation():
    with pytest.raises(ValidationError, match="LANGSMITH_API_KEY|langsmith_api_key"):
        config(langsmith_tracing=True)


def test_gate_sends_single_structured_request_with_bundled_atomic_questions_and_finite_timeout():
    requests = []
    question = "What were Amazon's earnings in 2025? " + "Full context. " * 150

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=body())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        gate = JevDomainGate(config(typesafe_api_key="server-secret", typesafe_timeout_seconds=7), client=client)
        assert gate.invoke(question) is True

    assert len(requests) == 1
    request = requests[0]
    payload = json.loads(request.content)
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer server-secret"
    assert payload["model"] == "jev-latest"
    assert isinstance(payload["state"], dict)
    assert question in payload["state"].values()
    assert set(payload["questions"]) == {"report_question", "financial_advice"}
    assert all(value["type"] == "noul" for value in payload["questions"].values())
    assert "server-secret" not in repr(payload)
    assert request.extensions["timeout"]["read"] == 7


@pytest.mark.parametrize("report,advice,allowed", [
    (0.99, 0.01, True), (0.01, 0.01, False), (0.99, 0.99, False),
    (0.29, 0.1, False), (0.3, 0.1, True), (0.7, 0.1, True),
    (0.5, 0.5, True), (0.99, 0.6999, True), (0.99, 0.7, False),
    (0.99, 1, False), (0, 0, False), (1, 0, True),
])
def test_decision_table_has_defined_outcome_at_probability_boundaries(report, advice, allowed):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body(report, advice)))) as client:
        gate = JevDomainGate(config(typesafe_api_key="test-key"), client=client)
        assert gate.invoke("Test question") is allowed


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_errors_propagate_instead_of_becoming_out_of_domain(status):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, json={"detail": "unavailable"}))) as client:
        gate = JevDomainGate(config(typesafe_api_key="test-key"), client=client)
        with pytest.raises(httpx.HTTPStatusError):
            gate.invoke("Apple revenue?")


def test_network_error_propagates():
    def fail(request):
        raise httpx.ConnectError("API unreachable", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        gate = JevDomainGate(config(typesafe_api_key="test-key"), client=client)
        with pytest.raises(httpx.ConnectError, match="API unreachable"):
            gate.invoke("Apple revenue?")


@pytest.mark.parametrize("change", ["missing", "wrong_type", "outside_range", "nan", "bool", "string"])
def test_malformed_judgment_never_silently_passes_or_refuses(change):
    response = body()
    if change == "missing":
        del response["answers"]["financial_advice"]
    elif change == "wrong_type":
        response["answers"]["report_question"]["type"] = "choice"
    else:
        response["answers"]["report_question"]["noul"] = {
            "outside_range": 1.2, "nan": None, "bool": True, "string": "0.8",
        }[change]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))) as client:
        gate = JevDomainGate(config(typesafe_api_key="test-key"), client=client)
        with pytest.raises((ValidationError, TypeError, ValueError, KeyError)):
            gate.invoke("Apple revenue?")


def test_jev_custom_model_emits_nested_usage_callbacks_without_credentials():
    class Events(BaseCallbackHandler):
        def __init__(self):
            self.model_calls = []
            self.responses = []

        def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
            self.model_calls.append((parent_run_id, kwargs))

        def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
            self.model_calls.append((parent_run_id, kwargs))

        def on_llm_end(self, response, **kwargs):
            self.responses.append(response)

    events = Events()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body()))) as client:
        gate = JevDomainGate(config(typesafe_api_key="never-in-traces"), client=client)
        runner = RunnableLambda(lambda question: gate.invoke(question))
        assert runner.invoke("Apple revenue?", config={"callbacks": [events]}) is True

    assert len(events.model_calls) == 1 and events.model_calls[0][0] is not None
    assert len(events.responses) == 1
    response = events.responses[0]
    metadata = getattr(response.generations[0][0].message, "usage_metadata", None)
    usage = metadata or (response.llm_output or {}).get("token_usage", {})
    assert usage.get("input_tokens", usage.get("prompt_tokens")) == 123
    assert usage.get("output_tokens", usage.get("completion_tokens")) == 4
    assert "never-in-traces" not in repr(events.model_calls)
    assert "never-in-traces" not in repr(events.responses)
