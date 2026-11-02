"""Behavioral contracts for project-wide utility functions."""

import ast
import csv
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from utils import (
    canonical_json_bytes,
    financial_report_sort_key,
    format_bullets,
    format_evidence,
    normalize_optional_string,
    read_json,
    require_nonblank_string,
    sha256_bytes,
    sha256_file,
    sha256_json,
    sha256_text,
    write_csv,
    write_json,
)
from utils.utils import canonical_json_bytes as canonical_json_bytes_from_module

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_public_package_reexports_utility_implementation() -> None:
    assert canonical_json_bytes is canonical_json_bytes_from_module


def test_canonical_json_bytes_are_compact_sorted_and_utf8() -> None:
    assert canonical_json_bytes({"unicode": "café", "answer": 42}) == (b'{"answer":42,"unicode":"caf\xc3\xa9"}')


def test_canonical_json_bytes_reject_non_json_numbers() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"amount": float("nan")})


def test_sha256_helpers_cover_bytes_text_json_and_files(tmp_path: Path) -> None:
    payload = "financial report £"
    encoded = payload.encode("utf-8")
    path = tmp_path / "nested" / "report.txt"
    path.parent.mkdir()
    path.write_bytes(encoded)

    expected = hashlib.sha256(encoded).hexdigest()
    assert sha256_bytes(encoded) == expected
    assert sha256_text(payload) == expected
    assert sha256_file(path) == expected
    assert sha256_json({"b": 2, "a": 1}) == hashlib.sha256(b'{"a":1,"b":2}').hexdigest()


def test_read_json_decodes_utf8(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text('{"company": "Société Générale"}', encoding="utf-8")

    assert read_json(path) == {"company": "Société Générale"}


@pytest.mark.parametrize(
    ("indent", "expected"),
    [
        (2, '{\n  "company": "Apple",\n  "year": 2025\n}\n'),
        (None, '{"company":"Apple","year":2025}\n'),
    ],
)
def test_write_json_creates_parents_and_supports_pretty_or_compact_output(
    tmp_path: Path,
    indent: int | None,
    expected: str,
) -> None:
    path = tmp_path / "nested" / "result.json"

    write_json(path, {"company": "Apple", "year": 2025}, indent=indent)

    assert path.read_text(encoding="utf-8") == expected


@pytest.mark.parametrize("invalid", [float("nan"), {"not": {"json", "serializable"}}])
def test_write_json_failure_preserves_destination_and_cleans_temporary_file(
    tmp_path: Path,
    invalid: object,
) -> None:
    path = tmp_path / "result.json"
    path.write_text('{"status":"existing"}\n', encoding="utf-8")

    with pytest.raises((TypeError, ValueError)):
        write_json(path, invalid)

    assert path.read_text(encoding="utf-8") == '{"status":"existing"}\n'
    assert list(tmp_path.iterdir()) == [path]


def test_write_csv_creates_parents_and_supports_field_options(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "manifest.csv"
    rows = [
        {"company": "Apple", "title": "Annual, report", "ignored": "not emitted"},
        {"company": "Meta", "title": "10-K", "ignored": "not emitted"},
    ]

    write_csv(
        path,
        rows,
        fieldnames=("company", "title"),
        quoting=csv.QUOTE_ALL,
        extrasaction="ignore",
    )

    assert path.read_text(encoding="utf-8") == ('"company","title"\n"Apple","Annual, report"\n"Meta","10-K"\n')


def test_write_csv_failure_preserves_destination_and_cleans_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    path.write_text("existing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fields not in fieldnames"):
        write_csv(
            path,
            [{"company": "Apple", "unexpected": "value"}],
            fieldnames=("company",),
            extrasaction="raise",
        )

    assert path.read_text(encoding="utf-8") == "existing\n"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (SecretStr("  secret  "), "secret"),
        (SecretStr("  "), None),
        ("  text  ", "text"),
        ("\t", None),
        (None, None),
        (17, 17),
    ],
)
def test_normalize_optional_string_unwraps_secrets_and_preserves_other_types(
    value: object,
    expected: object,
) -> None:
    assert normalize_optional_string(value) == expected


def test_normalize_optional_string_preserves_unrelated_object_identity() -> None:
    value = object()

    assert normalize_optional_string(value) is value


def test_require_nonblank_string_returns_trimmed_text() -> None:
    assert require_nonblank_string("  Apple FY2025  ", field_name="query") == "Apple FY2025"


