"""Opt-in PostgreSQL/pgvector contract tests; never touch non-test documents."""

import os
import uuid
from dataclasses import replace

import pytest

psycopg = pytest.importorskip("psycopg")

from etl.models import Chunk, SourceDocument
from etl.store import initialize, is_current, replace_document, search

pytestmark = pytest.mark.skipif(
    not os.environ.get("ETL_TEST_DATABASE_URL"),
    reason="Set ETL_TEST_DATABASE_URL to a disposable PostgreSQL database with pgvector",
)


def vector(axis=0):
    result = [0.0] * 1536
    result[axis] = 1.0
    return result


@pytest.fixture
def database():
    prefix = "etl-test-" + uuid.uuid4().hex
    schema = "company_store_" + uuid.uuid4().hex
    owned_ids = []
    with psycopg.connect(os.environ["ETL_TEST_DATABASE_URL"], autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
        conn.execute(psycopg.sql.SQL("SET search_path TO {}, public").format(psycopg.sql.Identifier(schema)))
        initialize(conn)

        def make_source(suffix="primary", year=2025):
            document_id = f"{prefix}-{suffix}"
            owned_ids.append(document_id)
            return SourceDocument(document_id=document_id, path=f"{document_id}.pdf", sha256="a" * 64, company="Apple", fiscal_year=year, quarter="4", report_type="annual_report", title="Annual financial results", url="https://example.com/annual.pdf", pages=10)

        try:
            yield conn, make_source
        finally:
            conn.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


def chunks_for(source, count=2):
    return [Chunk(chunk_id=f"{source.document_id}-chunk-{index}", document_id=source.document_id, ordinal=index, text=f"Revenue increased in business {index}.", headings=("Annual report", "Results"), pages=(index + 2,), source_refs=(f"#/texts/{index}",), kind="text") for index in range(count)]


def publish(conn, source, chunks, generation="generation-1"):
    replace_document(conn, source, chunks, [chunk.text for chunk in chunks], [vector() for _ in chunks], generation)


def test_replacement_is_idempotent_and_tracks_expected_count(database):
    conn, make_source = database
    source = make_source()
    chunks = chunks_for(source)
    assert not is_current(conn, source.document_id, "generation-1", 2)
    publish(conn, source, chunks)
    publish(conn, source, chunks)
    assert is_current(conn, source.document_id, "generation-1", 2)
    assert not is_current(conn, source.document_id, "other-generation", 2)
    assert not is_current(conn, source.document_id, "generation-1", 3)
    assert conn.execute("SELECT count(*) FROM etl_chunks_apple WHERE document_id = %s", (source.document_id,)).fetchone()[0] == 2


def test_replacement_removes_stale_chunks(database):
    conn, make_source = database
    source = make_source()
    original = chunks_for(source, 3)
    publish(conn, source, original)
    replacement = [replace(original[0], text="New revenue disclosure")]
    publish(conn, source, replacement, generation="generation-2")
    assert is_current(conn, source.document_id, "generation-2", 1)
    rows = conn.execute("SELECT chunk_id, body FROM etl_chunks_apple WHERE document_id = %s", (source.document_id,)).fetchall()
    assert rows == [(replacement[0].chunk_id, "New revenue disclosure")]


def test_insert_failure_rolls_back_previous_generation(database):
    conn, make_source = database
    source = make_source()
    other_source = make_source("other")
    original = chunks_for(source, 1)
    other_chunks = chunks_for(other_source, 1)
    publish(conn, source, original)
    publish(conn, other_source, other_chunks)
    colliding_chunk = replace(original[0], chunk_id=other_chunks[0].chunk_id, text="Must roll back")
    with pytest.raises(psycopg.Error):
        publish(conn, source, [colliding_chunk], generation="broken-generation")
    assert is_current(conn, source.document_id, "generation-1", 1)
    assert is_current(conn, other_source.document_id, "generation-1", 1)
    assert conn.execute("SELECT body FROM etl_chunks_apple WHERE document_id = %s", (source.document_id,)).fetchone()[0] == original[0].text


@pytest.mark.parametrize("problem", ["vector-count", "text-count", "dimension", "zero", "nan"])
def test_invalid_payload_does_not_delete_previous_generation(database, problem):
    conn, make_source = database
    source = make_source()
    chunks = chunks_for(source, 1)
    publish(conn, source, chunks)
    texts, vectors = [chunks[0].text], [vector()]
    if problem == "vector-count":
        vectors = []
    elif problem == "text-count":
        texts = []
    elif problem == "dimension":
        vectors = [[1.0, 2.0]]
    elif problem == "zero":
        vectors = [[0.0] * 1536]
    elif problem == "nan":
        vectors[0][0] = float("nan")
    with pytest.raises(ValueError):
        replace_document(conn, source, chunks, texts, vectors, "broken-generation")
    assert is_current(conn, source.document_id, "generation-1", 1)


def test_filtered_search_returns_citation_metadata(database):
    conn, make_source = database
    source = make_source()
    old_source = make_source("older", year=2024)
    chunk = chunks_for(source, 1)[0]
    publish(conn, source, [chunk])
    publish(conn, old_source, chunks_for(old_source, 1))
    hits = search(conn, vector(), limit=5, company=source.company, fiscal_year=2025)
    assert len(hits) == 1
    hit = hits[0]
    assert hit["document_id"] == source.document_id
    assert hit["chunk_id"] == chunk.chunk_id
    assert hit["company"] == source.company
    assert hit["fiscal_year"] == 2025
    assert hit["quarter"] == "4"
    assert hit["report_type"] == "annual_report"
    assert hit["title"] == source.title
    assert hit["url"] == source.url
    assert hit["source_path"] == source.path
    assert tuple(hit["pages"]) == chunk.pages
    assert tuple(hit["headings"]) == chunk.headings
    assert tuple(hit["source_refs"]) == chunk.source_refs
    assert hit["kind"] == "text"
    assert hit["text"] == chunk.text
    assert hit["score"] == pytest.approx(1.0)


def test_source_metadata_is_updated_on_replacement(database):
    conn, make_source = database
    source = make_source()
    chunks = chunks_for(source, 1)
    publish(conn, source, chunks)
    updated = replace(source, company="Amazon", title="Corrected annual report")
    publish(conn, updated, chunks, generation="updated-metadata")
    assert search(conn, vector(), company=source.company) == []
    hit = search(conn, vector(), company=updated.company)[0]
    assert hit["title"] == updated.title


def test_runner_commits_each_document_visible_to_other_connections(database, monkeypatch, tmp_path):
    """Use runner's actual connection setup, not the fixture's autocommit mode."""
    from etl import runner

    observer, make_source = database
    # This test owns only synthetic rows; full-corpus reconciliation is covered
    # separately with TEMP tables and must never prune the shared test database.
    monkeypatch.setattr(runner, "reconcile_documents", lambda *args: 0, raising=False)
    source = make_source("runner-visibility")
    chunks = chunks_for(source, 1)
    monkeypatch.setattr(runner, "load_manifest", lambda _: [source])
    monkeypatch.setattr(runner, "build_converter", lambda **_: object())
    monkeypatch.setattr(runner, "parser_config", lambda **_: {})
    monkeypatch.setattr(runner, "prepare_document", lambda *args: (tmp_path / "artifact", False))
    monkeypatch.setattr(runner, "read_chunks", lambda _: chunks)
    monkeypatch.setattr(runner, "cached_embeddings", lambda *args: [vector()])
    monkeypatch.setattr(runner, "cached_usage", lambda *args: {"prompt_tokens": 0, "total_tokens": 0, "api_calls": 0, "cost_usd": 0.0})

    def publish_and_check_visibility(conn, source, chunks, texts, vectors, generation):
        replace_document(conn, source, chunks, texts, vectors, generation)
        assert is_current(observer, source.document_id, generation, len(chunks)), (
            "replace_document returned successfully but Gold is invisible to a second connection; "
            "the runner must not leave per-document writes in an uncommitted outer transaction"
        )

    monkeypatch.setattr(runner, "replace_document", publish_and_check_visibility)
    result = runner.run(
        raw_dir=tmp_path / "raw", silver_dir=tmp_path / "silver",
        cache_dir=tmp_path / "cache", report_path=tmp_path / "report.json",
        database_url=psycopg.conninfo.make_conninfo(
            os.environ["ETL_TEST_DATABASE_URL"],
            options="-csearch_path=" + observer.execute("SELECT current_schema()").fetchone()[0] + ",public",
        ), openai_client=None,
        pictures=False, fail_fast=True,
    )
    assert result["status"] == "complete"
    assert observer.execute("SELECT count(*) FROM etl_chunks_apple WHERE document_id = %s", (source.document_id,)).fetchone()[0] == 1
