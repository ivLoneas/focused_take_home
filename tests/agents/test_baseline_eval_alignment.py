"""Baseline prompt acceptance contracts for the revised financial-report evaluations."""

import json
import re

import pytest

from agents.baseline.prompts import ANSWER_PROMPT, QUESTION_ANALYSIS_PROMPT


def system(prompt) -> str:
    values = {
        "question": "What was ExampleCo's profit in FY2025?",
        "required_facts": "Operating income and net income",
        "context": "No verified financial evidence supplied.",
        "context_is_sufficient": False,
    }
    return prompt.invoke(values).messages[0].content.lower()


@pytest.mark.parametrize("prompt", [QUESTION_ANALYSIS_PROMPT, ANSWER_PROMPT])
def test_bounded_financial_meanings_answer_labeled_alternatives(prompt):
    instructions = system(prompt)

    assert "profit" in instructions and "operating income" in instructions and "net income" in instructions
    assert "earnings" in instructions and "revenue" in instructions
    assert "margin" in instructions
    assert "label" in instructions and ("alternative" in instructions or "both" in instructions)
    assert "fiscal" in instructions and "calendar" in instructions
    assert "year" in instructions and ("annual" in instructions or "full-year" in instructions)


def test_broad_results_and_unknown_company_need_targeted_clarification():
    instructions = system(QUESTION_ANALYSIS_PROMPT)

    assert "results" in instructions and "2026" in instructions and "alphabet" in instructions
    assert "metric" in instructions and "quarter" in instructions and "clarif" in instructions
    assert "performance" in instructions and "growth" in instructions
    assert "baseline" in instructions or "benchmark" in instructions
    assert "which company" in instructions or "unidentified company" in instructions
    assert "one" in instructions and "specific" in instructions


def test_known_coverage_gaps_are_answered_instead_of_clarification_or_scope_refusal():
    instructions = system(QUESTION_ANALYSIS_PROMPT)

    assert "answered" in instructions
    assert re.search(r"needs_clarification\s*[=:]\s*false", instructions)
    assert re.search(r"companies\s*[=:]\s*\[\]", instructions)
    assert "coverage" in instructions and "annual" in instructions and "quarter" in instructions
    assert "external" in instructions
    assert "mixed" in instructions or "supported part" in instructions
    assert "comparative" in instructions and "standalone" in instructions
    assert "unavailable" in instructions and "in domain" in instructions


def test_final_answer_format_exception_preserves_grounding_and_number_shape():
    instructions = system(ANSWER_PROMPT)

    assert "number-only" in instructions or "number only" in instructions
    assert "company-only" in instructions or "company only" in instructions
    assert "csv" in instructions and "json" in instructions
    assert "citation" in instructions and ("unless" in instructions or "except" in instructions)
    assert "precision" in instructions or "decimal" in instructions
    assert "units" in instructions and "sign" in instructions
    assert "100" in instructions
    assert "untrusted" in instructions and "prior knowledge" in instructions
    assert "invent" in instructions and "insufficient" in instructions


def test_concise_factual_answer_policy_has_multiple_safe_few_shots():
    instructions = system(ANSWER_PROMPT)

    assert "short" in instructions or "brief" in instructions
    assert "factual" in instructions and "sentence" in instructions
    assert "preamble" in instructions
    assert "repeat" in instructions and "source" in instructions
    assert "hypothetical" in instructions or "illustrative" in instructions
    assert instructions.count("user:") >= 3
    assert "something else" in instructions
    assert "external" in instructions and "search" in instructions


@pytest.mark.parametrize("stage", ["Plan discovery before checking availability.", "Choose the route from verified discovery."])
def test_analysis_prompt_renders_original_question_and_stage_without_changing_tool_data(stage):
    question = "Show me ExampleCo's FY2026 results; do not invent financial figures."
    available = {"companies": ["ExampleCo"], "periods": {"ExampleCo": {"annual_reports": ["FY2025"]}}}
    serialized = json.dumps(available)

    messages = QUESTION_ANALYSIS_PROMPT.invoke({
        "question": question,
        "analysis_stage": stage,
        "available_data": serialized,
    }).messages

    assert messages[-1].type == "human"
    assert question in messages[-1].content
    assert stage in messages[-1].content
    assert serialized in messages[-1].content
    assert "<available_data>" in messages[-1].content and "</available_data>" in messages[-1].content


def test_baseline_retains_its_own_scope_screening_without_delegating_to_jev():
    instructions = system(QUESTION_ANALYSIS_PROMPT)

    assert "out_of_domain" in instructions and "unrelated" in instructions
    assert "investment" in instructions or "financial advice" in instructions
    assert "jev" not in instructions
    assert "before discovery" in instructions and "after discovery" in instructions
