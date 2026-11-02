"""Behavioral contract for baseline LangSmith tracing and callback propagation."""

from collections.abc import Sequence
from typing import Any, ClassVar
from unittest.mock import Mock
from uuid import UUID

import pytest
from langchain_core.callbacks import BaseCallbackHandler, CallbackManagerForLLMRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from pydantic import Field, SecretStr, ValidationError

from agents.baseline import baseline_agent as baseline_module
from agents.baseline.baseline_agent import BaselineAgent
from agents.settings import AgentConfig
from agents.tools import BaselineRetrieverAdapter

DEFAULT_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
DEFAULT_LANGSMITH_PROJECT = "focused-take-home"


@pytest.fixture(autouse=True)
def isolate_langsmith_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep local credentials and user-level tracing settings out of unit tests."""

    for name in (
        "AGENT_MODEL",
        "LANGSMITH_TRACING",
        "LANGSMITH_API_KEY",
        "LANGSMITH_PROJECT",
        "LANGSMITH_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_agent_config_defaults_model_and_disables_tracing_without_credentials() -> None:
    config = AgentConfig(_env_file=None)

    assert config.model == "gpt-5-mini"
    assert config.langsmith_tracing is False
    assert config.langsmith_api_key is None
    assert config.langsmith_project == DEFAULT_LANGSMITH_PROJECT
    assert config.langsmith_endpoint == DEFAULT_LANGSMITH_ENDPOINT


def test_agent_config_trims_an_explicit_model_name() -> None:
    config = AgentConfig(model="  gpt-5.2  ", _env_file=None)

    assert config.model == "gpt-5.2"


def test_agent_config_loads_and_trims_model_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL", "  gpt-5.2-mini  ")

    config = AgentConfig(_env_file=None)

    assert config.model == "gpt-5.2-mini"


@pytest.mark.parametrize("value", [None, "", " ", "\t\n", 123, True, b"gpt-5-mini"])
def test_agent_config_rejects_invalid_model_names(value: object) -> None:
    with pytest.raises(ValidationError, match="model"):
        AgentConfig(model=value, _env_file=None)


def test_settings_load_langsmith_configuration_from_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "LANGSMITH_TRACING=true\n"
        "LANGSMITH_API_KEY=dotenv-trace-secret\n"
        "LANGSMITH_PROJECT=dotenv-project\n"
        "LANGSMITH_ENDPOINT=https://langsmith.dotenv.test\n"
        "UNRELATED_APPLICATION_SETTING=ignored\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = AgentConfig()

    assert settings.langsmith_tracing is True
    assert isinstance(settings.langsmith_api_key, SecretStr)
    assert settings.langsmith_api_key.get_secret_value() == "dotenv-trace-secret"
    assert settings.langsmith_project == "dotenv-project"
    assert settings.langsmith_endpoint == "https://langsmith.dotenv.test"


def test_environment_overrides_dotenv_for_langsmith_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "LANGSMITH_TRACING=false\n"
        "LANGSMITH_API_KEY=dotenv-secret\n"
        "LANGSMITH_PROJECT=dotenv-project\n"
        "LANGSMITH_ENDPOINT=https://langsmith.dotenv.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "environment-secret")
    monkeypatch.setenv("LANGSMITH_PROJECT", "environment-project")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://langsmith.environment.test")

    settings = AgentConfig(_env_file=dotenv)

    assert settings.langsmith_tracing is True
    assert settings.langsmith_api_key is not None
    assert settings.langsmith_api_key.get_secret_value() == "environment-secret"
    assert settings.langsmith_project == "environment-project"
    assert settings.langsmith_endpoint == "https://langsmith.environment.test"


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_blank_api_key_is_normalized_to_missing_when_tracing_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", value)

    assert AgentConfig(_env_file=None).langsmith_api_key is None


@pytest.mark.parametrize("value", [None, "", " ", "\t\n"])
def test_enabled_tracing_requires_a_nonblank_api_key(value: str | None) -> None:
    values: dict[str, object] = {"langsmith_tracing": True, "_env_file": None}
    if value is not None:
        values["langsmith_api_key"] = value

    with pytest.raises(ValidationError, match="LANGSMITH_API_KEY|langsmith_api_key"):
        AgentConfig(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("langsmith_project", ""),
        ("langsmith_project", "   \t"),
        ("langsmith_endpoint", ""),
        ("langsmith_endpoint", "ftp://langsmith.example.test"),
        ("langsmith_endpoint", "not a URL"),
    ],
)
def test_invalid_langsmith_destinations_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        AgentConfig(**{field: value, "_env_file": None})


def test_invalid_tracing_boolean_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "sometimes")

    with pytest.raises(ValidationError, match="langsmith_tracing"):
        AgentConfig(_env_file=None)


def test_langsmith_api_key_is_not_exposed_by_settings_representations() -> None:
    secret = "super-sensitive-langsmith-key"
    settings = AgentConfig(langsmith_api_key=secret, _env_file=None)

    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert secret not in repr(settings.model_dump())


class RecordingClient:
    """Network-free stand-in that exposes the LangSmith destination contract."""

    instances: ClassVar[list[RecordingClient]] = []

    def __init__(self, *, api_key: str, api_url: str) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.instances.append(self)


class RecordingTracer(BaseCallbackHandler):
    """Network-free tracer that records root and nested LangChain activity."""

    instances: ClassVar[list[RecordingTracer]] = []

    def __init__(self, *, project_name: str, client: RecordingClient, **kwargs: Any) -> None:
        self.project_name = project_name
        self.client = client
        self.constructor_kwargs = kwargs
        self.events: list[dict[str, Any]] = []
        self.instances.append(self)

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        del inputs
        self.events.append(
            {
                "kind": "chain",
                "name": kwargs.get("name") or (serialized or {}).get("name"),
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "tags": tags or [],
                "metadata": metadata or {},
            }
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        del serialized, messages, kwargs
        self.events.append(
            {
                "kind": "model",
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "tags": tags or [],
                "metadata": metadata or {},
            }
        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        del serialized, input_str, kwargs
        self.events.append({
            "kind": "tool", "run_id": run_id,
            "parent_run_id": parent_run_id, "inputs": inputs or {},
        })

    def on_retriever_start(
        self,
        serialized: dict[str, Any] | None,
        query: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        del serialized, kwargs
        self.events.append(
            {
                "kind": "retriever",
                "query": query,
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "tags": tags or [],
                "metadata": metadata or {},
            }
        )


@pytest.fixture
def recording_langsmith(monkeypatch: pytest.MonkeyPatch) -> tuple[type[RecordingClient], type[RecordingTracer]]:
    RecordingClient.instances.clear()
    RecordingTracer.instances.clear()
    monkeypatch.setattr(baseline_module, "Client", RecordingClient)
    monkeypatch.setattr(baseline_module, "LangChainTracer", RecordingTracer)
    return RecordingClient, RecordingTracer


class NoCallModel:
    """A model boundary suitable for graph-construction-only tests."""

    def invoke(self, input: object, **kwargs: Any) -> str:
        del input, kwargs
        raise AssertionError("model must not run")

    def with_structured_output(self, schema, **kwargs: Any):
        del schema, kwargs
        raise AssertionError("model must not run")


def test_enabled_agent_attaches_configured_langsmith_tracer_to_root_graph_invocation(
    recording_langsmith,
) -> None:
    client_type, tracer_type = recording_langsmith
    settings = AgentConfig(
        model="gpt-5.2-mini",
        langsmith_tracing=True,
        langsmith_api_key="trace-secret",
        langsmith_project="baseline-observability",
        langsmith_endpoint="https://langsmith.example.test",
        _env_file=None,
    )
    injected_model = NoCallModel()
    agent = BaselineAgent(injected_model, config=settings)
    agent.graph = Mock(
        invoke=Mock(
            return_value={
                "status": "out_of_domain",
                "answer": "bounded response",
                "context": [],
                "retrieval_attempts": 0,
            }
        )
    )

    result = agent.invoke("How do I make sourdough bread?")

    assert result.answer == "bounded response"
    assert len(client_type.instances) == 1
    assert len(tracer_type.instances) == 1
    client = client_type.instances[0]
    tracer = tracer_type.instances[0]
    assert client.api_key == "trace-secret"
    assert client.api_url == "https://langsmith.example.test"
    assert tracer.client is client
    assert tracer.project_name == "baseline-observability"
    assert agent.model is injected_model
    assert agent.config is settings

    config = agent.graph.invoke.call_args.args[1]
    assert config["run_name"] == "baseline-agent"
    assert config["callbacks"] == [tracer]
    assert "baseline" in config["tags"]
    assert config["metadata"]["component"] == "baseline-agent"
    assert config["metadata"]["workflow"] == "financial-report-rag"
    assert config["metadata"]["model"] == "gpt-5.2-mini"
    assert config["metadata"]["max_retrieval_attempts"] == 3
    assert "trace-secret" not in repr(config)
    assert "How do I make sourdough bread?" not in repr(config["metadata"])


class TraceableModel(BaseChatModel):
    """Deterministic chat model whose real Runnable methods emit callbacks."""

    analyses: list[dict[str, Any]]
    assessments: list[dict[str, Any]]
    answers: list[str]

    @property
    def _llm_type(self) -> str:
        return "traceable-test-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        if not self.answers:
            raise AssertionError("Unexpected answer-model call")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.answers.pop(0)))])

    def with_structured_output(self, schema, **kwargs: Any):
        del kwargs
        fields = set(schema.model_fields)
        if {"out_of_domain", "needs_clarification", "retrieval_query"} <= fields:
            responses = self.analyses
            run_name = "test-question-analysis-model"
        elif {"is_sufficient", "refined_query"} <= fields:
            responses = self.assessments
            run_name = "test-context-assessment-model"
        else:
            raise AssertionError(f"Unexpected structured-output schema: {sorted(fields)}")

        def invoke(_: object):
            if not responses:
                raise AssertionError("Unexpected structured-model call")
            return schema.model_validate(responses.pop(0))

        return RunnableLambda(invoke).with_config(run_name=run_name)


class TraceableRetriever(BaseRetriever):
    """Standard BaseRetriever fake used to prove child retriever runs propagate."""

    documents: Sequence[Document]
    queries: list[str] = Field(default_factory=list, exclude=True)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del run_manager
        self.queries.append(query)
        return list(self.documents)


def test_root_callback_propagates_to_nested_graph_model_and_standard_retriever_runs(
    recording_langsmith,
) -> None:
    _, tracer_type = recording_langsmith
    model = TraceableModel(
        analyses=[
            {
                "out_of_domain": False,
                "needs_clarification": False,
                "clarification_question": None,
                "required_facts": ["Apple FY2025 net sales"],
                "retrieval_query": "Apple FY2025 net sales annual report",
                "companies": ["Apple"],
            }
        ],
        assessments=[{"is_sufficient": True, "refined_query": None}],
        answers=["Apple reported $416.161 billion in net sales [Apple 2025 10-K p. 29]."],
    )
    document_retriever = TraceableRetriever(
        documents=[
            Document(
                page_content="Total net sales were $416.161 billion in 2025.",
                metadata={"title": "Apple 2025 10-K", "pages": (29,)},
            )
        ]
    )
    settings = AgentConfig(
        langsmith_tracing=True,
        langsmith_api_key="trace-secret",
        langsmith_project="callback-propagation-test",
        _env_file=None,
    )
    agent = BaselineAgent(
        model,
        retriever=BaselineRetrieverAdapter(retrievers={"Apple": document_retriever}),
        config=settings,
    )

    result = agent.invoke("What were Apple's net sales in FY2025?")

    assert result.status == "answered"
    assert document_retriever.queries == ["Apple FY2025 net sales annual report"]
    tracer = tracer_type.instances[0]
    root_events = [event for event in tracer.events if event["kind"] == "chain" and event["parent_run_id"] is None]
    assert len(root_events) == 1
    assert root_events[0]["name"] == "baseline-agent"
    assert "baseline" in root_events[0]["tags"]
    assert root_events[0]["metadata"]["component"] == "baseline-agent"
    assert any(event["kind"] == "chain" and event["parent_run_id"] is not None for event in tracer.events)
    assert any(event["kind"] == "model" and event["parent_run_id"] is not None for event in tracer.events)
    tool_events = [event for event in tracer.events if event["kind"] == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["parent_run_id"] is not None
    assert tool_events[0]["inputs"]["company"] == "Apple"
    assert any(
        event["kind"] == "retriever" and event["parent_run_id"] == tool_events[0]["run_id"]
        for event in tracer.events
    )
    assert any(
        event["kind"] == "retriever"
        and event["parent_run_id"] is not None
        and event["query"] == "Apple FY2025 net sales annual report"
        for event in tracer.events
    )


def test_disabled_tracing_is_network_free_and_preserves_existing_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock(side_effect=AssertionError("disabled tracing must not construct a LangSmith client"))
    tracer = Mock(side_effect=AssertionError("disabled tracing must not construct a LangSmith tracer"))
    monkeypatch.setattr(baseline_module, "Client", client)
    monkeypatch.setattr(baseline_module, "LangChainTracer", tracer)
    model = TraceableModel(
        analyses=[
            {
                "out_of_domain": True,
                "needs_clarification": False,
                "clarification_question": None,
                "required_facts": [],
                "retrieval_query": "",
            }
        ],
        assessments=[],
        answers=[],
    )

    result = BaselineAgent(model, config=AgentConfig(_env_file=None)).invoke("How do I make sourdough bread?")

    assert result.status == "out_of_domain"
    assert "financial report" in result.answer.lower()
    assert result.retrieval_attempts == 0
    assert result.citations == ()
    client.assert_not_called()
    tracer.assert_not_called()
