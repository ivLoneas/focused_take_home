"""A document becomes visible in Gold only after one complete transaction."""
from pathlib import Path

import numpy as np
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from etl.embeddings import DIMENSIONS, MODEL, validate_vector


def initialize(conn):
    conn.execute(Path(__file__).with_name("schema.sql").read_text())
    register_vector(conn)


def reconcile_documents(conn, document_ids) -> int:
    """Delete Gold documents outside a complete, successfully published selection."""
    if isinstance(document_ids, (str, bytes)):
        raise ValueError("Document selection must be a nonempty collection of IDs")  # noqa: TRY004
    try:
        selected = list(document_ids)
    except TypeError as error:
        raise ValueError("Document selection must be a nonempty collection of IDs") from error
    if not selected or any(not isinstance(item, str) or not item.strip() for item in selected):
        raise ValueError("Document selection must contain nonempty string IDs")
    selected = list(dict.fromkeys(selected))
    with conn.transaction():
        result = conn.execute(
            "DELETE FROM etl_documents WHERE NOT (document_id = ANY(%s))",
            (selected,),
        )
    return result.rowcount


def is_current(conn, document_id, generation, expected_count):
    row = conn.execute(
        "SELECT d.generation, count(c.chunk_id) FROM etl_documents d "
        "LEFT JOIN etl_chunks c USING(document_id) WHERE d.document_id = %s GROUP BY d.document_id",
        (document_id,),
    ).fetchone()
    return row is not None and row[0] == generation and row[1] == expected_count


def replace_document(conn, source, chunks, texts, vectors, generation):
    """Validate and replace one document and all its chunks in a single transaction."""

    if not chunks or len(chunks) != len(texts) or len(chunks) != len(vectors):
        raise ValueError("Gold payload must contain equally sized, nonempty chunks/texts/vectors")
    if any(chunk.document_id != source.document_id for chunk in chunks):
        raise ValueError("Chunk belongs to another document")
    if any(not text.strip() for text in texts):
        raise ValueError("Empty embedding text")
    for vector in vectors:
        validate_vector(vector, DIMENSIONS)
    with conn.transaction():
        conn.execute(
            """INSERT INTO etl_documents
            (document_id,source_path,source_sha256,company,fiscal_year,quarter,report_type,title,
             source_url,page_count,generation,embedding_model)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(document_id) DO UPDATE SET
            source_path=excluded.source_path,source_sha256=excluded.source_sha256,
            company=excluded.company,fiscal_year=excluded.fiscal_year,quarter=excluded.quarter,
            report_type=excluded.report_type,title=excluded.title,source_url=excluded.source_url,
            page_count=excluded.page_count,generation=excluded.generation,
            embedding_model=excluded.embedding_model,updated_at=now()""",
            (source.document_id, source.path, source.sha256, source.company, source.fiscal_year,
             source.quarter, source.report_type, source.title, source.url, source.pages, generation, MODEL),
        )
        conn.execute("DELETE FROM etl_chunks WHERE document_id=%s", (source.document_id,))
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO etl_chunks
                (chunk_id,document_id,ordinal,body,embedding_text,headings,pages,source_refs,kind,embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(chunk.chunk_id, source.document_id, chunk.ordinal, chunk.text, text,
                  list(chunk.headings), list(chunk.pages), list(chunk.source_refs), chunk.kind,
                  np.asarray(vector, dtype=np.float32)) for chunk, text, vector in zip(chunks, texts, vectors, strict=True)],
            )


def search(conn, vector, limit=5, company=None, fiscal_year=None):
    """Use exact search for filtered subsets and HNSW for the unfiltered corpus."""

    validate_vector(vector, DIMENSIONS)
    if not 1 <= limit <= 100:
        raise ValueError("Search limit must be in 1..100")
    clauses, params = [], [np.asarray(vector, dtype=np.float32)]
    if company is not None:
        clauses.append("d.company=%s")
        params.append(company)
    if fiscal_year is not None:
        clauses.append("d.fiscal_year=%s")
        params.append(fiscal_year)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([np.asarray(vector, dtype=np.float32), limit])
    with conn.transaction():
        # Exact search avoids HNSW post-filter underfilling on small filtered subsets.
        if clauses:
            conn.execute("SET LOCAL enable_indexscan = off")
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT c.chunk_id,c.document_id,c.body AS text,c.headings,c.pages,c.source_refs,c.kind,"
                "d.company,d.fiscal_year,d.quarter,d.report_type,d.title,d.source_url AS url,d.source_path,"
                "1-(c.embedding <=> %s) AS score FROM etl_chunks c JOIN etl_documents d USING(document_id)"
                + where + " ORDER BY c.embedding <=> %s LIMIT %s", params,
            )
            return cursor.fetchall()
