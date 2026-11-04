"""HTTP request and response contracts for the web backend."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentDescriptor(BaseModel):
    """One agent exposed by the web interface."""

    id: Literal["baseline", "agent_v2"]
    name: str
    description: str


class AgentCatalogResponse(BaseModel):
    """Available web-facing agents."""

    agents: list[AgentDescriptor]


class ClarificationTurn(BaseModel):
    """A previous user request and the clarification it received."""

    model_config = ConfigDict(extra="forbid", strict=True)

    question: str = Field(min_length=1)
    clarification: str = Field(min_length=1, max_length=2000)


class RunRequest(BaseModel):
    """A question or a reply continuing a bounded clarification thread."""

    model_config = ConfigDict(extra="forbid", strict=True)

    agent_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    clarification_history: list[ClarificationTurn] = Field(default_factory=list, max_length=5)


class RunUsage(BaseModel):
    """Measured complete token usage and estimated standard API cost in USD."""

    total_tokens: int | None = Field(ge=0)
    cost_usd: float | None = Field(ge=0, allow_inf_nan=False)
    response_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    first_token_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class RunResponse(BaseModel):
    """Serializable result from the selected agent."""

    status: Literal["answered", "out_of_domain", "needs_clarification"]
    answer: str
    citations: list[str]
    retrieval_attempts: int
    source_urls: dict[str, str] = Field(default_factory=dict)
    metrics: RunUsage | None = None


class HealthResponse(BaseModel):
    """Small liveness response that does not initialize an agent."""

    status: Literal["ok"]


class ThreadTurn(RunResponse):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    created_at: str


class QuestionThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    agent_id: Literal["baseline", "agent_v2"]
    created_at: str
    updated_at: str
    turns: list[ThreadTurn] = Field(min_length=1, max_length=6)


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_thread_id: str | None = None
    threads: list[QuestionThread] = Field(default_factory=list, max_length=20)


@dataclass
class SessionRecord:
    state: SessionState
    version: int


class SessionRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    agent_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    thread_id: str | None = Field(default=None, min_length=1, max_length=100)


class ActiveThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    thread_id: str | None = Field(min_length=1, max_length=100)
