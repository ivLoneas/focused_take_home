# Baseline ETL pipeline

This directory owns the medallion pipeline that turns the checked, immutable financial-report corpus into retrieval-ready PostgreSQL rows. Keep the implementation simple and preserve evidence: retrieved text must retain its source document, section path, page numbers, and Docling item references.

## Architecture

### Bronze: `data/raw`

`data/raw/manifest.csv` is the authoritative inventory for the complete 799-document archive. `data/active_manifest.csv` pins the 100 documents selected for baseline ETL and retrieval; it preserves complete rows from the raw manifest and is the CLI/Docker default. The source-data contract lives in `data/AGENTS.md`.

`etl.manifest.load_manifest` validates required metadata, duplicate paths, fiscal periods, PDF extensions, path confinement, page counts, and SHA-256 syntax. An inventory may live outside `data/raw`, but all PDF paths are always resolved and confined beneath `data/raw`. `verify_source` checks the PDF header and full checksum immediately before every conversion, including cache hits. The pipeline never modifies Bronze PDFs.

### Silver: `data/silver/<document_id>`

Docling performs layout-aware PDF conversion with:

- heading hierarchy reconstruction enabled (bookmarks, numbering, then visual style);
- accurate TableFormer structure and cell matching;
- RapidOCR for image regions;
- rendered figure crops described by the OpenAI Responses API with `gpt-6-luna`, high image detail, and no reasoning;
- a conservative financial-figure prompt that forbids invented values.

Docling never runs a local picture-description model. The API description is attached to the original `PictureItem` before block extraction, so its page provenance and Docling reference survive serialization and chunking. Generated picture descriptions are labeled `[Generated image description; verify against source]`. Repeated page headers and footers are excluded. Text nested inside picture groups is traversed so OCR/table content is not silently dropped.

Each document publishes these artifacts:

- `document.json`: complete Docling document graph;
- `document.md`: inspectable rendering;
- `blocks.json`: normalized text/table/picture blocks with hierarchy and provenance;
- `chunks.json`: retrieval chunks;
- `metadata.json`: source/config fingerprints, counts, and artifact hashes. This completion marker is written last.

The Silver cache key includes the source checksum, inventory page count, parser versions, and parsing configuration. Picture descriptions have a separate content-addressed cache under `data/gold/embedding_cache/pictures`; its key covers the exact PNG bytes, model, prompt, and detail setting, and its integrity hash covers the response and measured usage. Luna output-limit truncation is retried with bounded increasing output limits, and cached usage aggregates every attempt. Other incomplete responses are rejected, and only a final completed description is cached. A chunk-setting change reuses valid parsing and picture descriptions; a source or parser-setting change reconverts the PDF. Partial conversions, page-count mismatches, empty extractions, and empty API descriptions are rejected.

### Gold: PostgreSQL + pgvector

`text-embedding-3-small` produces 1,536-dimensional vectors. Embedding input prepends company, fiscal period, report type, title, and section path to the chunk body. This metadata enrichment makes filtered and semantic retrieval agree on entity and period context.

Embedding requests use content-addressed batches of at most 64 chunks under `data/gold/embedding_cache`. Each cache record includes API-reported token usage and an integrity hash. Completed batches survive retries; corrupt batches are requested again. Gold publication replaces one document atomically, so a failed insert leaves the previous generation visible.

`etl_documents` stores shared source/filter/citation metadata. Five physical tables (`etl_chunks_alphabet`,
`etl_chunks_amazon`, `etl_chunks_apple`, `etl_chunks_meta`, `etl_chunks_netflix`) store each company's body,
contextualized embedding text, headings, pages, Docling refs, full-text search data, and `vector(1536)`. Each table has
its own GIN full-text and HNSW cosine indexes. A company CHECK and composite document/company foreign key enforce
isolation while preserving lowercase manifest metadata. `etl.companies` defines the canonical tool literals and table
mapping; ETL accepts the corresponding lowercase manifest names. Unsupported companies fail before publication.

`initialize` runs the schema in a transaction, migrates existing `etl_chunks` rows without re-embedding, and removes
the legacy table only after all rows copy successfully. Unknown companies abort the entire migration. Initialization
is idempotent and serializes against publication through a document-table lock. Apply `schema.sql` manually with
`psql --single-transaction -v ON_ERROR_STOP=1`; never execute the migration outside a transaction.

