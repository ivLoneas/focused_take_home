"""Load the reviewed CSV dataset into Promptfoo test cases."""

import csv
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = ("id", "test", "topic", "answer", "source", "annotations")
OPTIONAL_FIELDS = ("required_tools", "required_period_companies", "allow_no_retrieval", "output_pattern")
SUPPORTED_TOPICS = frozenset(
    {
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
)
DEFAULT_DATASET_PATH = Path(__file__).with_name("evals_tests.csv")

_ANSWER_RUBRIC = """Evaluate the actual assistant output against this reviewed financial-report test case.

Original question and requested output:
{{test}}

Expected answer or behavior:
{{answer}}

Illustrative supporting sources or corpus boundary (non-exhaustive):
{{source}}

Reviewer annotations:
{{annotations}}

Grade factual correctness and requested behavior, not agreement with the reference citation's location.
The same fact may appear in multiple reports, tables, charts, or pages of the active corpus. Accept equivalent
in-corpus evidence from any such location; do not require the exact reference report, page, citation wording, or all
listed sources. A different page or report is not by itself a factual error. Reviewer annotations identify relevant
facts and interpretations, not an exhaustive checklist of source locations the output must reproduce. Honor an
explicit request for a particular quotation or source, but still accept equivalent locations within that source.

Preserve material units, fiscal periods, currency, signs, and GAAP versus non-GAAP distinctions. Interpret a bare
number in the units requested by the original question. Equivalent wording, unit conversions, and mathematically
equivalent values are acceptable. Reject incorrect figures, unsupported claims, fabricated evidence, or materially
incomplete answers. Do not excuse a wrong number merely because its citation looks plausible.

Do not require inline citations, explanations, formulas, or every comparison operand unless explicitly requested.
For a request to return only a number or company name, a correct bare value or winner is a complete answer; no
supporting figures or report citations need appear in the answer text. Output format compliance is assessed by a
separate deterministic check where configured: grade the financial content here, even if extra prose or citations
violate the output format. The separate check must still fail that formatting violation.

For a clarification or refusal, assess the requested scope behavior; do not demand financial figures or report
citations. A concise refusal that clearly states the financial-report boundary is sufficient for an unrelated
request, without restating its topic or naming a manifest file. For unavailable data, require a truthful specific
coverage explanation without invented facts. Return a score from 0 to 1 and pass only at 0.8 or above.
A company-level boundary such as 'I do not have reports for Uber in this collection' is a specific coverage
explanation. When the entire company is unavailable, do not also require every requested date, a manifest name,
tool names, or a narration of verification steps. A brief optional invitation to ask about something else is
acceptable. Offers to search externally or fetch unavailable reports are not acceptable.
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
    for field in OPTIONAL_FIELDS:
        if field in row:
            cleaned[field] = (row[field] or "").strip()
    if cleaned.get("allow_no_retrieval", "") not in {"", "true", "false"}:
        raise ValueError(f"Evaluation case {cleaned['id']} has invalid allow_no_retrieval")
    names = {name.strip() for name in cleaned.get("required_tools", "").split(",") if name.strip()}
    if names - {"listed_companies", "company_periods"}:
        raise ValueError(f"Evaluation case {cleaned['id']} has unsupported required_tools")
    pattern = cleaned.get("output_pattern", "")
    if cleaned["topic"] == "formatting_questions" and not pattern:
        raise ValueError(f"Evaluation case {cleaned['id']} requires output_pattern")
    if pattern:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"Evaluation case {cleaned['id']} has invalid output_pattern: {error}") from error
    return cleaned


def _validate_unique_ids(rows: list[dict[str, str]], dataset_path: Path) -> None:
    seen: set[str] = set()
    for row in rows:
        case_id = row["id"]
        if case_id in seen:
            raise ValueError(f"Evaluation dataset {dataset_path} contains duplicate id {case_id!r}")
        seen.add(case_id)


def _to_test_case(row: dict[str, str]) -> dict[str, Any]:
    case = {
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
    if row.get("output_pattern"):
        case["assert"].append(
            {
                "type": "python",
                "value": "file://assertions.py:assert_output_format",
                "metric": "format_compliance",
            }
        )
    return case
