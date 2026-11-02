"""Unit contract for the Promptfoo Python provider around ``BaselineAgent``."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr, ValidationError

from evals import provider


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
    built_agent = object()
    chat_openai = Mock(return_value=chat_model)
    openai_embeddings = Mock(return_value=embeddings)
    pgvector = Mock(return_value=pgvector_retriever)
    adapter_type = Mock(return_value=adapter)
    baseline_type = Mock(return_value=built_agent)
    agent_config_type = Mock(return_value=agent_config)
    connect = Mock(return_value=object())
    monkeypatch.setattr(provider, "ChatOpenAI", chat_openai)
    monkeypatch.setattr(provider, "OpenAIEmbeddings", openai_embeddings)
    monkeypatch.setattr(provider, "PgVectorRetriever", pgvector)
    monkeypatch.setattr(provider, "BaselineRetrieverAdapter", adapter_type)
    monkeypatch.setattr(provider, "BaselineAgent", baseline_type)
    monkeypatch.setattr(provider, "AgentConfig", agent_config_type)
    monkeypatch.setattr(provider.psycopg, "connect", connect)
    configured = settings()

    result = provider.build_agent(configured)

    assert result is built_agent
    agent_config_type.assert_called_once_with(model="chat-test")
    chat_openai.assert_called_once_with(model="chat-test", temperature=0, api_key="sk-test")
    openai_embeddings.assert_called_once_with(
        model="embedding-test",
        dimensions=1536,
        api_key="sk-test",
    )
    pgvector.assert_called_once()
    pgvector_kwargs = pgvector.call_args.kwargs
    assert pgvector_kwargs["embeddings"] is embeddings
    assert pgvector_kwargs["limit"] == 7
    assert callable(pgvector_kwargs["connection_factory"])
    assert connect.call_count == 0
    connection = pgvector_kwargs["connection_factory"]()
    assert connection is connect.return_value
    connect.assert_called_once_with(configured.database_url)
    adapter_type.assert_called_once_with(retriever=pgvector_retriever)
    baseline_type.assert_called_once_with(
        chat_model,
        retriever=adapter,
        max_retrieval_attempts=2,
        config=agent_config,
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
    assert response == {
        "output": result.answer,
        "metadata": {
            "status": "answered",
            "citations": ["ExampleCo report p. 10"],
            "retrieval_attempts": 2,
        },
    }


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
