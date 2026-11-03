"""Independent contracts for evidence-flexible grading and exact output formats."""

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from evals import assertions
from evals.generate_tests import generate_tests

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_FIELDS = (
    "id",
    "test",
    "topic",
    "answer",
    "source",
    "annotations",
    "required_tools",
    "required_period_companies",
    "allow_no_retrieval",
)
NON_AMBIGUITY_ROWS_SHA256 = "e117ab264f63e1a3e1007d457b1f60d47bca4884bf0900b3961aa4d6c5769493"


def row(**overrides: str) -> dict[str, str]:
    values = {
        "id": "FMT01",
        "test": "What was Google's Q1 FY2025 revenue? Return only the number in millions, without commas.",
        "topic": "formatting_questions",
        "answer": "90234",
        "source": "Alphabet Q1 FY2025 earnings release, revenue table",
        "annotations": "The requested unit is millions; do not add prose or citations to the output.",
        "output_pattern": r"\d+",
    }
    values.update(overrides)
    return values


def write_dataset(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(dict.fromkeys(field for item in rows for field in item))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def format_context(pattern: object = r"\d+") -> dict[str, object]:
    return {"vars": {"id": "FMT01", "topic": "formatting_questions", "output_pattern": pattern}}


def verdict(output: object, context: dict[str, object]) -> dict[str, object]:
    result = assertions.assert_output_format(output, context)
    assert isinstance(result["reason"], str) and result["reason"].strip()
    assert result["score"] == (1 if result["pass"] else 0)
    return result


def test_formatting_cases_preserve_vars_and_add_a_fourth_independent_assertion(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.csv"
    source = row()
    write_dataset(dataset, [source])

    case = generate_tests({"dataset_path": dataset})[0]

    assert case["vars"] == source
    assert case["metadata"] == {"id": "FMT01", "topic": "formatting_questions"}
    by_metric = {item["metric"]: item for item in case["assert"]}
    assert len(case["assert"]) == 4
    assert set(by_metric) == {"response_validity", "workflow_behavior", "answer_quality", "format_compliance"}
    assert by_metric["format_compliance"] == {
        "type": "python",
        "value": "file://assertions.py:assert_output_format",
        "metric": "format_compliance",
    }


def test_existing_cases_with_a_blank_optional_pattern_keep_three_assertions(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.csv"
    write_dataset(dataset, [row(id="ACC01", topic="deterministic_accuracy", output_pattern="")])

    case = generate_tests({"dataset_path": dataset})[0]

    assert len(case["assert"]) == 3
    assert "format_compliance" not in {item["metric"] for item in case["assert"]}


def test_a_non_formatting_topic_can_opt_into_the_format_assertion(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.csv"
    write_dataset(dataset, [row(id="ACC01", topic="deterministic_accuracy")])

    case = generate_tests({"dataset_path": dataset})[0]

    assert len(case["assert"]) == 4
    assert "format_compliance" in {item["metric"] for item in case["assert"]}


@pytest.mark.parametrize("pattern", ["", " \t"])
def test_formatting_cases_require_a_nonblank_pattern(tmp_path: Path, pattern: str) -> None:
    dataset = tmp_path / "cases.csv"
    write_dataset(dataset, [row(output_pattern=pattern)])

    with pytest.raises(ValueError, match=r"FMT01.*output_pattern"):
        generate_tests({"dataset_path": dataset})


def test_formatting_cases_require_the_optional_pattern_column(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.csv"
    values = row()
    del values["output_pattern"]
    write_dataset(dataset, [values])

    with pytest.raises(ValueError, match=r"FMT01.*output_pattern"):
        generate_tests({"dataset_path": dataset})


@pytest.mark.parametrize("topic", ["formatting_questions", "deterministic_accuracy"])
@pytest.mark.parametrize("pattern", ["(", "[", "\\"])
def test_invalid_supplied_patterns_fail_before_model_execution(tmp_path: Path, topic: str, pattern: str) -> None:
    dataset = tmp_path / "cases.csv"
    write_dataset(dataset, [row(topic=topic, output_pattern=pattern)])

    with pytest.raises(ValueError, match=r"FMT01.*output_pattern"):
        generate_tests({"dataset_path": dataset})


@pytest.mark.parametrize("output", ["90234", " 90234 ", "\n90234\n"])
def test_number_only_output_accepts_incidental_surrounding_whitespace(output: str) -> None:
    assert verdict(output, format_context())["pass"] is True


@pytest.mark.parametrize(
    "output",
    ["Revenue: 90234", "90234 million", "90234 [Report p. 1]", "```\n90234\n```", "90,234", "90234\n90234", "90234.0"],
)
def test_number_only_output_rejects_prose_units_citations_markup_and_wrong_shape(output: str) -> None:
    assert verdict(output, format_context())["pass"] is False


def test_format_check_does_not_claim_financial_correctness() -> None:
    assert verdict("12345", format_context())["pass"] is True


@pytest.mark.parametrize("output,passed", [("23.49", True), ("23.4", False), ("23.490", False), ("23", False)])
def test_decimal_precision_is_enforced(output: str, passed: bool) -> None:
    assert verdict(output, format_context(r"\d+\.\d{2}"))["pass"] is passed


@pytest.mark.parametrize(
    "output,passed",
    [("Apple", True), ("Amazon", True), ("Apple.", False), ("apple", False), ("Apple earned more", False)],
)
def test_company_name_format_accepts_either_requested_company_without_grading_the_winner(
    output: str, passed: bool
) -> None:
    assert verdict(output, format_context(r"(?:Apple|Amazon)"))["pass"] is passed


@pytest.mark.parametrize("output", [None, 90234, b"90234", "", "  \t\n"])
def test_format_check_rejects_missing_non_string_or_blank_answers(output: object) -> None:
    assert verdict(output, format_context())["pass"] is False


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"vars": None},
        {"vars": []},
        {"vars": {}},
        format_context(None),
        format_context(123),
        format_context(""),
        format_context(" \t"),
        format_context("("),
    ],
)
def test_format_check_reports_malformed_metadata_without_raising(context: dict[str, object]) -> None:
    assert verdict("90234", context)["pass"] is False


def trajectory_context(**overrides: object) -> dict[str, object]:
    return {
        "vars": {
            "id": "FMT01",
            "topic": "formatting_questions",
            "required_tools": "listed_companies,company_periods",
            "required_period_companies": "Alphabet",
        },
        "metadata": {
            "status": "answered",
            "citations": ["Alphabet Q1 FY2025 earnings release p. 1"],
            "retrieval_attempts": 1,
            "tool_calls": [
                {"name": "listed_companies", "arguments": {}},
                {"name": "company_periods", "arguments": {"company": "Alphabet"}},
            ],
            **overrides,
        },
    }


def test_formatting_answers_need_evidence_metadata_without_inline_citations() -> None:
    assert assertions.assert_trajectory("90234", trajectory_context())["pass"] is True


@pytest.mark.parametrize(
    "overrides", [{"retrieval_attempts": 0}, {"citations": []}, {"status": "needs_clarification"}, {"tool_calls": []}]
)
def test_formatting_trajectory_still_requires_financial_retrieval_and_actual_discovery(
    overrides: dict[str, object],
) -> None:
    assert assertions.assert_trajectory("90234", trajectory_context(**overrides))["pass"] is False


def test_judge_rubric_has_question_and_explicit_evidence_flexibility_rules(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.csv"
    write_dataset(dataset, [row(id="ACC01", topic="deterministic_accuracy", output_pattern="")])
    case = generate_tests({"dataset_path": dataset})[0]
    rubric = next(item["value"] for item in case["assert"] if item["metric"] == "answer_quality")
    normalized = " ".join(rubric.lower().split())

    assert "{{test}}" in rubric, "The judge must see the actual output/citation instructions"
    assert "{{answer}}" in rubric and "{{source}}" in rubric and "{{annotations}}" in rubric
    assert "non-exhaustive" in normalized or "not exhaustive" in normalized
    assert "equivalent" in normalized and "corpus" in normalized
    assert "page" in normalized and "report" in normalized
    assert "unless explicitly requested" in normalized
    assert "format" in normalized and "separate" in normalized
    assert "clarification" in normalized and "refusal" in normalized
    assert "units" in normalized and "periods" in normalized
    assert "gaap" in normalized
    assert "grounded answers must identify the expected report" not in normalized


def test_ambiguity_revision_preserves_unrelated_cases_and_ten_formatting_questions() -> None:
    with (ROOT / "evals/evals_tests.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    originals = [{field: item[field] for field in ORIGINAL_FIELDS} for item in rows[:104]]
    resolved_period = next(item for item in originals if item["id"] == "AMB04")
    assert resolved_period["topic"] == "deterministic_accuracy"
    assert resolved_period["required_tools"] == "listed_companies,company_periods"
    assert resolved_period["required_period_companies"] == "Apple"
    assert resolved_period["allow_no_retrieval"] == "false"
    assert "416.161" in resolved_period["answer"]
    assert "September 27, 2025" in resolved_period["answer"]
    assert "fiscal" in resolved_period["answer"].lower()
    assert "Clarify calendar versus fiscal year" not in resolved_period["answer"]
    unchanged = [item for item in originals if not item["id"].startswith("AMB")]
    digest = hashlib.sha256(json.dumps(unchanged, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    assert len(unchanged) == 94
    assert digest == NON_AMBIGUITY_ROWS_SHA256, "Ambiguity revisions must preserve unrelated evaluation cases"
    formats = rows[104:]
    assert len(formats) == 10
    assert [item["id"] for item in formats] == [f"FMT{i:02}" for i in range(1, 11)]
    assert all(item["topic"] == "formatting_questions" for item in formats)
    for item in formats:
        assert re.fullmatch(item["output_pattern"], item["answer"].strip()), item["id"]
        assert "return only" in item["test"].lower(), item["id"]
        assert set(item["required_tools"].split(",")) == {"listed_companies", "company_periods"}
        assert item["required_period_companies"].strip(), item["id"]
        assert item["allow_no_retrieval"] == "false", item["id"]


def test_amb04_accepts_a_grounded_answer_that_resolves_the_fiscal_period() -> None:
    case = next(item for item in generate_tests() if item["vars"]["id"] == "AMB04")
    assert case["vars"]["topic"] == "deterministic_accuracy"
    context = {
        "vars": case["vars"],
        "metadata": {
            "status": "answered",
            "citations": ["Apple FY2025 Form 10-K p. 32"],
            "retrieval_attempts": 1,
            "tool_calls": [
                {"name": "listed_companies", "arguments": {}},
                {"name": "company_periods", "arguments": {"company": "Apple"}},
            ],
        },
    }
    answer = (
        "Apple's fiscal 2025 net sales were $416,161 million for the year ended September 27, 2025 "
        "[Apple FY2025 Form 10-K p. 32]."
    )

    assert assertions.assert_trajectory(answer, context)["pass"] is True
    context["metadata"].update(retrieval_attempts=0, citations=[])
    assert assertions.assert_trajectory(answer, context)["pass"] is False
