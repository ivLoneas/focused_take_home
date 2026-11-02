"""Silver lifecycle tests use real document artifacts and mocked conversion."""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("docling_core")
pytest.importorskip("docling")

from docling.datamodel.base_models import ConversionStatus
from docling_core.types.doc import DoclingDocument, Size
from docling_core.types.doc.document import DocItemLabel

from etl.models import SourceDocument
from etl.pipeline import prepare_document


@pytest.fixture
def preparation(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    pdf = b"%PDF-1.7\nExample report\n%%EOF"
    (raw / "report.pdf").write_bytes(pdf)
    source = SourceDocument(document_id="test-doc", path="report.pdf", sha256=hashlib.sha256(pdf).hexdigest(), company="example", fiscal_year=2025, quarter="4", report_type="annual_report", title="Report", url="https://example.com/report.pdf", pages=1)
    doc = DoclingDocument(name="report")
    doc.add_page(page_no=1, size=Size(width=612, height=792))
    doc.add_title("Report")
    doc.add_heading("Results", level=1)
    doc.add_text(DocItemLabel.TEXT, "Revenue grew and margins improved. " * 40)
    result = SimpleNamespace(status=ConversionStatus.SUCCESS, document=doc, errors=[])
    converter = SimpleNamespace(convert=Mock(return_value=result))
    return dict(source=source, raw_dir=raw, silver_dir=tmp_path / "silver", converter=converter, parse_config={"parser": "docling", "images": "disabled"})


def test_preparation_writes_all_artifacts_and_reuses_complete_cache(preparation):
    path, reused = prepare_document(**preparation)
    assert reused is False
    assert path.is_dir()
    for filename in ["document.json", "document.md", "blocks.json", "chunks.json", "metadata.json"]:
        assert (path / filename).is_file()
        assert (path / filename).stat().st_size > 0
        if filename.endswith(".json"):
            json.loads((path / filename).read_text())
    assert "Revenue grew" in (path / "document.md").read_text()
    second_path, reused = prepare_document(**preparation)
    assert second_path == path
    assert reused is True
    assert preparation["converter"].convert.call_count == 1


def test_cached_source_is_verified_again_before_reuse(preparation):
    prepare_document(**preparation)
    (preparation["raw_dir"] / "report.pdf").write_bytes(b"%PDF-1.7 changed")
    with pytest.raises(ValueError):
        prepare_document(**preparation)
    assert preparation["converter"].convert.call_count == 1


def test_new_source_checksum_invalidates_cached_parsing(preparation):
    prepare_document(**preparation)
    contents = b"%PDF-1.7\nUpdated report\n%%EOF"
    (preparation["raw_dir"] / "report.pdf").write_bytes(contents)
    preparation["source"] = replace(preparation["source"], sha256=hashlib.sha256(contents).hexdigest())
    _, reused = prepare_document(**preparation)
    assert reused is False
    assert preparation["converter"].convert.call_count == 2


def test_parser_configuration_change_invalidates_parsing(preparation):
    prepare_document(**preparation)
    preparation["parse_config"] = {"parser": "docling", "images": "new-model"}
    _, reused = prepare_document(**preparation)
    assert reused is False
    assert preparation["converter"].convert.call_count == 2


def test_chunk_configuration_change_reuses_valid_parsing(preparation):
    path, _ = prepare_document(**preparation)
    previous_chunks = json.loads((path / "chunks.json").read_text())
    new_path, reused = prepare_document(**preparation, max_chars=300, overlap=50)
    assert reused is False
    chunks = json.loads((new_path / "chunks.json").read_text())
    assert chunks != previous_chunks
    assert all(len(chunk["text"]) <= 300 for chunk in chunks)
    assert preparation["converter"].convert.call_count == 1
    assert prepare_document(**preparation, max_chars=300, overlap=50)[1] is True


@pytest.mark.parametrize("filename", ["document.json", "document.md", "blocks.json", "chunks.json", "metadata.json"])
def test_missing_artifacts_trigger_rebuild(preparation, filename):
    path, _ = prepare_document(**preparation)
    (path / filename).unlink()
    new_path, reused = prepare_document(**preparation)
    assert reused is False
    assert (new_path / filename).stat().st_size > 0
    assert prepare_document(**preparation)[1] is True


@pytest.mark.parametrize("filename", ["document.json", "blocks.json", "chunks.json", "metadata.json"])
def test_truncated_json_triggers_rebuild(preparation, filename):
    path, _ = prepare_document(**preparation)
    (path / filename).write_text('{"truncated":')
    new_path, reused = prepare_document(**preparation)
    assert reused is False
    json.loads((new_path / filename).read_text())
    assert prepare_document(**preparation)[1] is True


def test_valid_json_tampering_is_detected_by_hash(preparation):
    path, _ = prepare_document(**preparation)
    blocks = json.loads((path / "blocks.json").read_text())
    blocks[0]["text"] = "Tampered unsupported fact."
    (path / "blocks.json").write_text(json.dumps(blocks))
    new_path, reused = prepare_document(**preparation)
    assert reused is False
    assert "Tampered unsupported fact" not in (new_path / "blocks.json").read_text()
    assert "Tampered unsupported fact" not in (new_path / "chunks.json").read_text()


@pytest.mark.parametrize("status", [ConversionStatus.FAILURE, ConversionStatus.PARTIAL_SUCCESS])
def test_failed_or_partial_conversion_does_not_publish_complete_metadata(preparation, status):
    preparation["converter"].convert.return_value.status = status
    with pytest.raises((ValueError, RuntimeError)):
        prepare_document(**preparation)
    assert not list(preparation["silver_dir"].rglob("metadata.json"))


def test_page_count_mismatch_is_rejected(preparation):
    preparation["source"] = replace(preparation["source"], pages=2)
    with pytest.raises((ValueError, RuntimeError)):
        prepare_document(**preparation)
    assert not list(preparation["silver_dir"].rglob("metadata.json"))


def test_cached_page_count_is_revalidated_against_inventory(preparation):
    prepare_document(**preparation)
    preparation["source"] = replace(preparation["source"], pages=2)
    with pytest.raises((ValueError, RuntimeError)):
        prepare_document(**preparation)


def test_empty_extraction_is_rejected(preparation):
    doc = DoclingDocument(name="empty")
    doc.add_page(page_no=1, size=Size(width=612, height=792))
    preparation["converter"].convert.return_value.document = doc
    with pytest.raises((ValueError, RuntimeError)):
        prepare_document(**preparation)
    assert not list(preparation["silver_dir"].rglob("metadata.json"))


def test_conversion_exception_can_be_retried_without_incomplete_cache(preparation):
    preparation["converter"].convert.side_effect = RuntimeError("conversion failed")
    with pytest.raises(RuntimeError, match="conversion failed"):
        prepare_document(**preparation)
    assert not list(preparation["silver_dir"].rglob("metadata.json"))
    preparation["converter"].convert.side_effect = None
    path, reused = prepare_document(**preparation)
    assert path.is_dir() and reused is False
