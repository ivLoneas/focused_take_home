"""Promptfoo Python provider for the baseline financial-report agent."""

from functools import lru_cache, partial
from pathlib import Path
from typing import Any

import psycopg
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agents.baseline.baseline_agent import BaselineAgent
from agents.retrieval import BaselineRetrieverAdapter, PgVectorRetriever
from agents.settings import AgentConfig
from etl.settings import DEFAULT_DATABASE_URL
from utils import normalize_optional_string, require_nonblank_string

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="EVAL_",
        extra="ignore",
    )

    openai_api_key: SecretStr = Field(validation_alias="OPENAI_API_KEY")
    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        validation_alias=AliasChoices("EVAL_DATABASE_URL", "DATABASE_URL"),
    )
    chat_model: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, gt=0)
    retrieval_limit: int = Field(default=8, gt=0, le=100)
    max_retrieval_attempts: int = Field(default=3, gt=0)

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        value = normalize_optional_string(value)
        if value is None:
            raise ValueError("openai_api_key is required")
        return require_nonblank_string(value, field_name="openai_api_key")

    @field_validator("database_url", "chat_model", "embedding_model")
    @classmethod
    def require_nonblank_string(cls, value: str) -> str:
        return require_nonblank_string(value)


def build_agent(settings: ProviderSettings) -> BaselineAgent:
    """Wire the model, embeddings, pgvector retrieval, and baseline workflow."""

    api_key = settings.openai_api_key.get_secret_value()
    agent_config = AgentConfig(model=settings.chat_model)
    model = ChatOpenAI(model=agent_config.model, temperature=0, api_key=api_key)
    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        api_key=api_key,
    )
    retriever = PgVectorRetriever(
        embeddings=embeddings,
        connection_factory=partial(psycopg.connect, settings.database_url),
        limit=settings.retrieval_limit,
    )
    adapter = BaselineRetrieverAdapter(retriever=retriever)  # ty: ignore[invalid-argument-type]
    return BaselineAgent(
        model,  # ty: ignore[invalid-argument-type]
        retriever=adapter,
        max_retrieval_attempts=settings.max_retrieval_attempts,
        config=agent_config,
    )


@lru_cache(maxsize=1)
def get_agent() -> BaselineAgent:
    """Cache expensive model, graph, embeddings, and retriever construction."""

    return build_agent(ProviderSettings())


def call_api(prompt: object, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Translate Promptfoo's provider contract to baseline output and trajectory metadata."""

    del options, context
    prompt = require_nonblank_string(prompt, field_name="prompt")

    result = get_agent().invoke(prompt)
    return {
        "output": result.answer,
        "metadata": {
            "status": result.status,
            "citations": list(result.citations),
            "retrieval_attempts": result.retrieval_attempts,
        },
    }
