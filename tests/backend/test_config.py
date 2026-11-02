"""Configuration and dependency-wiring contracts for the web backend."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr, ValidationError

from backend import dependencies
from backend.config import Settings


def valid_settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql://rag:rag@localhost:5432/rag",
        "openai_api_key": "test-openai-secret",
        "chat_model": "gpt-4.1-mini",
        "embedding_model": "text-embedding-3-small",
        "retrieval_limit": 5,
        "max_question_length": 2000,
        "cors_origins": ["http://localhost:5173"],
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("field", ["chat_model", "embedding_model"])
@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_model_names_must_be_nonblank(field: str, value: str):
    with pytest.raises(ValidationError):
        valid_settings(**{field: value})


@pytest.mark.parametrize(
    "database_url",
    ["", "sqlite:///local.db", "https://database.example/rag", "not a url"],
)
def test_database_url_must_be_a_postgresql_url(database_url: str):
    with pytest.raises(ValidationError):
        valid_settings(database_url=database_url)


@pytest.mark.parametrize("database_url", ["postgresql://host/rag", "postgresql+psycopg://host/rag"])
def test_supported_postgresql_urls_are_accepted(database_url: str):
    assert valid_settings(database_url=database_url).database_url == database_url


@pytest.mark.parametrize("retrieval_limit", [0, 101, True, 1.5])
def test_retrieval_limit_is_an_integer_in_pgvector_supported_range(retrieval_limit):
    with pytest.raises((ValidationError, TypeError)):
        valid_settings(retrieval_limit=retrieval_limit)


@pytest.mark.parametrize("max_question_length", [0, -1, True, 1.5])
def test_max_question_length_must_be_a_positive_integer(max_question_length):
    with pytest.raises((ValidationError, TypeError)):
        valid_settings(max_question_length=max_question_length)


@pytest.mark.parametrize(
    "origin",
    ["*", "", "localhost:5173", "file:///tmp/frontend/index.html", "https://example.com/path"],
)
def test_cors_origins_must_be_narrow_http_origins(origin: str):
    with pytest.raises(ValidationError):
        valid_settings(cors_origins=[origin])


def test_openai_api_key_is_stored_as_a_masked_secret():
    settings = valid_settings(openai_api_key="sk-private-test-value")

    assert isinstance(settings.openai_api_key, SecretStr)
    assert settings.openai_api_key.get_secret_value() == "sk-private-test-value"
    assert "sk-private-test-value" not in repr(settings)
    assert "sk-private-test-value" not in str(settings)


def test_openai_api_key_is_loaded_from_dotenv_as_a_masked_secret(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=sk-dotenv-private-value\n", encoding="utf-8")

    settings = Settings(
        database_url="postgresql://rag:rag@localhost:5432/rag",
        chat_model="gpt-4.1-mini",
        embedding_model="text-embedding-3-small",
        retrieval_limit=5,
        max_question_length=2000,
        cors_origins=["http://localhost:5173"],
        _env_file=dotenv,
    )

    assert isinstance(settings.openai_api_key, SecretStr)
    assert settings.openai_api_key.get_secret_value() == "sk-dotenv-private-value"
    assert "sk-dotenv-private-value" not in repr(settings)


@pytest.mark.parametrize("value", [None, "", " ", "\t\n"])
def test_missing_or_blank_openai_api_key_is_allowed_for_non_agent_endpoints(value):
    settings = valid_settings(openai_api_key=value)

    assert settings.openai_api_key is None


@pytest.mark.parametrize("value", [None, "", " ", "\t\n"])
def test_agent_construction_rejects_missing_or_blank_openai_api_key(monkeypatch, value):
    chat_openai = Mock()
    openai_embeddings = Mock()
    monkeypatch.setattr(dependencies, "ChatOpenAI", chat_openai)
    monkeypatch.setattr(dependencies, "OpenAIEmbeddings", openai_embeddings)
    settings = valid_settings(openai_api_key=value)

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        dependencies.build_baseline_agent(settings)

    chat_openai.assert_not_called()
    openai_embeddings.assert_not_called()


def test_build_baseline_agent_wires_existing_components_without_connecting(monkeypatch):
    agent_config = SimpleNamespace(model="gpt-test-model")
    chat_model = object()
    embeddings = object()
    pgvector_retriever = object()
    adapter = object()
    baseline_agent = object()

    chat_openai = Mock(return_value=chat_model)
    openai_embeddings = Mock(return_value=embeddings)
    pgvector = Mock(return_value=pgvector_retriever)
    adapter_factory = Mock(return_value=adapter)
    baseline_factory = Mock(return_value=baseline_agent)
    agent_config_type = Mock(return_value=agent_config)
    connect = Mock()

    monkeypatch.setattr(dependencies, "ChatOpenAI", chat_openai)
    monkeypatch.setattr(dependencies, "OpenAIEmbeddings", openai_embeddings)
    monkeypatch.setattr(dependencies, "PgVectorRetriever", pgvector)
    monkeypatch.setattr(dependencies, "BaselineRetrieverAdapter", adapter_factory)
    monkeypatch.setattr(dependencies, "BaselineAgent", baseline_factory)
    monkeypatch.setattr(dependencies, "AgentConfig", agent_config_type)
    monkeypatch.setattr(dependencies.psycopg, "connect", connect)

    settings = valid_settings(
        database_url="postgresql+psycopg://rag:secret@db:5432/reports",
        chat_model="gpt-test-model",
        embedding_model="embedding-test-model",
        retrieval_limit=7,
        openai_api_key="sk-explicit-private-value",
    )
    result = dependencies.build_baseline_agent(settings)

    assert result is baseline_agent
    agent_config_type.assert_called_once_with(model="gpt-test-model")
    chat_openai.assert_called_once_with(
        model="gpt-test-model",
        api_key=settings.openai_api_key,
    )
    openai_embeddings.assert_called_once_with(
        model="embedding-test-model",
        api_key=settings.openai_api_key,
    )
    pgvector.assert_called_once()
    assert pgvector.call_args.kwargs["embeddings"] is embeddings
    assert pgvector.call_args.kwargs["limit"] == 7
    connection_factory = pgvector.call_args.kwargs["connection_factory"]
    assert callable(connection_factory)
    connect.assert_not_called()
    adapter_factory.assert_called_once_with(retriever=pgvector_retriever)
    baseline_factory.assert_called_once_with(chat_model, retriever=adapter, config=agent_config)

    connection_factory()

    connect.assert_called_once_with("postgresql+psycopg://rag:secret@db:5432/reports")
