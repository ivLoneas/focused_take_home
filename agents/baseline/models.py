from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    required_facts: tuple[str, ...]
    attempt: int


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BaselineResult:
    status: Literal["answered", "out_of_domain", "needs_clarification"]
    answer: str
    citations: tuple[str, ...]
    retrieval_attempts: int


class QuestionAnalysis(BaseModel):
    """Routing decision and retrieval plan for the user's question."""

    out_of_domain: bool = Field(description="True when the question cannot be answered from financial reports")
    needs_clarification: bool = Field(description="True when company, period, or metric details are missing")
    clarification_question: str | None = Field(
        default=None,
        description="One specific question that requests only the missing details",
    )
    required_facts: list[str] = Field(default_factory=list, description="Facts required for a complete answer")
    retrieval_query: str = Field(default="", description="Focused search query for the first retrieval attempt")


class ContextAssessment(BaseModel):
    """Decision made after each retrieval attempt."""

    is_sufficient: bool = Field(description="Whether the evidence can support a complete answer")
    refined_query: str | None = Field(
        default=None,
        description="A more targeted query for the next attempt when evidence is insufficient",
    )


class WorkflowState(TypedDict, total=False):
    question: str
    analysis: QuestionAnalysis
    retrieval_query: str
    context: list[RetrievedChunk]
    retrieval_attempts: int
    context_is_sufficient: bool
    status: Literal["answered", "out_of_domain", "needs_clarification"]
    answer: str
