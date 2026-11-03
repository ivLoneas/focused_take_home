"""Validated TypeSafe HTTP response contracts."""

from typing import Literal

from pydantic import BaseModel, Field

from agents.baseline.models import QuestionAnalysis
from etl.companies import Company


class QuestionPlan(QuestionAnalysis):
    out_of_domain: bool = Field(default=False, description="Always false: Jev has already screened domain.")
    needs_clarification: bool = Field(description=(
        "True ONLY if essential missing information prevents any useful bounded answer, e.g. unidentified company. "
        "False for revenue/net-income ambiguity or fiscal/calendar ambiguity: retrieve and answer alternatives. "
        "A named year defaults to full-year reported results; do not ask annual versus quarterly by default."
    ))
    companies: list[Company] = Field(default_factory=list, description=(
        "Every relevant company, using exact canonical names from listed_companies when supplied. "
        "Use [] for wholly unavailable companies and describe the gap in required_facts. "
        "Google=Alphabet, Facebook=Meta; legal entity suffixes must not be used as retrieval company names."
    ))
    required_facts: list[str] = Field(default_factory=list, description=(
        "Every fact needed for all bounded interpretations. Broad 'earnings in 2025' requires BOTH revenue "
        "and net income, plus fiscal/calendar period dates. 'Profit' requires operating income and net income. "
        "A year without a quarter means annual results. Do not replace revenue with EPS."
    ))


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)


class DomainAnswers(BaseModel):
    report_question: NoulAnswer
    financial_advice: NoulAnswer


class JevUsage(BaseModel):
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)


class JevResponse(BaseModel):
    model: str = Field(min_length=1)
    answers: DomainAnswers
    usage: JevUsage
