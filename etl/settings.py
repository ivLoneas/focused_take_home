"""Validated ETL configuration loaded from environment and .env files."""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from utils import normalize_optional_string

DEFAULT_DATABASE_URL = "postgresql://rag:rag_local@localhost:55432/rag"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL
    openai_api_key: SecretStr | None = None

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_openai_api_key(cls, value: object) -> object:
        return normalize_optional_string(value)
