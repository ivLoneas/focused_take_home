"""Unit contract for the Promptfoo Python provider around ``BaselineAgent``."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import SecretStr, ValidationError

from evals import provider
from evals.telemetry import RunMetrics, record_embedding_response


def settings(**overrides: object) -> provider.ProviderSettings:
    values = {
        "openai_api_key": "sk-test",
        "database_url": "postgresql://user:password@db.example.test/reports",
        "chat_model": "chat-test",
        "embedding_model": "embedding-test",
        "embedding_dimensions": 1536,
        "retrieval_limit": 7,
        "max_retrieval_attempts": 2,
    }
    values.update(overrides)
    return provider.ProviderSettings(_env_file=None, **values)


def test_settings_are_pydantic_settings_and_normalize_the_required_api_key() -> None:
    configured = settings(openai_api_key="  sk-test  ")

    assert isinstance(configured.openai_api_key, SecretStr)
    assert configured.openai_api_key.get_secret_value() == "sk-test"


@pytest.mark.parametrize("api_key", [None, "", "  \t"])
def test_settings_require_a_nonblank_openai_api_key(api_key: object) -> None:
    with pytest.raises(ValidationError, match="openai_api_key"):
        settings(openai_api_key=api_key)


@pytest.mark.parametrize("field", ["retrieval_limit", "max_retrieval_attempts"])
@pytest.mark.parametrize("value", [0, -1])
def test_settings_require_positive_retrieval_controls(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match=field):
        settings(**{field: value})


def test_build_agent_wires_openai_pgvector_adapter_and_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    agent_config = SimpleNamespace(model="chat-test")
    chat_model = object()
    embeddings = object()
    pgvector_retriever = object()
    adapter = object()
    coverage = object()
    built_agent = object()
    chat_openai = Mock(return_value=chat_model)
    openai_embeddings = Mock(return_value=embeddings)
    pgvector = Mock(return_value=pgvector_retriever)
    adapter_type = Mock(return_value=adapter)
    coverage_type = Mock(return_value=coverage)
    baseline_type = Mock(return_value=built_agent)
    agent_config_type = Mock(return_value=agent_config)
    connect = Mock(return_value=object())
    monkeypatch.setattr(provider, "ChatOpenAI", chat_openai)
    monkeypatch.setattr(provider, "OpenAIEmbeddings", openai_embeddings)
    monkeypatch.setattr(provider, "PgVectorRetriever", pgvector)
    monkeypatch.setattr(provider, "BaselineRetrieverAdapter", adapter_type)
    monkeypatch.setattr(provider, "DatabaseCoverage", coverage_type, raising=False)
    monkeypatch.setattr(provider, "BaselineAgent", baseline_type)
    monkeypatch.setattr(provider, "AgentConfig", agent_config_type)
    monkeypatch.setattr(provider.psycopg, "connect", connect)
    configured = settings()

    result = provider.build_agent(configured)

    assert result is built_agent
    agent_config_type.assert_called_once_with(model="chat-test")
    chat_openai.assert_called_once_with(model="chat-test", temperature=0, api_key="sk-test")
    openai_embeddings.assert_called_once()
    embedding_kwargs = openai_embeddings.call_args.kwargs
    assert embedding_kwargs["model"] == "embedding-test"
    assert embedding_kwargs["dimensions"] == 1536
    assert embedding_kwargs["api_key"] == "sk-test"
    assert embedding_kwargs["http_client"].event_hooks["response"] == [record_embedding_response]
    assert pgvector.call_count == 5
    assert {call.kwargs["company"] for call in pgvector.call_args_list} == {
        "Alphabet",
        "Amazon",
        "Apple",
        "Meta",
        "Netflix",
    }
    pgvector_kwargs = pgvector.call_args.kwargs
    assert pgvector_kwargs["embeddings"] is embeddings
    assert pgvector_kwargs["limit"] == 7
    assert callable(pgvector_kwargs["connection_factory"])
    assert connect.call_count == 0
    connection = pgvector_kwargs["connection_factory"]()
    assert connection is connect.return_value
    connect.assert_called_once_with(configured.database_url)
    adapter_type.assert_called_once_with(
        retrievers={company: pgvector_retriever for company in ("Alphabet", "Amazon", "Apple", "Meta", "Netflix")}
    )
    coverage_type.assert_called_once()
    assert callable(coverage_type.call_args.kwargs["connection_factory"])
    baseline_type.assert_called_once_with(
        chat_model,
        retriever=adapter,
        max_retrieval_attempts=2,
        config=agent_config,
        coverage=coverage,
    )


def test_get_agent_caches_expensive_runtime_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    provider.get_agent.cache_clear()
    configured = settings()
    built_agent = object()
    settings_type = Mock(return_value=configured)
    build_agent = Mock(return_value=built_agent)
    monkeypatch.setattr(provider, "ProviderSettings", settings_type)
    monkeypatch.setattr(provider, "build_agent", build_agent)

    first = provider.get_agent()
    second = provider.get_agent()

    assert first is built_agent
    assert second is built_agent
    settings_type.assert_called_once_with()
    build_agent.assert_called_once_with(configured)
    provider.get_agent.cache_clear()


def test_call_api_returns_agent_answer_and_trajectory_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    result = SimpleNamespace(
        answer="ExampleCo reported $10 billion [ExampleCo report p. 10].",
        status="answered",
        citations=("ExampleCo report p. 10",),
        retrieval_attempts=2,
        tool_calls=(),
    )
    agent = Mock()
    agent.invoke.return_value = result
    monkeypatch.setattr(provider, "get_agent", Mock(return_value=agent))

    response = provider.call_api(
        "  What revenue did ExampleCo report?  ",
        {"config": {}},
        {"vars": {"id": "ACC01"}},
    )

    agent.invoke.assert_called_once_with("What revenue did ExampleCo report?")
    latency = response["metadata"]["answer_latency_ms"]
    assert isinstance(latency, (int, float))
    assert latency >= 0
    assert response == {
        "output": result.answer,
        "metadata": {
            "status": "answered",
            "citations": ["ExampleCo report p. 10"],
            "retrieval_attempts": 2,
            "tool_calls": [],
            "telemetry": RunMetrics().metadata(),
            "answer_latency_ms": latency,
        },
        "tokenUsage": {"prompt": 0, "completion": 0, "total": 0, "cached": 0, "numRequests": 0},
    }


def test_call_api_reports_actual_nested_model_tokens_in_promptfoo_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="answer",
                usage_metadata={
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "input_token_details": {"cache_read": 40},
                    "output_token_details": {"reasoning": 6},
                },
            )
        ]
    )

    def invoke(question: str):
        model.invoke(question)
        return SimpleNamespace(answer="answer", status="answered", citations=(), retrieval_attempts=0, tool_calls=())

    agent = SimpleNamespace(invoke=invoke)
    monkeypatch.setattr(provider, "get_agent", lambda: agent)

    response = provider.call_api("question", {}, {})

    assert response["tokenUsage"] == {
        "prompt": 100,
        "completion": 20,
        "total": 120,
        "cached": 40,
        "numRequests": 1,
    }
    telemetry = response["metadata"]["telemetry"]
    assert telemetry["model_calls"] == 1
    assert telemetry["input_tokens"] == 100
    assert telemetry["output_tokens"] == 20
    assert telemetry["total_tokens"] == 120
    assert telemetry["cached_input_tokens"] == 40
    assert telemetry["reasoning_tokens"] == 6


def test_call_api_latency_includes_runtime_construction_and_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [10.0]
    monkeypatch.setattr(provider, "perf_counter", lambda: clock[0], raising=False)

    def invoke(question: str):
        clock[0] += 0.08
        return SimpleNamespace(answer="answer", status="answered", citations=(), retrieval_attempts=0, tool_calls=())

    def get_agent():
        clock[0] += 0.02
        return SimpleNamespace(invoke=invoke)

    monkeypatch.setattr(provider, "get_agent", get_agent)

    response = provider.call_api("question", {}, {})

    assert response["metadata"]["answer_latency_ms"] == pytest.approx(100.0)


@pytest.mark.parametrize(
    ("prompt", "error_type"),
    [
        (None, TypeError),
        (123, TypeError),
        (b"question", TypeError),
        ("", ValueError),
        ("  \t\n", ValueError),
    ],
)
def test_call_api_rejects_invalid_prompts_before_constructing_runtime(
    monkeypatch: pytest.MonkeyPatch,
    prompt: object,
    error_type: type[Exception],
) -> None:
    get_agent = Mock()
    monkeypatch.setattr(provider, "get_agent", get_agent)

    with pytest.raises(error_type, match="prompt"):
        provider.call_api(prompt, {}, {})

    get_agent.assert_not_called()


def test_call_api_propagates_agent_runtime_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = RuntimeError("database unavailable")
    agent = Mock()
    agent.invoke.side_effect = failure
    monkeypatch.setattr(provider, "get_agent", Mock(return_value=agent))

    with pytest.raises(RuntimeError, match="database unavailable") as raised:
        provider.call_api("What was revenue?", {}, {})

    assert raised.value is failure
