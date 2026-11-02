"""Load the reviewed CSV dataset into Promptfoo test cases."""

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = ("id", "test", "topic", "answer", "source", "annotations")
SUPPORTED_TOPICS = frozenset(
    {
        "ambiguous_questions",
        "conditional_reasoning",
        "deterministic_accuracy",
        "extra_calculation",
        "image_questions",
        "in_domain_no_data",
        "multiple_companies",
        "out_of_distribution",
        "table_questions",
        "tool_usage",
    }
)
DEFAULT_DATASET_PATH = Path(__file__).with_name("evals_tests.csv")

_ANSWER_RUBRIC = """Evaluate the actual assistant output against this reviewed financial-report test case.

Expected answer or behavior:
{{answer}}

Expected supporting source or corpus boundary:
{{source}}

Reviewer annotations:
{{annotations}}

Pass only when the output is factually consistent with the expected answer, follows the requested scope or refusal
behavior, preserves material units and periods, and does not invent evidence. Equivalent wording and mathematically
equivalent values are acceptable. A source citation need not use identical prose, but grounded answers must identify
the expected report or an unambiguously equivalent citation. Return a score from 0 to 1 and pass only at 0.8 or above.
"""


def generate_tests(config: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Validate the reviewed CSV before translating rows into Promptfoo cases."""

    dataset_path = _dataset_path(config)
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Evaluation dataset does not exist: {dataset_path}")

    with dataset_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        _validate_headers(reader.fieldnames, dataset_path)
        rows = [_validate_row(row, row_number, dataset_path) for row_number, row in enumerate(reader, start=2)]

    _validate_unique_ids(rows, dataset_path)
    return [_to_test_case(row) for row in rows]


def _dataset_path(config: Mapping[str, Any] | None) -> Path:
    if config is None:
        return DEFAULT_DATASET_PATH
    configured = config.get("dataset_path", DEFAULT_DATASET_PATH)
    if not isinstance(configured, (str, Path)):
        raise TypeError("dataset_path must be a string or Path")
    return Path(configured).expanduser().resolve()


def _validate_headers(fieldnames: Sequence[str] | None, dataset_path: Path) -> None:
    present = set(fieldnames or ())
    missing = [field for field in REQUIRED_FIELDS if field not in present]
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Evaluation dataset {dataset_path} is missing required header(s): {names}")


def _validate_row(row: dict[str, str | None], row_number: int, dataset_path: Path) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for field in REQUIRED_FIELDS:
        value = row.get(field)
        if value is None or not value.strip():
            raise ValueError(f"Evaluation dataset {dataset_path} row {row_number} field {field!r} is blank")
        cleaned[field] = value.strip()

    if cleaned["topic"] not in SUPPORTED_TOPICS:
        raise ValueError(
            f"Evaluation case {cleaned['id']} has unsupported topic {cleaned['topic']!r} in {dataset_path}"
        )
    return cleaned


def _validate_unique_ids(rows: list[dict[str, str]], dataset_path: Path) -> None:
    seen: set[str] = set()
    for row in rows:
        case_id = row["id"]
        if case_id in seen:
            raise ValueError(f"Evaluation dataset {dataset_path} contains duplicate id {case_id!r}")
        seen.add(case_id)


def _to_test_case(row: dict[str, str]) -> dict[str, Any]:
    return {
        "description": f"{row['id']}: {row['test']}",
        "vars": dict(row),
        "metadata": {"id": row["id"], "topic": row["topic"]},
        "assert": [
            {
                "type": "python",
                "value": "file://assertions.py:assert_non_empty_output",
                "metric": "response_validity",
            },
            {
                "type": "python",
                "value": "file://assertions.py:assert_trajectory",
                "metric": "workflow_behavior",
            },
            {
                "type": "llm-rubric",
                "value": _ANSWER_RUBRIC,
                "threshold": 0.8,
                "metric": "answer_quality",
            },
        ],
    }
