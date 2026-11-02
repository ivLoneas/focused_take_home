# Retrieval database dump

`retrieval_database.dump` is a PostgreSQL custom-format archive of the complete baseline retrieval database. It is compressed with zstd and contains:

- PostgreSQL schema, constraints, and indexes;
- the pgvector extension (`0.8.2`);
- 100 rows in `etl_documents`;
- 20,274 rows in `etl_chunks`;
- one 1,536-dimensional `text-embedding-3-small` vector for every chunk.

The archive was produced with PostgreSQL 17.10 after the pinned `data/active_manifest.csv` ETL completed successfully on 2026-11-02. It does not contain credentials, roles, ownership, or access-control grants.

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
  -c 'SELECT count(*) AS chunks FROM etl_chunks;' \
  -c 'SELECT count(*) AS vectors FROM etl_chunks WHERE vector_dims(embedding) = 1536;'
```

The expected counts are 100 documents, 20,274 chunks, and 20,274 vectors.
