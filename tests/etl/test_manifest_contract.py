"""CLI and runner must share the central active retrieval-manifest contract."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from etl import __main__ as cli
from etl import runner
from etl.models import SourceDocument


def test_cli_defaults_to_central_active_manifest():
    args = cli.parser().parse_args(["run", "--parse-only"])
    assert args.manifest == Path("data/active_manifest.csv")


@pytest.mark.parametrize(
    "arguments,expected",
    [([], Path("data/active_manifest.csv")), (["--manifest", "data/custom.csv"], Path("data/custom.csv"))],
)
def test_cli_forwards_default_or_explicit_manifest(monkeypatch, arguments, expected):
    run = Mock(return_value={"totals": {"documents_failed": 0}})
    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: SimpleNamespace(
            database_url="postgresql://test/database",
            openai_api_key=None,
        ),
    )
    assert cli.main(["run", "--parse-only", "--no-pictures", *arguments]) == 0
    assert run.call_args.kwargs["manifest_path"] == expected


def test_runner_loads_and_records_explicit_manifest(monkeypatch, tmp_path):
    manifest = tmp_path / "active_manifest.csv"
    raw = tmp_path / "raw"
    source = SourceDocument(
        document_id="doc",
        path="report.pdf",
        sha256="a" * 64,
        company="apple",
        fiscal_year=2025,
        quarter="4",
        report_type="annual_report",
        title="Report",
        url="https://example.com/report",
        pages=1,
    )
    load = Mock(return_value=[source])
    monkeypatch.setattr(runner, "load_manifest", load)
    monkeypatch.setattr(runner, "build_converter", lambda **_: object())
    monkeypatch.setattr(runner, "parser_config", lambda **_: {})
    monkeypatch.setattr(runner, "write_json", lambda *args: None)
    monkeypatch.setattr(runner, "prepare_document", lambda *args: (tmp_path / "artifact", True))
    monkeypatch.setattr(runner, "read_chunks", lambda _: [])
    report = runner.run(
        raw,
        tmp_path / "silver",
        tmp_path / "cache",
        tmp_path / "report.json",
        "unused",
        None,
        parse_only=True,
        pictures=False,
        manifest_path=manifest,
    )
    load.assert_called_once_with(raw, manifest_path=manifest)
    assert report["selection"]["manifest"] == str(manifest)
    assert report["selection"]["documents"] == 1