@pytest.mark.parametrize("value", [None, 1, True, b"query"])
def test_require_nonblank_string_rejects_non_strings_with_field_name(value: object) -> None:
    with pytest.raises(TypeError, match=r"^query must be a string$"):
        require_nonblank_string(value, field_name="query")


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_require_nonblank_string_rejects_blank_strings_with_field_name(value: str) -> None:
    with pytest.raises(ValueError, match=r"^query must not be blank$"):
        require_nonblank_string(value, field_name="query")


def test_financial_report_sort_key_accepts_mappings_and_objects() -> None:
    mapping = {
        "company": "apple",
        "fiscal_year": "2025",
        "quarter": "Q2",
        "path": "apple/2025/Q2/report.pdf",
    }
    report = SimpleNamespace(
        company="apple",
        fiscal_year=2025,
        quarter="2",
        path="apple/2025/Q2/report.pdf",
    )

    assert financial_report_sort_key(mapping) == financial_report_sort_key(report)


def test_financial_report_sort_key_places_annual_or_blank_period_after_q4() -> None:
    reports = [
        {"company": "apple", "fiscal_year": "2025", "quarter": "", "path": "annual-b.pdf"},
        {"company": "apple", "fiscal_year": "2025", "quarter": "Q4", "path": "q4.pdf"},
        {"company": "apple", "fiscal_year": "2024", "quarter": "annual", "path": "annual-a.pdf"},
        {"company": "apple", "fiscal_year": "2025", "quarter": "1", "path": "q1.pdf"},
        {"company": "apple", "fiscal_year": "2025", "quarter": "FY", "path": "annual-a.pdf"},
    ]

    ordered = sorted(reports, key=financial_report_sort_key)

    assert [report["path"] for report in ordered] == [
        "annual-a.pdf",
        "q1.pdf",
        "q4.pdf",
        "annual-a.pdf",
        "annual-b.pdf",
    ]


def test_format_bullets_renders_items_and_empty_fallback() -> None:
    assert format_bullets(("Revenue", "Fiscal year")) == "- Revenue\n- Fiscal year"
    assert format_bullets(()) == "- No explicit fact list supplied"
    assert format_bullets((), empty="- Nothing required") == "- Nothing required"


def test_format_evidence_uses_source_labels_and_sorted_metadata() -> None:
    chunks = [
        SimpleNamespace(
            source="Apple FY2025 10-K p. 29",
            text="Net sales were $416.161 billion.",
            metadata={"page": 29, "company": "Apple"},
        ),
        SimpleNamespace(source="Apple FY2024 10-K", text="Prior-year comparison.", metadata={}),
    ]

    assert format_evidence(chunks) == (
        "Source: Apple FY2025 10-K p. 29 (company=Apple, page=29)\n"
        "Net sales were $416.161 billion.\n\n"
        "Source: Apple FY2024 10-K\n"
        "Prior-year comparison."
    )


def test_format_evidence_uses_empty_fallback() -> None:
    assert format_evidence(()) == "No evidence was retrieved."
    assert format_evidence((), empty="No context.") == "No context."


def _defined_functions(relative_path: str) -> set[str]:
    tree = ast.parse((REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _imports_shared_utils(relative_path: str) -> bool:
    tree = ast.parse((REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"utils", "utils.utils"}:
            return True
        if isinstance(node, ast.Import) and any(alias.name in {"utils", "utils.utils"} for alias in node.names):
            return True
    return False


@pytest.mark.parametrize(
    "relative_path",
    [
        "agents/baseline/baseline_agent.py",
        "etl/pipeline.py",
        "etl/runner.py",
        "evals/provider.py",
        "scripts/build_active_manifest.py",
    ],
)
def test_representative_project_sections_import_shared_utils(relative_path: str) -> None:
    assert _imports_shared_utils(relative_path), f"{relative_path} must reuse project-wide utilities"


def test_representative_callers_do_not_redefine_shared_utilities() -> None:
    assert {"_format_facts", "_format_context"}.isdisjoint(_defined_functions("agents/baseline/baseline_agent.py"))
    assert {"digest", "file_hash", "write_json", "read_json"}.isdisjoint(_defined_functions("etl/pipeline.py"))
    assert {"_write_json", "_chronological_key"}.isdisjoint(_defined_functions("etl/runner.py"))
    assert {"write_csv"}.isdisjoint(_defined_functions("scripts/audit_reports.py"))
    assert {"chronological_key"}.isdisjoint(_defined_functions("scripts/build_active_manifest.py"))
