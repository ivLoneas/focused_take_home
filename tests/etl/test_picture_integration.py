"""Picture API configuration, Silver artifacts, run accounting and CLI policy."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling_core.types.doc.document import DocItemLabel
from pydantic import SecretStr

from etl import __main__ as cli
from etl import parsing, pipeline, runner
from etl.models import SourceDocument

PICTURE_USAGE = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
                 "api_calls": 1, "cost_usd": 0.0002}


@pytest.mark.parametrize("enabled", [True, False])
def test_docling_never_runs_local_picture_description(monkeypatch, enabled):
    import docling.document_converter

    factory = Mock()
    monkeypatch.setattr(docling.document_converter, "DocumentConverter", factory)
    parsing.build_converter(pictures=enabled)
    options = factory.call_args.kwargs["format_options"][InputFormat.PDF].pipeline_options
    assert options.do_picture_description is False
    assert options.generate_picture_images is enabled


def test_parser_config_identifies_openai_picture_model_and_prompt():
    config = parsing.parser_config(pictures=True)
    assert config["picture_model"] == "gpt-6-luna"
    assert config["picture_prompt"] == parsing.IMAGE_PROMPT
    assert config["picture_detail"] == "high"


@pytest.fixture
def picture_preparation(tmp_path, picture_document, picture_client):
    raw = tmp_path / "raw"
    raw.mkdir()
    contents = b"%PDF-1.7\nTest picture report\n%%EOF"
    (raw / "report.pdf").write_bytes(contents)
    source = SourceDocument(document_id="picture-doc", path="report.pdf", sha256=hashlib.sha256(contents).hexdigest(),
                            company="apple", fiscal_year=2025, quarter="4", report_type="annual_report",
                            title="Report", url="https://example.com/report", pages=1)
    picture_document.add_text(DocItemLabel.TEXT, "Source financial narrative.")
    converter = SimpleNamespace(convert=Mock(return_value=SimpleNamespace(
        status=ConversionStatus.SUCCESS, document=picture_document, errors=[])))
    return {"source": source, "raw_dir": raw, "silver_dir": tmp_path / "silver", "converter": converter,
            "parse_config": {"pictures": True, "picture_model": "gpt-6-luna",
                             "picture_prompt": parsing.IMAGE_PROMPT, "picture_detail": "high"},
            "picture_client": picture_client, "picture_cache_dir": tmp_path / "picture-cache"}


def test_silver_persists_description_usage_and_provenance_and_reuses_cache(picture_preparation):
    path, reused = pipeline.prepare_document(**picture_preparation)
    assert reused is False
    metadata = json.loads((path / "metadata.json").read_text())
    assert metadata["picture_usage"] == PICTURE_USAGE
    assert metadata["parse_config"]["picture_model"] == "gpt-6-luna"
    document = json.loads((path / "document.json").read_text())
    assert document["pictures"][0]["meta"]["description"]["text"] == "Revenue increased from $10m to $12m."
    chunks = pipeline.read_chunks(path / "chunks.json")
    picture = next(chunk for chunk in chunks if chunk.kind == "picture")
    assert picture.pages == (1,) and picture.source_refs == ("#/pictures/0",)
    assert "Revenue increased" in picture.text
    picture_preparation["picture_client"].responses.create.reset_mock()
    assert pipeline.prepare_document(**picture_preparation) == (path, True)
    picture_preparation["picture_client"].responses.create.assert_not_called()
    assert json.loads((path / "metadata.json").read_text())["picture_usage"] == PICTURE_USAGE


def test_rechunking_preserves_picture_usage_without_another_api_call(picture_preparation):
    pipeline.prepare_document(**picture_preparation)
    path, reused = pipeline.prepare_document(**picture_preparation, max_chars=300, overlap=50)
    assert reused is False
    assert json.loads((path / "metadata.json").read_text())["picture_usage"] == PICTURE_USAGE
    picture_preparation["picture_client"].responses.create.assert_called_once()


def test_disabled_picture_enrichment_makes_no_api_call(picture_preparation):
    picture_preparation["parse_config"]["pictures"] = False
    path, _ = pipeline.prepare_document(**picture_preparation)
    picture_preparation["picture_client"].responses.create.assert_not_called()
    metadata = json.loads((path / "metadata.json").read_text())
    assert metadata["picture_usage"]["api_calls"] == 0
    assert metadata["picture_usage"]["cost_usd"] == 0
    assert "Generated image description" not in (path / "blocks.json").read_text()


@pytest.mark.parametrize("parse_only,expected_cost", [(False, 0.0005), (True, 0.0002)])
def test_runner_reports_picture_usage_and_combined_cost(monkeypatch, tmp_path, picture_client, parse_only, expected_cost):
    source = SourceDocument(document_id="doc", path="report.pdf", sha256="a" * 64, company="apple",
                            fiscal_year=2025, quarter="4", report_type="annual_report", title="Report",
                            url="https://example.com/report", pages=1)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "metadata.json").write_text(json.dumps({"picture_usage": PICTURE_USAGE}))
    monkeypatch.setattr(runner, "load_manifest", lambda *args, **kwargs: [source])
    monkeypatch.setattr(runner, "build_converter", lambda **kwargs: object())
    monkeypatch.setattr(runner, "parser_config", lambda **kwargs: {"pictures": True})
    prepare = Mock(return_value=(artifact, False))
    monkeypatch.setattr(runner, "prepare_document", prepare)
    monkeypatch.setattr(runner, "read_chunks", lambda _: [])
    connect = Mock(return_value=Mock())
    monkeypatch.setattr(runner.psycopg, "connect", connect)
    monkeypatch.setattr(runner, "initialize", lambda *args: None)
    monkeypatch.setattr(runner, "is_current", lambda *args: False)
    monkeypatch.setattr(runner, "replace_document", lambda *args: None)
    monkeypatch.setattr(runner, "reconcile_documents", lambda *args: 0)
    monkeypatch.setattr(runner, "cached_embeddings", lambda *args: [])
    monkeypatch.setattr(runner, "cached_usage", lambda *args: {
        "prompt_tokens": 15000, "total_tokens": 15000, "api_calls": 1, "cost_usd": 0.0003})
    report = runner.run(tmp_path / "raw", tmp_path / "silver", tmp_path / "cache", tmp_path / "run.json",
                        "unused", picture_client, pictures=True, parse_only=parse_only, fail_fast=True)
    assert prepare.call_args.kwargs["picture_client"] is picture_client
    assert prepare.call_args.kwargs["picture_cache_dir"] is not None
    for counts in [report["totals"], report["documents"][0]]:
        assert counts["picture_input_tokens"] == 1000
        assert counts["picture_output_tokens"] == 200
        assert counts["picture_total_tokens"] == 1200
        assert counts["picture_api_calls"] == 1
        assert counts["picture_cost_usd"] == pytest.approx(0.0002)
        assert counts["cost_usd"] == pytest.approx(expected_cost)
    if parse_only:
        connect.assert_not_called()


@pytest.fixture
def offline_cli(monkeypatch):
    import openai

    settings = SimpleNamespace(database_url="unused", openai_api_key=None)
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    run = Mock(return_value={"totals": {"documents_failed": 0}})
    factory = Mock()
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(openai, "OpenAI", factory)
    return settings, run, factory


def test_parse_only_with_pictures_requires_api_key(offline_cli):
    _, run, factory = offline_cli
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        cli.main(["run", "--parse-only"])
    run.assert_not_called()
    factory.assert_not_called()


def test_parse_only_without_pictures_remains_offline(offline_cli):
    _, run, factory = offline_cli
    assert cli.main(["run", "--parse-only", "--no-pictures"]) == 0
    factory.assert_not_called()
    assert run.call_args.args[5] is None
    assert run.call_args.kwargs["pictures"] is False


def test_parse_only_with_key_forwards_openai_client_for_pictures(offline_cli):
    settings, run, factory = offline_cli
    settings.openai_api_key = SecretStr("test-picture-key")
    assert cli.main(["run", "--parse-only"]) == 0
    factory.assert_called_once_with(api_key="test-picture-key")
    assert run.call_args.args[5] is factory.return_value


def test_full_run_without_pictures_still_requires_embedding_api_key(offline_cli):
    _, run, factory = offline_cli
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        cli.main(["run", "--no-pictures"])
    run.assert_not_called()
    factory.assert_not_called()
