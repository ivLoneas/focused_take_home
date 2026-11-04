"""Validated configuration for the web backend."""

from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from utils import normalize_optional_string, require_nonblank_string

DEFAULT_DATABASE_URL = "postgresql://rag:rag_local@localhost:55432/rag"
DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


class Settings(BaseSettings):
    """Configuration loaded from environment variables and the local ``.env`` file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL
    openai_api_key: SecretStr | None = None
    chat_model: str = "gpt-6.1-terra"
    embedding_model: str = "text-embedding-3-small"
    retrieval_limit: int = Field(default=5, ge=1, le=100, strict=True)
    max_question_length: int = Field(default=2_000, ge=1, strict=True)
    session_ttl_seconds: int = Field(default=1800, ge=60, strict=True)
    session_cookie_secure: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))

    @field_validator("retrieval_limit", "max_question_length", "session_ttl_seconds", mode="before")
    @classmethod
    def parse_integer_setting(cls, value: object) -> object:
        if isinstance(value, str) and value.isdecimal():
            return int(value)
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        value = require_nonblank_string(value, field_name="database_url")
        parsed = urlparse(value)
        if parsed.scheme not in {"postgresql", "postgresql+psycopg"} or not parsed.hostname:
            raise ValueError("database_url must be a PostgreSQL URL")
        return value

    @field_validator("chat_model", "embedding_model")
    @classmethod
    def validate_model_name(cls, value: str, info) -> str:
        return require_nonblank_string(value, field_name=info.field_name)

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_openai_api_key(cls, value: object) -> object:
        return normalize_optional_string(value)

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("cors_origins must contain at least one origin")

        normalized = []
        for origin in origins:
            value = require_nonblank_string(origin, field_name="cors_origins")
            parsed = urlparse(value)
            if (
                value == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("cors_origins must contain only HTTP(S) origins without paths")
            normalized.append(value.rstrip("/"))
        return normalized
