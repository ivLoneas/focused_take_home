"""Source inventory validation must protect bronze data integrity."""

import csv
import hashlib
from dataclasses import replace

import pytest

from etl.manifest import load_manifest, verify_source


PDF = b"%PDF-1.7\nA synthetic test report\n%%EOF\n"
FIELDS = ["company", "fiscal_year", "quarter", "report_type", "title", "format", "path", "pages", "sha256", "url"]


def make_row(**overrides):
    row = dict(company="example", fiscal_year="2025", quarter="4", report_type="annual_report", title="Example FY2025 report", format="pdf", path="example/2025/report.pdf", pages="10", sha256=hashlib.sha256(PDF).hexdigest(), url="https://example.com/report.pdf")
    return row | overrides


def write_inventory(raw, rows, annual_rows=()):
    for name, records in [("manifest.csv", rows), ("annual_manifest.csv", annual_rows)]:
        with (raw / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(records)


def test_loads_primary_inventory_with_stable_document_ids(tmp_path):
    write_inventory(tmp_path, [make_row(), make_row(path="example/2024/annual.pdf", fiscal_year="2024")])
    sources = load_manifest(tmp_path)
    assert len(sources) == 2
    assert sources == load_manifest(tmp_path)
    assert len({source.document_id for source in sources}) == 2
    current = next(source for source in sources if source.fiscal_year == 2025)
    assert current.company == "example"
    assert current.pages == 10
    assert current.path == "example/2025/report.pdf"
    assert current.report_type == "annual_report"
    assert current.title == "Example FY2025 report"
    assert current.url == "https://example.com/report.pdf"


@pytest.mark.parametrize("path", ["../outside.pdf", "/tmp/outside.pdf", "example/../../outside.pdf", "report.txt"])
def test_rejects_unsafe_or_non_pdf_paths(tmp_path, path):
    write_inventory(tmp_path, [make_row(path=path)])
    with pytest.raises(ValueError):
        load_manifest(tmp_path)


def test_rejects_symlink_path_escaping_raw(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(PDF)
    (raw / "link.pdf").symlink_to(outside)
    write_inventory(raw, [make_row(path="link.pdf")])
    with pytest.raises(ValueError):
        load_manifest(raw)


@pytest.mark.parametrize("field,value", [("company", ""), ("path", ""), ("sha256", ""), ("sha256", "not-a-digest"), ("sha256", "g" * 64), ("fiscal_year", "twenty"), ("fiscal_year", "0"), ("quarter", "0"), ("quarter", "5"), ("quarter", "QX"), ("pages", "-2"), ("pages", "many"), ("report_type", ""), ("title", "")])
def test_rejects_invalid_required_metadata(tmp_path, field, value):
    write_inventory(tmp_path, [make_row(**{field: value})])
    with pytest.raises(ValueError):
        load_manifest(tmp_path)


def test_duplicate_paths_within_primary_inventory_fail(tmp_path):
    write_inventory(tmp_path, [make_row(), make_row()])
    with pytest.raises(ValueError):
        load_manifest(tmp_path)


def test_secondary_annual_inventory_is_not_loaded_twice(tmp_path):
    write_inventory(tmp_path, [make_row()], [make_row()])
    assert len(load_manifest(tmp_path)) == 1


def test_annual_report_can_have_empty_quarter(tmp_path):
    write_inventory(tmp_path, [make_row(quarter="")])
    assert load_manifest(tmp_path)[0].quarter == ""


def test_missing_required_column_fails(tmp_path):
    (tmp_path / "manifest.csv").write_text("company,path\nexample,report.pdf\n")
    with pytest.raises(ValueError):
        load_manifest(tmp_path)


def test_verifies_pdf_magic_and_hash(tmp_path):
    write_inventory(tmp_path, [make_row(path="report.pdf")])
    path = tmp_path / "report.pdf"
    path.write_bytes(PDF)
    source = load_manifest(tmp_path)[0]
    assert verify_source(tmp_path, source) == path
    path.write_bytes(PDF + b"changed")
    with pytest.raises(ValueError):
        verify_source(tmp_path, source)


def test_matching_hash_does_not_allow_non_pdf_content(tmp_path):
    contents = b"<html>not a report</html>"
    write_inventory(tmp_path, [make_row(path="report.pdf", sha256=hashlib.sha256(contents).hexdigest())])
    (tmp_path / "report.pdf").write_bytes(contents)
    with pytest.raises(ValueError):
        verify_source(tmp_path, load_manifest(tmp_path)[0])


def test_verify_rechecks_confinement_for_constructed_source(tmp_path):
    write_inventory(tmp_path, [make_row(path="report.pdf")])
    source = replace(load_manifest(tmp_path)[0], path="../outside.pdf")
    with pytest.raises(ValueError):
        verify_source(tmp_path, source)


def test_external_manifest_selects_only_its_rows_and_resolves_pdfs_under_raw(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    write_inventory(raw, [make_row(path="report.pdf"), make_row(path="excluded.pdf")])
    write_inventory(tmp_path, [make_row(path="report.pdf")])
    (raw / "report.pdf").write_bytes(PDF)
    sources = load_manifest(raw, manifest_path=tmp_path / "manifest.csv")
    assert [source.path for source in sources] == ["report.pdf"]
    assert verify_source(raw, sources[0]) == raw / "report.pdf"


@pytest.mark.parametrize("path", ["../outside.pdf", "/tmp/outside.pdf"])
def test_external_manifest_does_not_expand_source_path_permissions(tmp_path, path):
    raw = tmp_path / "raw"
    raw.mkdir()
    write_inventory(tmp_path, [make_row(path=path)])
    with pytest.raises(ValueError):
        load_manifest(raw, manifest_path=tmp_path / "manifest.csv")


def test_missing_explicit_manifest_does_not_fall_back_to_raw_inventory(tmp_path):
    write_inventory(tmp_path, [make_row()])
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path, manifest_path=tmp_path / "missing-active.csv")
