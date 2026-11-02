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

-- Serialize migration against document publication and reconciliation.
LOCK TABLE etl_documents IN ACCESS EXCLUSIVE MODE;
CREATE UNIQUE INDEX IF NOT EXISTS etl_documents_company_key ON etl_documents(document_id, company);
CREATE INDEX IF NOT EXISTS etl_documents_filter ON etl_documents(company, fiscal_year, quarter, report_type);

DO $$
DECLARE
    company_slug text;
    table_name text;
    legacy_table regclass;
BEGIN
    IF EXISTS (
        SELECT 1 FROM etl_documents
        WHERE lower(company) NOT IN ('alphabet', 'amazon', 'apple', 'meta', 'netflix')
    ) THEN
        RAISE EXCEPTION 'Unsupported company in etl_documents; company-table migration aborted';
    END IF;

    -- Resolve only this schema, so isolated test schemas never migrate public data.
    legacy_table := to_regclass(format('%I.etl_chunks', current_schema()));
    IF legacy_table IS NOT NULL THEN
        EXECUTE format('LOCK TABLE %s IN ACCESS EXCLUSIVE MODE', legacy_table);
    END IF;

    FOREACH company_slug IN ARRAY ARRAY['alphabet', 'amazon', 'apple', 'meta', 'netflix'] LOOP
        table_name := 'etl_chunks_' || company_slug;
        EXECUTE format($ddl$
            CREATE TABLE IF NOT EXISTS %I (
                chunk_id text PRIMARY KEY,
                document_id text NOT NULL,
                company text NOT NULL CHECK (lower(company) = %L),
                ordinal integer NOT NULL,
                body text NOT NULL CHECK (length(body) > 0),
                embedding_text text NOT NULL,
                headings text[] NOT NULL,
                pages integer[] NOT NULL,
                source_refs text[] NOT NULL,
                kind text NOT NULL,
                embedding vector(1536) NOT NULL,
                search_text tsvector GENERATED ALWAYS AS (to_tsvector('english', embedding_text)) STORED,
                UNIQUE(document_id, ordinal),
                FOREIGN KEY (document_id, company)
                    REFERENCES etl_documents(document_id, company) ON DELETE CASCADE
            )
        $ddl$, table_name, company_slug);

        IF legacy_table IS NOT NULL THEN
            EXECUTE format($copy$
                INSERT INTO %I
                (chunk_id,document_id,company,ordinal,body,embedding_text,headings,pages,source_refs,kind,embedding)
                SELECT c.chunk_id,c.document_id,d.company,c.ordinal,c.body,c.embedding_text,
                       c.headings,c.pages,c.source_refs,c.kind,c.embedding
                FROM %s c JOIN etl_documents d USING(document_id) WHERE lower(d.company) = %L
            $copy$, table_name, legacy_table, company_slug);
        END IF;

        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I(document_id)', table_name || '_document', table_name);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I USING gin(search_text)', table_name || '_text', table_name);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I USING hnsw(embedding vector_cosine_ops)',
                       table_name || '_vector', table_name);
    END LOOP;

    IF legacy_table IS NOT NULL THEN
        EXECUTE format('DROP TABLE %s', legacy_table);
    END IF;
END $$;
