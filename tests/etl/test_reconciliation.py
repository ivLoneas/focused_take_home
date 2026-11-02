"""Reconcile Gold only after a complete successful active-corpus publication."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from etl import runner, store
from etl.models import SourceDocument


@pytest.mark.parametrize("document_ids", [[], (), "document-id", [""], ["  "], [None], [123]])
def test_reconciliation_rejects_empty_or_invalid_selection_before_sql(document_ids):
    connection = Mock()
    with pytest.raises(ValueError):
        store.reconcile_documents(connection, document_ids)
    connection.execute.assert_not_called()
    connection.transaction.assert_not_called()


@pytest.fixture
def run_case(monkeypatch, tmp_path):
    sources = [
        SourceDocument(
            document_id=f"doc-{index}",
            path=f"report-{index}.pdf",
            sha256="a" * 64,
            company="apple",
            fiscal_year=2025 + index,
            quarter="4",
            report_type="annual_report",
            title="Report",
            url="https://example.com",
            pages=1,
        )
        for index in range(2)
    ]
    events = []
    connection = Mock()
    connect = Mock(return_value=connection)
    monkeypatch.setattr(runner.psycopg, "connect", connect)
    monkeypatch.setattr(runner, "initialize", lambda _: None)
    monkeypatch.setattr(runner, "load_manifest", lambda *args, **kwargs: list(sources))
    monkeypatch.setattr(runner, "build_converter", lambda **kwargs: object())
    monkeypatch.setattr(runner, "parser_config", lambda **kwargs: {})
    monkeypatch.setattr(runner, "write_json", lambda *args: None)
    prepare = Mock(return_value=(tmp_path / "artifact", False))
    monkeypatch.setattr(runner, "prepare_document", prepare)
    monkeypatch.setattr(runner, "read_chunks", lambda _: [])
    monkeypatch.setattr(runner, "is_current", lambda *args: False)
    monkeypatch.setattr(runner, "cached_embeddings", lambda *args: [])
    monkeypatch.setattr(
        runner, "cached_usage", lambda *args: {"prompt_tokens": 0, "total_tokens": 0, "api_calls": 0, "cost_usd": 0.0}
    )
    monkeypatch.setattr(
        runner, "replace_document", lambda conn, source, *args: events.append(("publish", source.document_id))
    )

    def reconcile(conn, ids):
        assert conn is connection
        events.append(("reconcile", tuple(ids)))
        return 3

    prune = Mock(side_effect=reconcile)
    monkeypatch.setattr(store, "reconcile_documents", prune, raising=False)
    monkeypatch.setattr(runner, "reconcile_documents", prune, raising=False)

    def execute(**options):
        return runner.run(
            tmp_path / "raw",
            tmp_path / "silver",
            tmp_path / "cache",
            tmp_path / "report.json",
            "unused",
            None,
            pictures=False,
            **options,
        )

    return SimpleNamespace(
        sources=sources,
        events=events,
        connect=connect,
        connection=connection,
        prepare=prepare,
        prune=prune,
        execute=execute,
    )


@pytest.mark.parametrize(
    "options,expected_ids",
    [({}, ("doc-0", "doc-1")), ({"company": ["apple"], "per_company_limit": 1, "keep": "newest"}, ("doc-1",))],
)
def test_successful_run_prunes_to_final_selected_ids_after_all_publications(run_case, options, expected_ids):
    report = run_case.execute(**options)
    assert run_case.events == [("publish", item) for item in expected_ids] + [("reconcile", expected_ids)]
    assert report["totals"]["documents_pruned"] == 3
    assert report["status"] == "complete"


def test_failed_document_preserves_previous_corpus_without_pruning(run_case, tmp_path):
    run_case.prepare.side_effect = [(tmp_path / "artifact", False), RuntimeError("bad PDF")]
    report = run_case.execute()
    assert report["status"] == "complete_with_errors"
    assert report["totals"]["documents_failed"] == 1
    assert run_case.events == [("publish", "doc-0")]
    run_case.prune.assert_not_called()


def test_parse_only_never_connects_or_reconciles_gold(run_case):
    report = run_case.execute(parse_only=True)
    assert report["status"] == "complete"
    run_case.connect.assert_not_called()
    run_case.prune.assert_not_called()


def test_empty_selection_fails_before_any_database_access(run_case):
    run_case.sources.clear()
    with pytest.raises(ValueError):
        run_case.execute()
    run_case.connect.assert_not_called()
    run_case.prune.assert_not_called()


@pytest.fixture
def temporary_gold():
    """TEMP tables shadow production names, so tests cannot prune real Gold."""
    url = os.environ.get("ETL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ETL_TEST_DATABASE_URL is required for temporary-table PostgreSQL tests")
    import psycopg

    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("CREATE TEMP TABLE etl_documents (document_id text PRIMARY KEY)")
        connection.execute(
            "CREATE TEMP TABLE etl_chunks (chunk_id text PRIMARY KEY, document_id text REFERENCES etl_documents(document_id) ON DELETE CASCADE)"
        )
        connection.execute("INSERT INTO etl_documents VALUES ('keep'), ('stale')")
        connection.execute("INSERT INTO etl_chunks VALUES ('keep-chunk', 'keep'), ('stale-chunk', 'stale')")
        yield connection


def test_live_reconciliation_removes_stale_documents_and_cascades_chunks(temporary_gold):
    connection = temporary_gold
    assert store.reconcile_documents(connection, ["keep"]) == 1
    assert connection.execute("SELECT document_id FROM etl_documents").fetchall() == [("keep",)]
    assert connection.execute("SELECT chunk_id FROM etl_chunks").fetchall() == [("keep-chunk",)]
    assert store.reconcile_documents(connection, ["keep"]) == 0


def test_live_reconciliation_accepts_selected_documents_not_yet_in_gold(temporary_gold):
    connection = temporary_gold
    assert store.reconcile_documents(connection, ["keep", "new-document"]) == 1
    assert connection.execute("SELECT document_id FROM etl_documents").fetchall() == [("keep",)]