Search requires a canonical company and queries only its physical table. Fiscal-year-filtered vector queries use
exact search to avoid ANN post-filter under-filling. After every selected document publishes successfully, Gold
reconciliation removes documents outside the selected manifest and cascades their chunks across all five tables.
Reconciliation is skipped after any document failure so a previous usable corpus is preserved.

## Hierarchy-aware chunking

The baseline budget is 1,000 characters with 200 characters of overlap, matching the project brief and the cited PDF-to-RAG study. This is implemented over structured Docling blocks rather than flat Markdown:

1. Adjacent prose merges only when the complete heading path matches.
2. A chunk never carries overlap across a section boundary.
3. Tables remain a distinct kind. Rows are kept intact where possible, and column headers are repeated on every split table chunk.
4. Picture descriptions remain distinct from prose.
5. Every chunk unions page numbers and source item references for all contributing and overlapping blocks.
6. Chunk IDs are deterministic hashes of document, ordinal, content, hierarchy, provenance, and kind.

The character budget is the requested baseline. Retrieval evaluations should drive any later move to tokenizer-aware limits or parent-child retrieval.

## Docker operation

The Docker image uses Python 3.14 and CPU-only PyTorch. The Compose model-cache volume persists Docling and OCR downloads; `data/` is bind-mounted so Silver, picture/embedding caches, and reports survive container replacement. PostgreSQL is bound only to `127.0.0.1:55432`.

The baseline Compose command reads the pinned `data/active_manifest.csv`: the newest 20 reports for each of Alphabet, Amazon, Apple, Meta, and Netflix. Retained reports are processed deterministically in manifest order. Bronze remains unchanged. Rebuild the pinned selection deliberately with `uv run python scripts/build_active_manifest.py`, review the manifest diff, and run the alignment tests before restarting ETL.

Copy `.env.example` to `.env`, set `OPENAI_API_KEY`, then run:

```sh
docker compose --profile etl build etl
docker compose --profile etl up -d etl
docker compose logs -f etl
```

On Linux, set `LOCAL_UID` and `LOCAL_GID` if they differ from the Compose defaults so bind-mounted files retain host ownership. A one-document validation is:

```sh
docker compose --profile etl run --rm etl run --limit 1 --fail-fast
```

Use `--manifest PATH` to run an explicitly reviewed inventory. Repeat `--company` to narrow that manifest to multiple companies. `--per-company-limit N --keep newest` keeps the newest `N` reports from every requested company; `--keep oldest` selects the other end of the timeline. `--limit` is a final global cap. Other useful flags are `--parse-only`, `--no-pictures`, `--max-chars`, `--overlap`, and `--fail-fast`. `--parse-only` still requires `OPENAI_API_KEY` when pictures are enabled; use `--parse-only --no-pictures` for a fully offline parse. Re-running the same command safely reuses validated Silver, picture descriptions, embedding batches, and current database generations.

## Spend and progress

`data/etl_runs/latest.json` is updated after every document. It records document status/duration, chunk counts, stale Gold documents pruned, embedding usage, picture input/output tokens and calls, separate picture cost, and combined cost. The pinned rates are **$0.02 per 1 million input tokens** for `text-embedding-3-small`, and **$0.10 per 1 million input tokens plus $0.50 per 1 million output tokens** for `gpt-6-luna`. These rates were verified against OpenAI model documentation when this baseline was implemented. Local Docling/OCR inference has no API charge; infrastructure/electricity is outside this dollar total.

Use the report's final `totals.cost_usd` as the measured corpus processing spend. `totals.picture_cost_usd` isolates Luna picture annotation spend. Both represent the original API usage of the exact content-addressed entries in the current corpus, so reruns do not double-count cached work.

## Verification

Independent pytest suites cover manifest/file safety, prose/table/picture chunking, page provenance and overlap, Luna request/cache failures, malformed embedding responses, cache recovery, genuine Docling document types, Silver lifecycle corruption, spend accounting, and transactional pgvector replacement/search. Run:

```sh
uv run pytest -q tests/etl
ETL_TEST_DATABASE_URL=postgresql://rag:rag_local@localhost:55432/rag uv run pytest -q tests/etl/test_store_integration.py
uv run ruff check etl
```

Tests must be written by an independent subagent before behavior is implemented or changed. Keep that rule for future ETL work.
