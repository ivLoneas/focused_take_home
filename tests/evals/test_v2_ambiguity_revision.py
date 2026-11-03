"""Revised ambiguity cases distinguish missing intent from bounded financial meanings."""

import csv
from pathlib import Path

import pytest

from evals.generate_tests import generate_tests

ROOT = Path(__file__).resolve().parents[2]


def rows(name: str) -> list[dict[str, str]]:
    with (ROOT / "evals" / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


@pytest.mark.parametrize(
    "answerable_question",
    [
        "What was Amazon's profit in 2025?",
        "What was Meta's profit in 2025?",
        "Compare Apple's and Netflix's margins for 2025.",
        "Did Alphabet's revenue grow 18% or 15% in 2025?",
        "How much did Meta spend on capital expenditures in 2025: the quarter or the whole year?",
    ],
)
def test_bounded_financial_meanings_are_not_in_clarification_only_topic(answerable_question):
    ambiguous = [row for row in rows("evals_tests.csv") if row["topic"] == "ambiguous_questions"]

    assert answerable_question not in {row["test"] for row in ambiguous}


def test_revised_ambiguity_cases_preserve_ids_and_require_one_specific_clarification():
    dataset = rows("evals_tests.csv")
    ambiguous = [row for row in dataset if row["topic"] == "ambiguous_questions"]

    assert len(dataset) == 114
    assert {row["id"] for row in ambiguous} == {f"AMB{i:02}" for i in range(1, 11) if i != 4}
    for row in ambiguous:
        expected = row["answer"].lower()
        assert "ask" in expected or "clarif" in expected, row["id"]
        assert "alternatives are acceptable" not in row["annotations"].lower(), row["id"]
        assert "or give" not in expected, row["id"]
        assert row["allow_no_retrieval"] != "true", row["id"]
    assert next(row for row in ambiguous if row["id"] == "AMB06")["test"] == "Show me Alphabet's 2026 results."


def test_bounded_profit_and_margin_questions_have_grounded_answer_acceptance_cases():
    behavior = rows("agent_v2_cases.csv")
    assert len({row["id"] for row in behavior}) == len(behavior)
    for question in ("What was Amazon's profit in 2025?", "What was Meta's profit in 2025?"):
        case = next(row for row in behavior if row["test"] == question)
        assert case["topic"] != "ambiguous_questions"
        assert "operating income" in case["answer"].lower() and "net income" in case["answer"].lower()
        assert case["allow_no_retrieval"] == "false"
    margins = next(row for row in behavior if row["test"] == "Compare Apple's and Netflix's margins for 2025.")
    assert margins["topic"] != "ambiguous_questions"
    assert "operating" in margins["answer"].lower() and "net" in margins["answer"].lower()
    assert set(margins["required_period_companies"].split(",")) == {"Apple", "Netflix"}
    assert margins["allow_no_retrieval"] == "false"


def test_coverage_gap_cases_keep_answered_metadata_only_route_available():
    cases = generate_tests()
    missing_data = [case["vars"] for case in cases if case["vars"]["topic"] == "in_domain_no_data"]

    assert len(missing_data) == 10
    assert all(row["allow_no_retrieval"] == "true" for row in missing_data)
    assert all("listed_companies" in row["required_tools"] for row in missing_data)


def test_explicit_annual_and_quarter_alternatives_remain_answerable_in_behavior_suite():
    cases = generate_tests({"dataset_path": ROOT / "evals/agent_v2_cases.csv"})
    by_id = {case["vars"]["id"]: case for case in cases}

    for case_id in ("V204", "V205"):
        values = by_id[case_id]["vars"]
        assert values["topic"] != "ambiguous_questions"
        assert values["allow_no_retrieval"] == "false"
        assert "quarter" in values["answer"].lower() or "q4" in values["answer"].lower()
        assert "annual" in values["answer"].lower() or "full-year" in values["answer"].lower()
