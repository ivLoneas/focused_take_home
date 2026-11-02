from dataclasses import dataclass
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from agents.tools.models import RetrievalRequest, RetrievedChunk

__all__ = [
    "BaselineResult",
    "ContextAssessment",
    "QuestionAnalysis",
    "RetrievalRequest",
    "RetrievedChunk",
    "WorkflowState",
]


@dataclass(frozen=True)
class BaselineResult:
    status: Literal["answered", "out_of_domain", "needs_clarification"]
    answer: str
    citations: tuple[str, ...]
    retrieval_attempts: int
    tool_calls: tuple[dict[str, object], ...] = ()


class QuestionAnalysis(BaseModel):
    """Routing decision and retrieval plan for the user's question."""

    out_of_domain: bool = Field(description="True for requests unrelated to the supported public financial reports")
    needs_clarification: bool = Field(description="True when company, period, or metric details are missing")
    clarification_question: str | None = Field(
        default=None,
        description="One specific question that requests only the missing details",
    )
    required_facts: list[str] = Field(default_factory=list, description="Facts required for a complete answer")
    coverage_requested: bool = Field(
        default=False,
        description="True when the user asks to list available companies or periods, including alongside facts",
    )
    companies: list[str] = Field(
        default_factory=list,
        description=(
            "Company names mentioned or needed, including potentially unavailable companies during planning. "
            "After discovery, use only names verified by listed_companies for factual retrieval. "
            "One separate search per company; Google=Alphabet, Facebook=Meta."
        ),
    )
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
    available_data: dict[str, object]
    tool_calls: list[dict[str, object]]
