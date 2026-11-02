# Retrieval database dump

`retrieval_database.dump` is a PostgreSQL custom-format archive of the complete baseline retrieval database. It is compressed with zstd and contains:

- PostgreSQL schema, constraints, and indexes;
- the pgvector extension (`0.8.2`);
- 100 rows in `etl_documents`;
- 20,274 chunks across five company-specific vector tables;
- one 1,536-dimensional `text-embedding-3-small` vector for every chunk.

The archive was produced with PostgreSQL 17.10 after the pinned `data/active_manifest.csv` ETL completed successfully
and the lossless company-table migration ran on 2026-11-02. It does not contain credentials, roles, ownership, or
access-control grants. The snapshot was restored into a temporary database and compared with the original backup:
all document metadata, chunk bodies, hierarchy, pages, source references, search text, and vectors matched.

| Company | Table | Chunks/vectors |
| --- | --- | ---: |
| Alphabet | `etl_chunks_alphabet` | 3,353 |
| Amazon | `etl_chunks_amazon` | 5,829 |
| Apple | `etl_chunks_apple` | 2,779 |
| Meta | `etl_chunks_meta` | 5,344 |
| Netflix | `etl_chunks_netflix` | 2,969 |

Each table has its own HNSW cosine index and GIN full-text index. Company checks and composite document/company
foreign keys prevent cross-company inserts; document deletion cascades to chunks. There is no shared vector table.

Verify the archive before restoring it:

```sh
cd /path/to/focused_take_home
shasum -a 256 -c data/dumps/retrieval_database.dump.sha256
```

On a fresh clone with an empty Compose database, restore it with:

```sh
docker compose up -d postgres
docker compose exec -T postgres pg_restore \
  -U rag -d rag --exit-on-error --no-owner --no-acl \
  < data/dumps/retrieval_database.dump
```

To replace an existing local `rag` database, clear its public schema first. This deletes every table in that database:

```sh
docker compose exec -T postgres psql -U rag -d rag \
  -v ON_ERROR_STOP=1 \
  -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
docker compose exec -T postgres pg_restore \
  -U rag -d rag --exit-on-error --no-owner --no-acl \
  < data/dumps/retrieval_database.dump
```

Verify the restored corpus:

```sh
docker compose exec -T postgres psql -U rag -d rag \
  -c 'SELECT count(*) AS documents FROM etl_documents;' \
  -c 'SELECT company, count(*) AS chunks, count(*) FILTER (WHERE vector_dims(embedding) = 1536) AS vectors FROM (SELECT company, embedding FROM etl_chunks_alphabet UNION ALL SELECT company, embedding FROM etl_chunks_amazon UNION ALL SELECT company, embedding FROM etl_chunks_apple UNION ALL SELECT company, embedding FROM etl_chunks_meta UNION ALL SELECT company, embedding FROM etl_chunks_netflix) c GROUP BY company ORDER BY company;'
```

The expected counts are 100 documents, 20,274 chunks, and 20,274 vectors.

For an older dump containing `etl_chunks`, restore it and then apply the current schema atomically:

```sh
docker compose exec -T postgres psql -U rag -d rag -v ON_ERROR_STOP=1 --single-transaction < etl/schema.sql
```

ETL initialization performs the same idempotent migration. It copies existing vectors into their company tables
without new embedding calls and aborts without dropping the legacy data if a company cannot be mapped.
