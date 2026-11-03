"""Validated TypeSafe HTTP response contracts."""

from typing import Literal

from pydantic import BaseModel, Field

from agents.baseline.models import QuestionAnalysis
from etl.companies import Company


class QuestionPlan(QuestionAnalysis):
    out_of_domain: bool = Field(default=False, description="Always false: Jev has already screened domain.")
    needs_clarification: bool = Field(description=(
        "True only for essential missing intent: unidentified company, broad results/performance without a metric, "
        "or generic growth without metric/baseline. 'Results in 2026' is still broad. "
        "False for bounded profit, earnings or margins: retrieve labeled alternatives (revenue/net income etc.). "
        "False for known missing coverage: return answered with the gap, no external-search offer. "
        "A named metric and year default to annual results; fiscal/calendar ambiguity alone is not a clarification."
    ))
    companies: list[Company] = Field(default_factory=list, description=(
        "Every relevant company, using exact canonical names from listed_companies when supplied. "
        "Use [] for wholly unavailable companies and describe the gap in required_facts. "
        "Google=Alphabet, Facebook=Meta; legal entity suffixes must not be used as retrieval company names."
    ))
    required_facts: list[str] = Field(default_factory=list, description=(
        "Every fact needed for all bounded interpretations. Broad 'earnings in 2025' requires BOTH revenue "
        "and net income, plus fiscal/calendar period dates. 'Profit' requires operating income and net income. "
        "For a named metric, a year without a quarter means annual results. "
        "For broad results or unspecified growth, leave facts empty and ask for the missing intent. Do not replace revenue with EPS."
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
