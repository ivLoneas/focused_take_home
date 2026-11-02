"""Coverage evaluations must prove discovery, including company arguments."""

import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evals import provider
from evals.assertions import assert_trajectory
from evals.generate_tests import generate_tests


def context(*, calls=None, **values):
    return {
        "vars": {
            "id": "NOD01", "topic": "in_domain_no_data", "required_tools": "listed_companies,company_periods",
            "required_period_companies": "Apple", "allow_no_retrieval": "true", **values,
        },
        "metadata": {
            "status": "answered", "citations": [], "retrieval_attempts": 0,
            "tool_calls": calls if calls is not None else [
                {"name": "listed_companies", "arguments": {}},
                {"name": "company_periods", "arguments": {"company": "Apple"}},
            ],
        },
    }


def test_verified_company_period_gap_can_answer_without_evidence_retrieval():
    assert assert_trajectory("No report for that period.", context())["pass"] is True


@pytest.mark.parametrize("calls", [[], [{"name": "listed_companies", "arguments": {}}], [
    {"name": "listed_companies", "arguments": {}},
    {"name": "company_periods", "arguments": {"company": "Amazon"}},
], None, "listed_companies,company_periods"])
def test_coverage_checks_reject_missing_or_wrong_company_calls(calls):
    values = context()
    values["metadata"]["tool_calls"] = calls
    result = assert_trajectory("No reports.", values)
    assert result["pass"] is False
    assert "tool" in result["reason"].lower() or "compan" in result["reason"].lower()


def test_every_comparison_company_requires_a_period_lookup():
    values = context(required_period_companies="Apple,Amazon")
    assert assert_trajectory("Missing comparison.", values)["pass"] is False
    values["metadata"]["tool_calls"].append({"name": "company_periods", "arguments": {"company": "Amazon"}})
    assert assert_trajectory("Missing comparison.", values)["pass"] is True


def test_discovery_does_not_satisfy_required_financial_evidence_retrieval():
    values = context(allow_no_retrieval="false")
    result = assert_trajectory("Missing evidence.", values)
    assert result["pass"] is False
    assert "retriev" in result["reason"].lower()


def test_generator_preserves_optional_discovery_expectations(tmp_path):
    path = tmp_path / "cases.csv"
    row = {
        "id": "NOD01", "test": "What was Apple's FY2030 revenue?", "topic": "in_domain_no_data",
        "answer": "That period is unavailable.", "source": "Database coverage", "annotations": "Check period tool.",
        "required_tools": "listed_companies,company_periods", "required_period_companies": "Apple",
        "allow_no_retrieval": "true",
    }
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)

    assert generate_tests({"dataset_path": path})[0]["vars"] == row


def test_provider_exports_actual_tool_trajectory_for_deterministic_evaluations(monkeypatch):
    calls = ({"name": "listed_companies", "arguments": {}},)
    result = SimpleNamespace(answer="Available companies.", status="answered", citations=(), retrieval_attempts=0, tool_calls=calls)
    agent = Mock()
    agent.invoke.return_value = result
    monkeypatch.setattr(provider, "get_agent", lambda: agent)

    response = provider.call_api("Which companies are available?", {}, {})

    assert response["metadata"]["tool_calls"] == list(calls)


def test_real_scope_evaluation_requires_live_company_and_period_discovery():
    root = Path(__file__).resolve().parents[2]
    with (root / "evals/evals_tests.csv").open(newline="") as stream:
        rows = {row["id"]: row for row in csv.DictReader(stream)}
    scope = rows["COV01"]
    assert set(scope["required_tools"].split(",")) == {"listed_companies", "company_periods"}
    assert scope["allow_no_retrieval"] == "true"
    assert set(scope["required_period_companies"].split(",")) == {"Alphabet", "Amazon", "Apple", "Meta", "Netflix"}
    missing = [row for row in rows.values() if row["topic"] == "in_domain_no_data"]
    assert any(row.get("required_tools") and row.get("allow_no_retrieval") == "true" for row in missing)


@pytest.mark.parametrize("record", [None, "listed_companies", {}, {"name": 42, "arguments": {}},
    {"name": "company_periods", "arguments": "Apple"}])
def test_malformed_tool_records_fail_without_raising(record):
    result = assert_trajectory("No reports.", context(calls=[record]))
    assert result["pass"] is False
