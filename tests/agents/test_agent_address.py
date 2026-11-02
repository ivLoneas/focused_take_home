"""Agent-address tracing configuration and callback propagation contracts."""

from unittest.mock import Mock

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langsmith import agent_address
from pydantic import ValidationError

from agents.baseline import baseline_agent as baseline_module
from agents.baseline.baseline_agent import BaselineAgent
from agents.baseline.models import QuestionAnalysis
from agents.settings import AgentConfig


@pytest.fixture(autouse=True)
def isolate_langsmith(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AGENT_MODEL",
        "LANGSMITH_TRACING",
        "LANGSMITH_API_KEY",
        "LANGSMITH_PROJECT",
        "LANGSMITH_ENDPOINT",
        "LANGSMITH_AGENT_ID",
        "LANGSMITH_AGENT_ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)


def config(**kwargs) -> AgentConfig:
    return AgentConfig(_env_file=None, **kwargs)


def test_default_configuration_has_no_agent_address() -> None:
    settings = config()

    assert settings.langsmith_agent_id is None
    assert settings.langsmith_agent_environment is None


@pytest.mark.parametrize("environment", ["local", "development", "staging", "production"])
def test_agent_address_trims_id_and_normalizes_environment(environment: str) -> None:
    settings = config(langsmith_agent_id="  example-agent  ", langsmith_agent_environment=f" {environment.upper()} ")

    assert settings.langsmith_agent_id == "example-agent"
    assert settings.langsmith_agent_environment == environment


@pytest.mark.parametrize("identifier,environment", [(None, None), ("", ""), ("  ", "\t")])
def test_absent_or_blank_address_pair_uses_project_configuration(identifier, environment) -> None:
    settings = config(langsmith_agent_id=identifier, langsmith_agent_environment=environment)

    assert settings.langsmith_agent_id is None
    assert settings.langsmith_agent_environment is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"langsmith_agent_id": "example-agent"},
        {"langsmith_agent_environment": "production"},
        {"langsmith_agent_id": "example-agent", "langsmith_agent_environment": "  "},
        {"langsmith_agent_id": "", "langsmith_agent_environment": "development"},
    ],
)
def test_agent_address_requires_both_nonblank_fields(kwargs) -> None:
    with pytest.raises(ValidationError, match="(?i)(agent|environment)"):
        config(**kwargs)


@pytest.mark.parametrize("environment", ["preview", "dev", "test", "sometimes"])
def test_unknown_agent_environment_is_rejected(environment: str) -> None:
    with pytest.raises(ValidationError, match="langsmith_agent_environment"):
        config(langsmith_agent_id="example-agent", langsmith_agent_environment=environment)


def test_agent_address_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_AGENT_ID", "environment-agent")
    monkeypatch.setenv("LANGSMITH_AGENT_ENVIRONMENT", "STAGING")

    settings = config()

    assert settings.langsmith_agent_id == "environment-agent"
    assert settings.langsmith_agent_environment == "staging"


def test_address_tracer_uses_configured_eu_client_and_omits_project_name(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    client_type = Mock(return_value=client)
    tracer = BaseCallbackHandler()
    tracer_type = Mock(return_value=tracer)
    monkeypatch.setattr(baseline_module, "Client", client_type)
    monkeypatch.setattr(baseline_module, "LangChainTracer", tracer_type)
    settings = config(
        langsmith_tracing=True,
        langsmith_api_key="test-secret",
        langsmith_endpoint="https://eu.api.smith.langchain.com/",
        langsmith_project="must-not-override-agent",
        langsmith_agent_id="example-agent",
        langsmith_agent_environment="production",
    )

    agent = BaselineAgent(Mock(), config=settings)

    client_type.assert_called_once_with(api_key="test-secret", api_url="https://eu.api.smith.langchain.com")
    tracer_type.assert_called_once_with(address=agent_address("example-agent", "production"), client=client)
    assert agent.tracer is tracer


def test_project_tracer_remains_available_without_agent_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    tracer = BaseCallbackHandler()
    tracer_type = Mock(return_value=tracer)
    monkeypatch.setattr(baseline_module, "Client", Mock(return_value=client))
    monkeypatch.setattr(baseline_module, "LangChainTracer", tracer_type)

    BaselineAgent(
        Mock(),
        config=config(
            langsmith_tracing=True,
            langsmith_api_key="test-secret",
            langsmith_project="legacy-project",
        ),
    )

    tracer_type.assert_called_once_with(project_name="legacy-project", client=client)


def test_disabled_tracing_does_not_construct_client_for_agent_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    client_type = Mock()
    monkeypatch.setattr(baseline_module, "Client", client_type)

    agent = BaselineAgent(
        Mock(),
        config=config(
            langsmith_tracing=False,
            langsmith_agent_id="example-agent",
            langsmith_agent_environment="local",
        ),
    )

    assert agent.tracer is None
    client_type.assert_not_called()


def test_agent_address_preserves_root_and_nested_model_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []

    class RecordingTracer(BaseCallbackHandler):
        def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
            events.append(("chain", run_id, parent_run_id, kwargs.get("metadata", {})))

        def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
            events.append(("model", run_id, parent_run_id, kwargs.get("metadata", {})))

    tracer = RecordingTracer()
    monkeypatch.setattr(baseline_module, "Client", Mock(return_value=Mock()))
    monkeypatch.setattr(baseline_module, "LangChainTracer", Mock(return_value=tracer))
    chat = FakeMessagesListChatModel(responses=[AIMessage(content="analysis")])

    class Model:
        def with_structured_output(self, schema):
            def analyze(prompt):
                chat.invoke(prompt)
                return QuestionAnalysis(out_of_domain=True, needs_clarification=False)

            return RunnableLambda(analyze)

    agent = BaselineAgent(
        Model(),
        config=config(
            langsmith_tracing=True,
            langsmith_api_key="test-secret",
            langsmith_agent_id="example-agent",
            langsmith_agent_environment="development",
        ),
    )

    result = agent.invoke("How do I bake bread?")

    assert result.status == "out_of_domain"
    root = next(event for event in events if event[0] == "chain" and event[2] is None)
    model_event = next(event for event in events if event[0] == "model")
    assert model_event[2] is not None
    assert root[1] != model_event[1]
    assert "test-secret" not in repr(events)
