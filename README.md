# FAANG+ financial-report PDFs

Public financial-report PDFs for 15 technology companies, covering fiscal years 2022–2026 where available. Includes annual reports / Forms 10-K, quarterly filings, earnings releases and supporting earnings materials.

The complete Bronze archive is in [`data/raw`](data/raw), organized by company, fiscal year and quarter, with supplemental annual reports under `annual/`. The [data contract](data/AGENTS.md) defines the distinction between this archive and the pinned active retrieval corpus.
See the [dataset README](data/raw/README.md) for company totals, scope, source notes, file formats, validation, and reproduction commands.

- [Source manifest and checksums](data/raw/manifest.csv)
- [Active retrieval manifest](data/active_manifest.csv)
- [Annual-report subset](data/raw/annual_manifest.csv)
- [Annual-report availability](data/raw/annual_coverage.csv)
- [Quarter-by-quarter coverage](data/raw/coverage.csv)
- [Machine-readable size summary](data/raw/summary.json)

The resumable downloader is `scripts/download_reports.py`; the integrity audit and inventory builder is `scripts/audit_reports.py`. Both use Python and `pypdf`; the downloader also uses curl and the audit requires Poppler's `pdfinfo`. See the dataset README for reproduction commands and source limitations.

## Quick start: web agent

Prerequisites: Python 3.14, `uv`, Docker, and a populated PostgreSQL Gold index. If the retrieval index has not been
built yet, complete the [Retrieval ETL](#retrieval-etl) steps first.

From the project root, install dependencies and create the local configuration:

```sh
uv sync
cp .env.example .env
```

Add your `OPENAI_API_KEY` to `.env`, then start PostgreSQL:

```sh
docker compose up -d postgres
```

Start the API in one terminal:

```sh
uv run python -m backend
```

Start the frontend in a second terminal:

```sh
uv run python -m http.server 5173 --directory frontend
```

Open [http://localhost:5173](http://localhost:5173). The API health check is available at
[http://localhost:8000/health](http://localhost:8000/health), and its interactive documentation is at
[http://localhost:8000/docs](http://localhost:8000/docs).

## Retrieval ETL

The Dockerized ETL validates the Bronze inventory, parses PDFs with Docling's heading hierarchy, accurate tables and OCR, describes rendered figures with `gpt-6-luna`, writes checksum-protected Silver artifacts, creates OpenAI embeddings, and atomically publishes retrieval rows to PostgreSQL/pgvector. Figure descriptions retain the originating PDF page and Docling reference through chunking.

The default Compose run reads the pinned [`data/active_manifest.csv`](data/active_manifest.csv): 100 reports, with the newest 20 each from Alphabet, Amazon, Apple, Meta, and Netflix. The full 799-document source archive remains intact in `data/raw`. Regenerate the active manifest deliberately with `uv run python scripts/build_active_manifest.py` after reviewing archive changes.

```sh
cp .env.example .env
# Add OPENAI_API_KEY to .env, then:
docker compose --profile etl build etl
docker compose --profile etl up -d etl
docker compose logs -f etl
```

Progress and measured Luna, embedding, and combined spend are written to `data/etl_runs/latest.json`. See [`etl/AGENTS.md`](etl/AGENTS.md) for artifacts, invariants, algorithms, and runner options.

A restore-tested snapshot of the complete 100-document Gold database is committed at [`data/dumps/retrieval_database.dump`](data/dumps/retrieval_database.dump). See [`data/dumps/README.md`](data/dumps/README.md) for checksum, restore, replacement, and verification commands. Restoring this archive lets a new machine run retrieval without repeating PDF parsing, Luna annotation, or embedding generation.

## Agent retrieval

`agents.retrieval.PgVectorRetriever` is a model-independent LangChain `BaseRetriever` over the Gold pgvector store. It
accepts injected query embeddings and a database connection factory, supports optional company and fiscal-year
filters, and returns `Document` objects with source, hierarchy, page, and score metadata. The embedding implementation
must be compatible with the vectors used to build the Gold index.

The baseline graph's custom evidence contract is supported by
`agents.retrieval.BaselineRetrieverAdapter`. See [`agents/baseline/AGENTS.md`](agents/baseline/AGENTS.md) for a complete
configuration example.

## Web interface

The local web interface is split into a stateless FastAPI backend and a buildless HTML/CSS/JavaScript frontend. The
browser saves recent runs in `localStorage`; it never sends prior turns to the API, and the server keeps no conversation
or session state.

See [Quick start: web agent](#quick-start-web-agent) for launch commands. The baseline agent may answer, request a
missing company/period/metric, or reject an out-of-domain question; retrieval is attempted up to three times before it
formulates its evidence-bound response.

## LangSmith observability

Baseline runs can be traced end to end in LangSmith, including nested graph nodes, model calls, and pgvector retrievals.
Enable it in `.env` before constructing `BaselineAgent`:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-langsmith-api-key>
LANGSMITH_PROJECT=focused-take-home
```

Tracing is disabled by default for offline development. Enabling it without an API key fails during agent
construction instead of running without observability. The resulting traces expose execution order, latency, errors,
and model token usage; configure dashboards, alerts, sampling, and online evaluators in the LangSmith project.
