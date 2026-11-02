# Source data contract

This directory defines the only document corpus used by the retrieval system. Code, Docker defaults, evaluations, and documentation must distinguish the complete Bronze archive from the smaller active retrieval corpus described below.

## Authoritative inventories

`raw/manifest.csv` is the authoritative inventory for the complete downloaded archive. It contains 799 immutable PDFs, 27,563 pages, and 15 technology companies covering fiscal years 2022-2026 where available. Each row records the relative PDF path, issuer fiscal period, report type, original and resolved source URLs, byte count, page count, retrieval time, and SHA-256. `raw/summary.json`, `raw/coverage.csv`, `raw/annual_manifest.csv`, and `raw/annual_coverage.csv` describe that archive but do not select retrieval documents.

`active_manifest.csv` is the authoritative inventory for ETL, retrieval, and positive grounded evaluations. It preserves the complete `raw/manifest.csv` schema and exact row values for 100 PDFs: the newest 20 reports for each of Alphabet, Amazon, Apple, Meta, and Netflix. It currently contains 3,503 pages.

| Company | Documents | Pages | Retained period |
|---|---:|---:|---|
| Alphabet | 20 | 587 | FY2025 Q1-FY2026 Q3 |
| Amazon | 20 | 1,220 | FY2025 Q1-FY2026 Q3 |
| Apple | 20 | 490 | FY2024 Q2-FY2026 Q3 |
| Meta | 20 | 736 | FY2025 Q4-FY2026 Q3 |
| Netflix | 20 | 470 | FY2024 Q3-FY2026 Q3 |

The active manifest is pinned. A change to the full Bronze archive does not silently change retrieval or evaluation scope. Regenerate it deliberately with `uv run python scripts/build_active_manifest.py`, review the diff, then rerun alignment tests. Selection sorts by company, issuer fiscal year, quarter, and path; an annual report sorts after Q4 of the same fiscal year. The newest 20 rows for each active company survive the cutoff and are processed in chronological order.

## Source rules

- Treat PDFs under `raw/` as immutable Bronze evidence. Never rewrite, normalize, or delete them from ETL code.
- Do not scrape or add external documents during ETL, retrieval, or evaluation. Acquisition is a separate explicit workflow in `scripts/download_reports.py`.
- Resolve every manifest `path` under `data/raw`; reject absolute paths, parent traversal, non-PDF files, duplicate paths, invalid periods, and invalid checksums.
- Verify the PDF header and SHA-256 immediately before conversion, including cache hits.
- Use the issuer's fiscal-year and fiscal-quarter labels. They are not necessarily calendar periods or publication dates.
- Preserve company, fiscal period, report type, title, source URL, page numbers, hierarchy, and Docling references through Silver chunks and Gold rows.
- Positive grounded evaluation questions may cite only PDFs in `active_manifest.csv`. Missing-data and out-of-distribution cases may mention excluded companies only to test scope handling.

## Derived data

`silver/<document_id>/` contains checksum-protected Docling documents, Markdown, normalized blocks, retrieval chunks, and a completion marker. `gold/embedding_cache/` contains content-addressed OpenAI embedding responses, plus `gold/embedding_cache/pictures/` for exact-PNG `gpt-6-luna` figure descriptions. Both caches retain measured token usage and integrity hashes. `etl_runs/latest.json` is the live progress and selected-corpus spend report, including separate picture cost and combined API cost. These directories are reproducible runtime artifacts and are excluded from Git.

PostgreSQL/pgvector is the active Gold store. It must contain only documents selected by `active_manifest.csv` for the baseline run. Publication is atomic per document, and reruns reuse valid Silver and embedding caches. After every selected document succeeds, the runner deletes Gold documents outside the selection in one transaction; a partial or failed run preserves the previous corpus instead of pruning it.

`dumps/retrieval_database.dump` is the Git-portable snapshot of the completed Gold database. It is a zstd-compressed PostgreSQL custom-format archive without credentials, roles, ownership, or grants. `dumps/README.md` records its expected row/vector counts, SHA-256 verification, restore procedure, and PostgreSQL/pgvector compatibility. Regenerate and restore-test the dump whenever the active corpus, chunking, embeddings, or Gold schema changes.

## Validation workflow

After changing source data or the active selection, run:

```sh
uv run python scripts/audit_reports.py
uv run python scripts/build_active_manifest.py
uv run pytest -q tests/etl/test_manifest.py tests/etl/test_manifest_contract.py tests/etl/test_eval_alignment.py
```

`audit_reports.py` requires Poppler `pdfinfo` and rebuilds the full Bronze inventory. `build_active_manifest.py` does not download or mutate PDFs; it copies exact audited rows into the pinned active inventory.
