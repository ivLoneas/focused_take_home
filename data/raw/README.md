# FAANG+ financial-report PDF collection

Snapshot: **2026-10-31**. Fiscal years **2022–2026**, where available.

**799 PDFs · 27,563 pages · 1,590,581,590 bytes (1.591 GB / 1.481 GiB).**

This README describes the complete Bronze archive. See [`data/AGENTS.md`](../AGENTS.md) for the source-data contract and [`data/active_manifest.csv`](../active_manifest.csv) for the pinned 100-document retrieval corpus.

## Scope

15 companies: FAANG (Meta, Apple, Amazon, Netflix, Alphabet), plus Microsoft, NVIDIA, Tesla, Uber, AMD, Intel, Adobe, Salesforce, Oracle and Airbnb. This is a practical technology-company selection, not the membership of a particular FAANG+ index or a Fortune 100 ranking.

Includes **66 annual reports / Forms 10-K covering 64 company-years**, plus **733 quarterly filings, earnings releases, shareholder letters, presentations, financial tables and earnings-call materials**. Counts are PDF files, not distinct reporting periods. Alphabet has both an annual-report edition and a standalone 10-K for some years; these overlap in content but are distinct PDFs. Annual filings can contain exhibits. Original PDF bytes are preserved; no HTML or Office documents were converted to PDF.

Fiscal-year labels follow the issuer, not the publication date. For example, NVIDIA FY2026 ended January 25, 2026. Calendar-2026 publications labelled FY2027 are outside the requested fiscal-year range. A 2026 proxy does not count as a FY2026 annual financial report.

## Company totals

| Company | PDFs | Pages | MB (decimal) | Annual fiscal years downloaded |
|---|---:|---:|---:|---|
| adobe | 23 | 559 | 5.41 | 2022, 2023, 2024, 2025 |
| airbnb | 54 | 2,471 | 170.90 | 2022, 2023, 2024, 2025 |
| alphabet | 47 | 1,675 | 34.23 | 2022, 2023, 2024, 2025 |
| amazon | 57 | 2,632 | 26.19 | 2022, 2023, 2024, 2025 |
| amd | 40 | 1,268 | 56.04 | 2022, 2023, 2024, 2025 |
| apple | 38 | 905 | 72.25 | 2022, 2023, 2024, 2025 |
| intel | 73 | 1,302 | 114.21 | 2022, 2023, 2024, 2025 |
| meta | 95 | 3,502 | 54.69 | 2022, 2023, 2024, 2025 |
| microsoft | 5 | 682 | 10.70 | 2022, 2023, 2024, 2025, 2026 |
| netflix | 42 | 967 | 24.43 | 2022, 2023, 2024, 2025 |
| nvidia | 85 | 2,589 | 158.78 | 2022, 2023, 2024, 2025, 2026 |
| oracle | 61 | 2,234 | 76.13 | 2022, 2023, 2024, 2025, 2026 |
| salesforce | 80 | 3,723 | 376.68 | 2022, 2023, 2024, 2025, 2026 |
| tesla | 23 | 1,252 | 152.95 | 2022, 2023, 2024, 2025 |
| uber | 76 | 1,802 | 257.00 | 2022, 2023, 2024, 2025 |

## Fiscal-year totals

| Fiscal year | PDFs | Pages | MB (decimal) |
|---|---:|---:|---:|
| 2022 | 164 | 6,162 | 270.39 |
| 2023 | 170 | 5,920 | 288.41 |
| 2024 | 168 | 5,760 | 367.86 |
| 2025 | 168 | 5,524 | 436.41 |
| 2026 | 129 | 4,197 | 227.51 |

Mean length: **34.5 pages**; median: **17 pages**. The largest PDF is Salesforce FY2025 Q4’s earnings presentation (**95.48 MB**, 20 pages); the longest is Amazon FY2026 Q3’s 10-Q filing package (**386 pages**, 2.85 MB). PDF totals exclude metadata, manifests and documentation. GB/MB are decimal; GiB/MiB are binary.

## Coverage and availability

Annual reports are present for every company for FY2022–FY2025. FY2026 annual reports are included for companies whose reports were located and validated. FY2026 annual-report PDFs were not found in the checked sources for: **adobe, airbnb, alphabet, amazon, amd, apple, intel, meta, netflix, tesla, uber**. This does not mean that all FY2026 reports are unpublished; consult the recorded source archives for updates. Partial FY2026 quarterly reporting is included.

Quarterly source discovery reuses the repository's 2026-10-30 inventory, filtered to PDF and FY2022–FY2026. Annual reports were separately researched on this snapshot date. The quarter inventory does not claim every publicly available PDF or filing has been collected. In particular, Microsoft's quarterly source materials were HTML/Office files in the prior inventory and are excluded from this PDF collection; its annual reports cover FY2022–FY2026. AMD and some other companies' quarters are represented by financial presentations/supporting materials rather than a standalone PDF earnings release.

The previous repository contained metadata but no report PDFs. Its original inventories are preserved under `_metadata/previous_inventory/`; those historical counts are not the current dataset totals.

## Layout and indexes

```text
data/raw/<company>/<fiscal-year>/Q<quarter>/<document>.pdf
data/raw/<company>/<fiscal-year>/annual/<company>-<year>-annual-report.pdf
```

- `manifest.csv`: all downloaded PDFs, source URLs, download timestamps, actual bytes/pages and SHA-256.
- `annual_manifest.csv`: the annual-report subset, referencing the same files without duplication.
- `annual_coverage.csv`: all 75 company/year annual-report combinations and their availability.
- `coverage.csv`: quarterly PDF coverage, separating downloaded, no-PDF-in-source-inventory and not-yet-available states.
- `summary.json`: exact machine-readable totals and breakdowns.
- `_metadata/annual_candidates.json`: supplemental annual-report source URLs.
- `_metadata/acquisition.jsonl`: acquisition records and first-three-page text samples.
- `_metadata/failed_downloads.json`: unresolved download failures (0).

All retained PDFs were downloaded from company investor-relations sites or their linked document hosts/CDNs. Source URLs and resolved download URLs are recorded separately. Failed AnnualReports.com mirror attempts remain only in acquisition history; none are counted in the retained collection. `_metadata/source_overrides.json` records replacement official links.

## Validation and reproduction

Every retained file passed a PDF-header check, full SHA-256 and byte-size check, pypdf page-tree parsing, and an independent Poppler `pdfinfo` page-count check. There are **799 distinct SHA-256 hashes**. Text sampling is a format/content sanity check, not a full transcription or a financial-data accuracy audit.

Install Python, `pypdf[crypto]`, curl and Poppler (`pdfinfo`), then run from the project root:

```sh
python scripts/download_reports.py
python scripts/audit_reports.py
```

Downloads resume from existing PDFs. Re-running downloads fetches the recorded URLs; it does not automatically discover newly published periods.
