"""Opt-in isolated migration and physical company-vector separation checks."""

import os
import uuid

import pytest
from pgvector.psycopg import register_vector
from psycopg import Cursor, IntegrityError, connect, sql

from etl import store
from etl.models import Chunk, SourceDocument

pytestmark = pytest.mark.skipif(
    not os.environ.get("ETL_TEST_DATABASE_URL"),
    reason="Set ETL_TEST_DATABASE_URL to a disposable PostgreSQL/pgvector database",
)

COMPANIES = ("Alphabet", "Amazon", "Apple", "Meta", "Netflix")


def vector():
    return [1.0] + [0.0] * 1535


@pytest.fixture
def isolated_database():
    schema = "company_migration_" + uuid.uuid4().hex
    with connect(os.environ["ETL_TEST_DATABASE_URL"], autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        try:
            yield conn
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def source(company, suffix="2025"):
    return SourceDocument(
        document_id=company + suffix, path=company + suffix + ".pdf", sha256="a" * 64,
        company=company, fiscal_year=2025, quarter="4", report_type="annual_report",
        title="Annual financial results", url="https://example.test/report.pdf", pages=10,
    )


def publish(conn, company, suffix="2025"):
    report = source(company, suffix)
    chunk = Chunk(
        chunk_id=report.document_id + "-chunk", document_id=report.document_id, ordinal=0,
        text="Annual revenue", headings=("Financial statements",), pages=(3,),
        source_refs=("#/tables/1",), kind="table",
    )
    store.replace_document(conn, report, [chunk], ["Annual revenue"], [vector()], "generation")
    return report, chunk


def create_legacy_store(conn):
    conn.execute("""
        CREATE TABLE etl_documents (
            document_id text PRIMARY KEY, source_path text NOT NULL UNIQUE, source_sha256 text NOT NULL,
            company text NOT NULL, fiscal_year integer NOT NULL, quarter text NOT NULL,
            report_type text NOT NULL, title text NOT NULL, source_url text NOT NULL,
            page_count integer NOT NULL, generation text NOT NULL, embedding_model text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE etl_chunks (
            chunk_id text PRIMARY KEY, document_id text NOT NULL REFERENCES etl_documents(document_id) ON DELETE CASCADE,
            ordinal integer NOT NULL, body text NOT NULL, embedding_text text NOT NULL,
            headings text[] NOT NULL, pages integer[] NOT NULL, source_refs text[] NOT NULL,
            kind text NOT NULL, embedding vector(1536) NOT NULL,
            search_text tsvector GENERATED ALWAYS AS (to_tsvector('english', embedding_text)) STORED,
            UNIQUE(document_id, ordinal)
        );
    """)
    register_vector(conn)


def insert_legacy(conn, company):
    report = source(company)
    conn.execute("""
        INSERT INTO etl_documents
        (document_id,source_path,source_sha256,company,fiscal_year,quarter,report_type,title,
         source_url,page_count,generation,embedding_model)
        VALUES (%s,%s,%s,%s,2025,'4','annual_report','Annual financial results',
                'https://example.test/report.pdf',10,'generation','text-embedding-3-small')
    """, (report.document_id, report.path, report.sha256, company))
    conn.execute("""
        INSERT INTO etl_chunks
        (chunk_id,document_id,ordinal,body,embedding_text,headings,pages,source_refs,kind,embedding)
        VALUES (%s,%s,0,'Revenue','Company FY2025 Revenue',ARRAY['Results'],ARRAY[3,4],
                ARRAY['#/tables/1'],'table',%s::vector)
    """, (report.document_id + "-chunk", report.document_id, str(vector())))


def test_legacy_vectors_migrate_losslessly_and_initialization_is_idempotent(isolated_database):
    conn = isolated_database
    create_legacy_store(conn)
    for company in COMPANIES:
        insert_legacy(conn, company.lower())
    documents_before = conn.execute("SELECT * FROM etl_documents ORDER BY document_id").fetchall()
    chunks_before = conn.execute("""
        SELECT chunk_id,document_id,ordinal,body,embedding_text,headings,pages,source_refs,kind,embedding::text,search_text::text
        FROM etl_chunks ORDER BY document_id
    """).fetchall()

    store.initialize(conn)
    store.initialize(conn)

    assert conn.execute("SELECT * FROM etl_documents ORDER BY document_id").fetchall() == documents_before
    chunks_after = []
    for company in COMPANIES:
        table = sql.Identifier("etl_chunks_" + company.lower())
        assert conn.execute(sql.SQL("SELECT count(*) FROM {}").format(table)).fetchone()[0] == 1
        chunks_after.extend(conn.execute(sql.SQL("""
            SELECT chunk_id,document_id,ordinal,body,embedding_text,headings,pages,source_refs,kind,embedding::text,search_text::text
            FROM {}
        """).format(table)).fetchall())
        hits = store.search(conn, vector(), company=company)
        assert len(hits) == 1
        assert hits[0]["company"] == company.lower()
        assert hits[0]["pages"] == [3, 4]
    assert sorted(chunks_after) == sorted(chunks_before)
    legacy = conn.execute("SELECT relkind FROM pg_class WHERE oid=to_regclass(format('%I.etl_chunks', current_schema()))").fetchone()
    assert legacy is None or legacy[0] == "v"


def test_legacy_unknown_company_aborts_without_losing_any_rows(isolated_database):
    conn = isolated_database
    create_legacy_store(conn)
    insert_legacy(conn, "apple")
    insert_legacy(conn, "unsupported")
    before = conn.execute("SELECT chunk_id,embedding::text FROM etl_chunks ORDER BY chunk_id").fetchall()

    with pytest.raises(Exception, match="(?i)company|companies|unsupported"):
        store.initialize(conn)

    assert conn.execute("SELECT chunk_id,embedding::text FROM etl_chunks ORDER BY chunk_id").fetchall() == before
    assert conn.execute("SELECT count(*) FROM etl_documents").fetchone()[0] == 2
    assert conn.execute("SELECT to_regclass(format('%I.etl_chunks_apple', current_schema()))").fetchone()[0] is None


def test_physical_tables_isolate_identical_vectors_and_reconciliation_cascades(isolated_database):
    conn = isolated_database
    store.initialize(conn)
    selected = []
    for company in COMPANIES:
        report, chunk = publish(conn, company.lower())
        if company == "Apple":
            selected.append(report.document_id)
        hits = store.search(conn, vector(), company=company, limit=100)
        assert [hit["document_id"] for hit in hits] == [report.document_id]
        assert hits[0]["chunk_id"] == chunk.chunk_id

    assert store.reconcile_documents(conn, selected) == 4
    for company in COMPANIES:
        hits = store.search(conn, vector(), company=company)
        assert len(hits) == (1 if company == "Apple" else 0)


def test_company_table_cannot_contain_another_companys_document(isolated_database):
    conn = isolated_database
    store.initialize(conn)
    publish(conn, "apple")
    publish(conn, "amazon")
    with pytest.raises(IntegrityError):
        conn.execute("""
            INSERT INTO etl_chunks_apple
            (chunk_id,document_id,company,ordinal,body,embedding_text,headings,pages,source_refs,kind,embedding)
            SELECT 'wrong-table',document_id,company,1,body,embedding_text,headings,pages,source_refs,kind,embedding
            FROM etl_chunks_amazon
        """)
    with pytest.raises(IntegrityError):
        conn.execute("""
            INSERT INTO etl_chunks_apple
            (chunk_id,document_id,company,ordinal,body,embedding_text,headings,pages,source_refs,kind,embedding)
            SELECT 'wrong-document','amazon2025','apple',1,body,embedding_text,headings,pages,source_refs,kind,embedding
            FROM etl_chunks_apple
        """)
    assert conn.execute("SELECT count(*) FROM etl_chunks_apple").fetchone()[0] == 1


def test_unsupported_etl_company_rejected_without_changing_gold(isolated_database):
    conn = isolated_database
    store.initialize(conn)
    publish(conn, "apple")
    with pytest.raises((ValueError, TypeError), match="(?i)company"):
        publish(conn, "unsupported")
    assert conn.execute("SELECT count(*) FROM etl_documents").fetchone()[0] == 1


def test_live_search_reads_only_selected_company_vector_table(isolated_database):
    conn = isolated_database
    store.initialize(conn)
    for company in COMPANIES:
        publish(conn, company.lower())
    queries = []

    class RecordingCursor(Cursor):
        def execute(self, query, params=None, **kwargs):
            queries.append(query.as_string(self.connection) if isinstance(query, sql.Composable) else query)
            return super().execute(query, params, **kwargs)

    conn.cursor_factory = RecordingCursor
    for company in COMPANIES:
        queries.clear()
        assert len(store.search(conn, vector(), company=company)) == 1
        searches = [query for query in queries if "<=>" in query]
        assert len(searches) == 1
        assert "etl_chunks_" + company.lower() in searches[0]
        for other in COMPANIES:
            if other != company:
                assert "etl_chunks_" + other.lower() not in searches[0]
        assert "FROM etl_chunks " not in searches[0]
        assert 'FROM "etl_chunks" ' not in searches[0]
