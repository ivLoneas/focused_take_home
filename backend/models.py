"""HTTP request and response contracts for the web backend."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentDescriptor(BaseModel):
    """One agent exposed by the web interface."""

    id: Literal["baseline"]
    name: str
    description: str


class AgentCatalogResponse(BaseModel):
    """Available web-facing agents."""

    agents: list[AgentDescriptor]


class RunRequest(BaseModel):
    """One independent agent invocation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    agent_id: str = Field(min_length=1)
    question: str = Field(min_length=1)


class RunResponse(BaseModel):
    """Serializable result from the selected agent."""

    status: Literal["answered", "out_of_domain", "needs_clarification"]
    answer: str
    citations: list[str]
    retrieval_attempts: int


class HealthResponse(BaseModel):
    """Small liveness response that does not initialize an agent."""

    status: Literal["ok"]
