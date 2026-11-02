"""Contract tests for the Promptfoo CSV test generator."""

import csv
from pathlib import Path

import pytest

from evals.generate_tests import REQUIRED_FIELDS, SUPPORTED_TOPICS, generate_tests

EXPECTED_FIELDS = ("id", "test", "topic", "answer", "source", "annotations")
EXPECTED_TOPICS = {
    "ambiguous_questions",
    "conditional_reasoning",
    "deterministic_accuracy",
    "extra_calculation",
    "formatting_questions",
    "image_questions",
    "in_domain_no_data",
    "multiple_companies",
    "out_of_distribution",
    "table_questions",
    "tool_usage",
}


def write_dataset(path: Path, rows: list[dict[str, str]], fieldnames: tuple[str, ...] = EXPECTED_FIELDS) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def row(**overrides: str) -> dict[str, str]:
    values = {
        "id": "ACC01",
        "test": "What revenue did ExampleCo report?",
        "topic": "deterministic_accuracy",
        "answer": "$10 billion.",
        "source": "ExampleCo 2025 annual report, p. 10",
        "annotations": "Use the annual revenue row.",
    }
    values.update(overrides)
    return values


def assertions_by_metric(case: dict[str, object]) -> dict[str, dict[str, object]]:
    assertions = case["assert"]
    assert isinstance(assertions, list)
    return {assertion["metric"]: assertion for assertion in assertions}


def test_declares_the_csv_schema_and_supported_topics() -> None:
    assert tuple(REQUIRED_FIELDS) == EXPECTED_FIELDS
    assert set(SUPPORTED_TOPICS) == EXPECTED_TOPICS


def test_generates_exactly_one_case_per_csv_row_and_preserves_all_fields(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.csv"
    rows = [
        row(),
        row(
            id="OOD01",
            test="What will the weather be tomorrow?",
            topic="out_of_distribution",
            answer="That request is outside the financial-report scope.",
            source="Active corpus manifest",
            annotations="Do not retrieve or cite a report.",
        ),
    ]
    write_dataset(dataset, rows)

    cases = generate_tests({"dataset_path": str(dataset)})

    assert len(cases) == len(rows)
    for case, source_row in zip(cases, rows, strict=True):
        assert case["vars"] == source_row
        assert source_row["id"] in case["description"]
        assert case["metadata"] == {"id": source_row["id"], "topic": source_row["topic"]}


def test_real_dataset_generates_all_114_rows_in_csv_order() -> None:
    cases = generate_tests()

    assert len(cases) == 114
    assert [case["vars"]["id"] for case in cases[:3]] == ["ACC01", "ACC02", "ACC03"]
    assert {case["vars"]["topic"] for case in cases} == EXPECTED_TOPICS


def test_each_case_has_three_distinct_named_evaluation_dimensions(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.csv"
    write_dataset(dataset, [row()])

    case = generate_tests({"dataset_path": str(dataset)})[0]
    assertions = assertions_by_metric(case)

    assert set(assertions) == {"response_validity", "workflow_behavior", "answer_quality"}
    assert assertions["response_validity"] == {
        "type": "python",
        "value": "file://assertions.py:assert_non_empty_output",
        "metric": "response_validity",
    }
    assert assertions["workflow_behavior"] == {
        "type": "python",
        "value": "file://assertions.py:assert_trajectory",
        "metric": "workflow_behavior",
    }

    rubric = assertions["answer_quality"]
    assert rubric["type"] == "llm-rubric"
    assert rubric["metric"] == "answer_quality"
    rubric_text = rubric["value"]
    assert isinstance(rubric_text, str)
    assert "actual assistant output" in rubric_text.lower()
    assert "{{answer}}" in rubric_text
    assert "{{source}}" in rubric_text
    assert "{{annotations}}" in rubric_text


def test_missing_dataset_fails_with_the_resolved_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"

    with pytest.raises(FileNotFoundError, match=r"missing\.csv"):
        generate_tests({"dataset_path": str(missing)})


@pytest.mark.parametrize("missing_header", EXPECTED_FIELDS)
def test_missing_required_header_fails_clearly(tmp_path: Path, missing_header: str) -> None:
    dataset = tmp_path / "cases.csv"
    headers = tuple(field for field in EXPECTED_FIELDS if field != missing_header)
    write_dataset(dataset, [{field: value for field, value in row().items() if field in headers}], headers)

    with pytest.raises(ValueError, match=rf"required header.*{missing_header}"):
        generate_tests({"dataset_path": str(dataset)})


@pytest.mark.parametrize("blank_field", EXPECTED_FIELDS)
@pytest.mark.parametrize("blank_value", ["", "  \t"])
def test_blank_required_field_identifies_row_and_field(
    tmp_path: Path,
    blank_field: str,
    blank_value: str,
) -> None:
    dataset = tmp_path / "cases.csv"
    write_dataset(dataset, [row(**{blank_field: blank_value})])

    with pytest.raises(ValueError, match=rf"row 2.*{blank_field}.*blank"):
        generate_tests({"dataset_path": str(dataset)})


def test_duplicate_ids_are_rejected_with_the_duplicate_value(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.csv"
    write_dataset(dataset, [row(), row(test="A second question with the same id")])

    with pytest.raises(ValueError, match=r"duplicate.*ACC01"):
        generate_tests({"dataset_path": str(dataset)})


def test_unsupported_topic_is_rejected_with_id_and_topic(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.csv"
    write_dataset(dataset, [row(topic="unsupported_topic")])

    with pytest.raises(ValueError, match=r"ACC01.*unsupported_topic"):
        generate_tests({"dataset_path": str(dataset)})
