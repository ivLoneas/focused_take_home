CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS etl_documents (
    document_id text PRIMARY KEY,
    source_path text NOT NULL UNIQUE,
    source_sha256 text NOT NULL,
    company text NOT NULL,
    fiscal_year integer NOT NULL,
    quarter text NOT NULL,
    report_type text NOT NULL,
    title text NOT NULL,
    source_url text NOT NULL,
    page_count integer NOT NULL CHECK (page_count > 0),
    generation text NOT NULL,
    embedding_model text NOT NULL CHECK (embedding_model = 'text-embedding-3-small'),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS etl_chunks (
    chunk_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES etl_documents(document_id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    body text NOT NULL CHECK (length(body) > 0),
    embedding_text text NOT NULL,
    headings text[] NOT NULL,
    pages integer[] NOT NULL,
    source_refs text[] NOT NULL,
    kind text NOT NULL,
    embedding vector(1536) NOT NULL,
    search_text tsvector GENERATED ALWAYS AS (to_tsvector('english', embedding_text)) STORED,
    UNIQUE(document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS etl_documents_filter ON etl_documents(company, fiscal_year, quarter, report_type);
CREATE INDEX IF NOT EXISTS etl_chunks_document ON etl_chunks(document_id);
CREATE INDEX IF NOT EXISTS etl_chunks_text ON etl_chunks USING gin(search_text);
CREATE INDEX IF NOT EXISTS etl_chunks_vector ON etl_chunks USING hnsw(embedding vector_cosine_ops);
