"""Configuration for the Jev gate and split-model workflow."""

from pydantic import Field, SecretStr, field_validator

from agents.settings import AgentConfig
from utils import normalize_optional_string, require_nonblank_string


class AgentV2Config(AgentConfig):
    routing_model: str = Field(default="gpt-6-luna", validation_alias="AGENT_V2_ROUTING_MODEL", strict=True)
    typesafe_model: str = Field(default="jev-latest", strict=True)
    typesafe_api_key: SecretStr | None = None
    typesafe_timeout_seconds: float = Field(default=15, gt=0, allow_inf_nan=False)

    @field_validator("routing_model", "typesafe_model")
    @classmethod
    def validate_model_name(cls, value: str, info) -> str:
        return require_nonblank_string(value, field_name=info.field_name)

    @field_validator("typesafe_api_key", mode="before")
    @classmethod
    def normalize_typesafe_key(cls, value: object) -> object:
        return normalize_optional_string(value)
