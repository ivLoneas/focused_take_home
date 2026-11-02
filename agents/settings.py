"""Validated runtime configuration shared by agent implementations."""

from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from utils import normalize_optional_string, require_nonblank_string

DEFAULT_AGENT_MODEL = "gpt-5-mini"
DEFAULT_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
DEFAULT_LANGSMITH_PROJECT = "focused-take-home"


class AgentConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    model: str = Field(default=DEFAULT_AGENT_MODEL, validation_alias="AGENT_MODEL", strict=True)
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = DEFAULT_LANGSMITH_PROJECT
    langsmith_endpoint: str = DEFAULT_LANGSMITH_ENDPOINT

    @field_validator("langsmith_api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        return normalize_optional_string(value)

    @field_validator("model", "langsmith_project")
    @classmethod
    def validate_nonblank_name(cls, value: str, info) -> str:
        return require_nonblank_string(value, field_name=info.field_name)

    @field_validator("langsmith_endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("langsmith_endpoint must be an HTTP(S) URL")
        return value.rstrip("/")

    @model_validator(mode="after")
    def require_api_key_for_tracing(self) -> AgentConfig:
        if self.langsmith_tracing and self.langsmith_api_key is None:
            raise ValueError("LANGSMITH_API_KEY is required when LANGSMITH_TRACING is enabled")
        return self
