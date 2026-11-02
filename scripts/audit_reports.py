"""Verify downloaded PDF bytes/page counts and rebuild the dataset inventory."""

import csv
import json
import re
import statistics
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from utils import read_json, sha256_bytes, write_csv, write_json

ROOT = Path(__file__).resolve().parents[1] / "data" / "raw"
META = ROOT / "_metadata"


def verify(row):
    path = ROOT / row["path"]
    data = path.read_bytes()
    assert data.startswith(b"%PDF-"), path
    assert len(data) == row["bytes"], path
    assert sha256_bytes(data) == row["sha256"], path
    result = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, check=True)
    match = re.search(r"^Pages:\s+(\d+)", result.stdout, re.MULTILINE)
    assert match and int(match.group(1)) == row["pages"], (path, result.stdout)
    return row


def summarize(rows):
    return {"documents": len(rows), "bytes": sum(r["bytes"] for r in rows), "pages": sum(r["pages"] for r in rows)}


def main():
    """Validate downloaded PDFs, rebuild manifests, and summarize corpus coverage."""

    results = read_json(META / "download_results.json")
    successful = [r for r in results if r["status"] == "downloaded"]
    failures = [r for r in results if r["status"] != "downloaded"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(verify, successful))
    actual_paths = {str(p.relative_to(ROOT)) for p in ROOT.rglob("*.pdf") if "_metadata" not in p.parts}
    assert actual_paths == {r["path"] for r in rows}, "Untracked PDFs or missing files"
    assert len({r["path"] for r in rows}) == len(rows), "Duplicate paths"
    companies = sorted({r["company"] for r in results})
    totals = summarize(rows)
    annual = [r for r in rows if r["report_type"] == "annual_report"]
    annual_periods = {(r["company"], int(r["fiscal_year"])) for r in annual}
    summary = {
        "as_of": datetime.now(UTC).date().isoformat(),
        "fiscal_years": [2022, 2023, 2024, 2025, 2026],
        "companies": companies,
        "total_pdfs": totals["documents"],
        "total_bytes": totals["bytes"],
        "total_pages": totals["pages"],
        "total_mb": totals["bytes"] / 1e6,
        "total_mib": totals["bytes"] / 1024**2,
        "total_gb": totals["bytes"] / 1e9,
        "total_gib": totals["bytes"] / 1024**3,
        "annual_reports": summarize(annual),
        "annual_company_years": len(annual_periods),
        "quarterly_and_supporting_documents": summarize([r for r in rows if r not in annual]),
        "company_summaries": [dict(company=c, **summarize([r for r in rows if r["company"] == c])) for c in companies],
        "year_summaries": [
            dict(fiscal_year=y, **summarize([r for r in rows if int(r["fiscal_year"]) == y])) for y in range(2022, 2027)
        ],
        "report_types": dict(Counter(r["report_type"] for r in rows)),
        "unique_sha256": len({r["sha256"] for r in rows}),
        "mean_pages": statistics.mean(r["pages"] for r in rows),
        "median_pages": statistics.median(r["pages"] for r in rows),
        "largest_pdf": max(rows, key=lambda r: r["bytes"])["path"],
        "longest_pdf": max(rows, key=lambda r: r["pages"])["path"],
        "failed_downloads": len(failures),
        "validation": "Every PDF: header, byte size, SHA-256, pypdf page tree, and independent Poppler pdfinfo page count.",
        "document_totals_exclude_metadata": True,
    }
    fields = [
        "company",
        "fiscal_year",
        "quarter",
        "role",
        "report_type",
        "title",
        "format",
        "path",
        "bytes",
        "pages",
        "sha256",
        "url",
        "final_url",
        "source_url",
        "retrieved_at",
        "mirror_note",
        "sample_text_characters",
        "previous_hash_matches",
    ]
    write_csv(ROOT / "manifest.csv", rows, fieldnames=fields, extrasaction="ignore")
    write_csv(ROOT / "annual_manifest.csv", annual, fieldnames=fields, extrasaction="ignore")
    write_json(ROOT / "summary.json", summary)
    write_json(META / "failed_downloads.json", failures)
    annual_coverage = []
    for c in companies:
        for y in range(2022, 2027):
            matches = [r for r in annual if r["company"] == c and int(r["fiscal_year"]) == y]
            annual_coverage.append(
                {
                    "company": c,
                    "fiscal_year": y,
                    "status": "downloaded" if matches else "not_found_in_checked_sources",
                    "documents": len(matches),
                    "pages": sum(r["pages"] for r in matches),
                }
            )
    write_csv(
        ROOT / "annual_coverage.csv",
        annual_coverage,
        fieldnames=["company", "fiscal_year", "status", "documents", "pages"],
        extrasaction="ignore",
    )
    old = list(csv.DictReader((META / "previous_inventory" / "coverage.csv").open()))
    quarterly_coverage = []
    for entry in old:
        if not 2022 <= int(entry["fiscal_year"]) <= 2026:
            continue
        matches = [
            r
            for r in rows
            if r["company"] == entry["company"]
            and r["fiscal_year"] == entry["fiscal_year"]
            and r["quarter"] == entry["quarter"]
            and "/annual/" not in r["path"]
        ]
        quarterly_coverage.append(
            dict(
                company=entry["company"],
                fiscal_year=entry["fiscal_year"],
                quarter=entry["quarter"],
                status="downloaded"
                if matches
                else (
                    "not_yet_available_in_source_inventory"
                    if entry["status"] == "not_yet_available"
                    else "no_pdf_in_source_inventory"
                ),
                **summarize(matches),
            )
        )
    write_csv(
        ROOT / "coverage.csv",
        quarterly_coverage,
        fieldnames=["company", "fiscal_year", "quarter", "status", "documents", "bytes", "pages"],
        extrasaction="ignore",
    )
    company_lines = []
    for c in companies:
        cr = [r for r in rows if r["company"] == c]
        ar = [r for r in annual if r["company"] == c]
        company_lines.append(
            f"| {c} | {len(cr)} | {sum(r['pages'] for r in cr):,} | {sum(r['bytes'] for r in cr) / 1e6:.2f} | {', '.join(sorted({r['fiscal_year'] for r in ar}))} |"
        )
    year_lines = [
        f"| {r['fiscal_year']} | {r['documents']} | {r['pages']:,} | {r['bytes'] / 1e6:.2f} |"
        for r in summary["year_summaries"]
    ]
    missing = ", ".join(r["company"] for r in annual_coverage if r["fiscal_year"] == 2026 and not r["documents"])
    largest = max(rows, key=lambda r: r["bytes"])
    longest = max(rows, key=lambda r: r["pages"])
    size_extremes = f"Largest PDF: `{largest['path']}` ({largest['bytes'] / 1e6:.2f} MB, {largest['pages']} pages). Longest PDF: `{longest['path']}` ({longest['pages']} pages, {longest['bytes'] / 1e6:.2f} MB)."
    missing_older = [(c, y) for c in companies for y in range(2022, 2026) if (c, y) not in annual_periods]
    historical_coverage = (
        "Annual reports are present for every company for FY2022–FY2025."
        if not missing_older
        else "Earlier annual-report gaps: " + ", ".join(f"{c} FY{y}" for c, y in missing_older) + "."
    )
    text = f"""# FAANG+ financial-report PDF collection

Snapshot: **{summary["as_of"]}**. Fiscal years **2022–2026**, where available.

**{len(rows):,} PDFs · {totals["pages"]:,} pages · {totals["bytes"]:,} bytes ({totals["bytes"] / 1e9:.3f} GB / {totals["bytes"] / 1024**3:.3f} GiB).**

This README describes the complete Bronze archive. See [`data/AGENTS.md`](../AGENTS.md) for the source-data contract and [`data/active_manifest.csv`](../active_manifest.csv) for the pinned 100-document retrieval corpus.

## Scope

15 companies: FAANG (Meta, Apple, Amazon, Netflix, Alphabet), plus Microsoft, NVIDIA, Tesla, Uber, AMD, Intel, Adobe, Salesforce, Oracle and Airbnb. This is a practical technology-company selection, not the membership of a particular FAANG+ index or a Fortune 100 ranking.

Includes **{len(annual)} annual reports / Forms 10-K covering {len(annual_periods)} company-years**, plus **{len(rows) - len(annual)} quarterly filings, earnings releases, shareholder letters, presentations, financial tables and earnings-call materials**. Counts are PDF files, not distinct reporting periods. Alphabet has both an annual-report edition and a standalone 10-K for some years; these overlap in content but are distinct PDFs. Annual filings can contain exhibits. Original PDF bytes are preserved; no HTML or Office documents were converted to PDF.

Fiscal-year labels follow the issuer, not the publication date. For example, NVIDIA FY2026 ended January 25, 2026. Calendar-2026 publications labelled FY2027 are outside the requested fiscal-year range. A 2026 proxy does not count as a FY2026 annual financial report.

## Company totals

| Company | PDFs | Pages | MB (decimal) | Annual fiscal years downloaded |
|---|---:|---:|---:|---|
{chr(10).join(company_lines)}

## Fiscal-year totals

| Fiscal year | PDFs | Pages | MB (decimal) |
|---|---:|---:|---:|
{chr(10).join(year_lines)}

Mean length: **{summary["mean_pages"]:.1f} pages**; median: **{summary["median_pages"]:g} pages**. PDF totals exclude metadata, manifests and documentation. GB/MB are decimal; GiB/MiB are binary.

{size_extremes}

## Coverage and availability

{historical_coverage} FY2026 annual reports are included for companies whose reports were located and validated. FY2026 annual-report PDFs were not found in the checked sources for: **{missing}**. This does not mean that all FY2026 reports are unpublished; consult the recorded source archives for updates. Partial FY2026 quarterly reporting is included.

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
- `_metadata/failed_downloads.json`: unresolved download failures ({len(failures)}).

All retained PDFs were downloaded from company investor-relations sites or their linked document hosts/CDNs. Source URLs and resolved download URLs are recorded separately. Failed AnnualReports.com mirror attempts remain only in acquisition history; none are counted in the retained collection. `_metadata/source_overrides.json` records replacement official links.

## Validation and reproduction

Every retained file passed a PDF-header check, full SHA-256 and byte-size check, pypdf page-tree parsing, and an independent Poppler `pdfinfo` page-count check. There are **{summary["unique_sha256"]} distinct SHA-256 hashes**. Text sampling is a format/content sanity check, not a full transcription or a financial-data accuracy audit.

Install Python, `pypdf[crypto]`, curl and Poppler (`pdfinfo`), then run from the project root:

```sh
python scripts/download_reports.py
python scripts/audit_reports.py
```

Downloads resume from existing PDFs. Re-running downloads fetches the recorded URLs; it does not automatically discover newly published periods.
"""
    (ROOT / "README.md").write_text(text)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
