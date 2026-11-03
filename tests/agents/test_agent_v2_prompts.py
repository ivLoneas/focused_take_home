"""Prompt contracts for broad interpretations, exact formats and visual evidence."""

import pytest

from agents.agent_v2 import AgentV2, AgentV2Config, JevDomainGate
from agents.agent_v2.prompts import ANSWER_PROMPT, CONTEXT_ASSESSMENT_PROMPT, QUESTION_ANALYSIS_PROMPT


def system(prompt):
    return prompt.invoke({
        "question": "What were Amazon's earnings in 2025?",
        "required_facts": "Revenue and net income", "context": "No evidence",
        "context_is_sufficient": False, "current_query": "earnings",
    }).messages[0].content.lower()


def test_package_exports_public_workflow_configuration_and_gate():
    assert AgentV2 and AgentV2Config and JevDomainGate


@pytest.mark.parametrize("prompt", [QUESTION_ANALYSIS_PROMPT, ANSWER_PROMPT])
def test_common_earnings_ambiguity_answers_all_useful_interpretations(prompt):
    text = system(prompt)
    assert "amazon" in text and "2025" in text
    assert "revenue" in text and "net income" in text
    assert "fiscal" in text and "calendar" in text
    assert "clarif" in text
    assert "both" in text or "all reasonable" in text or "interpretations" in text
    assert "date" in text and ("same" in text or "coincide" in text or "identical" in text)


def test_answer_format_exception_has_concrete_bare_number_example_and_keeps_grounding():
    text = system(ANSWER_PROMPT)
    assert "unless a user asks for a specific formatting" in text
    assert "only" in text and "number" in text and "example" in text
    assert "citations" in text and "page" in text and "source" in text
    assert "precision" in text or "decimal" in text
    assert "units" in text and "sign" in text
    assert "invent" in text and "untrusted" in text
    assert "prior knowledge" in text and "insufficient" in text


@pytest.mark.parametrize("prompt", [QUESTION_ANALYSIS_PROMPT, CONTEXT_ASSESSMENT_PROMPT, ANSWER_PROMPT])
def test_chart_and_table_instructions_preserve_panel_series_and_financial_basis(prompt):
    text = system(prompt)
    assert "panel" in text and "series" in text
    assert "row" in text and "column" in text
    assert "quarter" in text and "annual" in text
    assert "segment" in text and "total" in text
    assert "units" in text and "period" in text


def test_coverage_reasoning_allows_comparative_periods_in_retained_reports():
    text = system(QUESTION_ANALYSIS_PROMPT)
    assert "comparative" in text and "standalone" in text
    assert "listed_companies" in text and "company_periods" in text
    assert "google" in text and "alphabet" in text and "facebook" in text and "meta" in text
    assert "missing" in text and "company" in text


def test_evidence_check_requires_source_support_and_targeted_retry():
    text = system(CONTEXT_ASSESSMENT_PROMPT)
    assert "is_sufficient" in text and "refined_query" in text
    assert "source" in text and "page" in text and "untrusted" in text
    assert "missing" in text and "units" in text


def test_question_plan_schema_clarifies_only_unanswerable_essential_gaps():
    from agents.agent_v2.models import QuestionPlan

    description = QuestionPlan.model_json_schema()["properties"]["needs_clarification"]["description"].lower()
    assert "essential" in description and "bounded" in description
    assert "company" in description
    assert "fiscal" in description and "calendar" in description
    assert "revenue" in description and "net" in description
    assert "year" in description and ("annual" in description or "full-year" in description)


def test_question_plan_company_schema_uses_only_canonical_retrieval_names():
    from typing import get_args

    from agents.agent_v2.models import QuestionPlan
    from etl.companies import Company

    item_schema = QuestionPlan.model_json_schema()["properties"]["companies"]["items"]
    assert set(item_schema["enum"]) == set(get_args(Company))
    plan = QuestionPlan(needs_clarification=False, companies=list(get_args(Company)))
    assert plan.companies == list(get_args(Company))


@pytest.mark.parametrize("name", ["Meta Platforms, Inc.", "Meta Platforms Inc", "Google", "Facebook", "Walmart"])
def test_question_plan_rejects_noncanonical_company_names_before_retrieval(name):
    from pydantic import ValidationError

    from agents.agent_v2.models import QuestionPlan

    with pytest.raises(ValidationError, match="companies"):
        QuestionPlan(needs_clarification=False, companies=[name])


def test_question_plan_keeps_unsupported_company_gap_without_retrieval_name():
    from agents.agent_v2.models import QuestionPlan

    plan = QuestionPlan(needs_clarification=False, companies=[], required_facts=["Walmart reports unavailable"])
    assert plan.companies == []
    assert plan.required_facts == ["Walmart reports unavailable"]


def test_planner_explicitly_answers_known_coverage_gaps_instead_of_clarifying():
    text = system(QUESTION_ANALYSIS_PROMPT)

    assert "coverage" in text and "needs_clarification=false" in text
    assert "answered" in text
    assert "uber" in text and "net income" in text and "2025" in text
    assert "annual" in text and "quarter" in text
    assert "external" in text


@pytest.mark.parametrize("prompt", [QUESTION_ANALYSIS_PROMPT, ANSWER_PROMPT])
def test_broad_results_and_unknown_entities_remain_essential_clarification_cases(prompt):
    text = system(prompt)

    assert "alphabet" in text and "2026" in text and "results" in text
    assert "clarif" in text and "metric" in text and "period" in text
    assert "unidentified company" in text or "which company" in text or "unknown company" in text


def test_question_plan_schema_distinguishes_coverage_gaps_and_broad_results():
    from agents.agent_v2.models import QuestionPlan

    description = QuestionPlan.model_json_schema()["properties"]["needs_clarification"]["description"].lower()

    assert "coverage" in description
    assert "false" in description
    assert "results" in description and "metric" in description


def test_answer_prompt_demonstrates_short_factual_answers_and_bounds_followups():
    text = system(ANSWER_PROMPT)

    assert "short" in text or "brief" in text
    assert "factual" in text and "sentence" in text
    assert "preamble" in text
    assert "repeat" in text and "source" in text
    assert "hypothetical" in text
    assert text.count("example") >= 3 or text.count("user:") >= 3
    assert "uber" in text and "something else" in text
    assert "external" in text and "search" in text
