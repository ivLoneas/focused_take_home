# Quarterly technology-company earnings collection

Snapshot date: **30 October 2026**.

**1,129 original documents; 1,821,882,056 bytes (1.822 GB / 1.697 GiB); 346 company-quarters across 15 companies.**

## Scope and dates

FAANG (Meta/Facebook, Apple, Amazon, Netflix, Alphabet/Google), plus Microsoft, NVIDIA, Tesla, Uber, AMD, Intel, Adobe, Salesforce, Oracle, and Airbnb.

Folders use each company's **fiscal year and fiscal quarter**, for fiscal years 2021–2026. Fiscal and calendar years differ for several companies: a fiscal 2021 quarter may have ended in calendar 2020. Fiscal 2027 results are outside this collection, even when published in calendar 2026. Q4/full-year earnings releases are included. Only reports already published by the snapshot date are available.

The collection contains earnings releases/shareholder letters, financial statements/tables, presentations, prepared remarks, transcripts, and regulatory filings linked from quarterly earnings archives. It preserves the downloaded bytes; HTML is saved as HTML rather than converted to PDF. Audio, video, webcast landing pages, and unrelated proxy statements are excluded. PDFs are preferred when the archive also links a redundant HTML earnings release or filing.

## Company totals

| Company | Reported quarters | Documents | MB (decimal) |
|---|---:|---:|---:|
| adobe | 23 | 23 | 3.42 |
| airbnb | 22 | 66 | 188.19 |
| alphabet | 23 | 51 | 34.64 |
| amazon | 23 | 69 | 30.86 |
| amd | 22 | 88 | 52.32 |
| apple | 23 | 69 | 81.43 |
| intel | 23 | 95 | 134.05 |
| meta | 23 | 118 | 63.78 |
| microsoft | 24 | 28 | 17.60 |
| netflix | 23 | 69 | 24.76 |
| nvidia | 24 | 125 | 191.47 |
| oracle | 24 | 120 | 111.45 |
| salesforce | 24 | 96 | 449.89 |
| tesla | 23 | 23 | 171.11 |
| uber | 22 | 89 | 266.92 |

## File formats

- DOCX: 2
- HTML: 128
- PDF: 918
- PPTX: 1
- XLSX: 80

PDFs contain **28,564 pages** in total.

## Layout and provenance

```text
data/raw/
  <company>/<fiscal-year>/Q<quarter>/<document>.<format>
  manifest.csv
  coverage.csv
  summary.json
  _metadata/
```

- `manifest.csv`: document roles, relative paths, sizes, SHA-256 hashes, download URLs, original archive URLs, and retrieval times.
- `coverage.csv`: all 360 requested company/year/quarter combinations, with downloaded and not-yet-available states.
- `summary.json`: exact totals and breakdowns. Report sizes exclude indexes, metadata, and this README.
- `_metadata/`: original archive/API snapshots, discovery candidates, acquisition log, rejected attempts, exclusions, and validation results.

Alphabet's four 2021 earnings PDFs are original Alphabet releases mirrored in Google's public `cloud-samples-data` bucket. The original Alphabet URLs now redirect to the new site, and direct SEC retrieval rejected access. The original SEC exhibit URLs and mirror notes are recorded in the manifest. All four PDFs were checked for the correct quarter and year.

Meta's JavaScript filing viewers were resolved through its public filing index to the underlying filing PDFs. One Salesforce FY2025 Q4 archive link points to the same 10-Q as FY2026 Q3; the mislinked FY2025 Q4 copy is excluded. Original fiscal-quarter associations otherwise follow the companies' own earnings archives.

Rejected network responses and source links remain in the acquisition log for reproducibility; they are not counted as documents. Some rejected attempts were superseded by working alternate links. These counts do not represent missing earnings quarters.

## Validation

All 1,129 retained files passed SHA-256 and size verification. PDFs were opened and their page trees read; Office ZIP packages were checked for corruption. Earnings reports were checked for financial text. HTML challenge/error pages and non-PDF responses from PDF URLs were rejected.

Unreleased quarters: 14. Missing published quarters: 0.

## Re-run

From the project root:

```sh
uv run --with beautifulsoup4 scripts/download_earnings.py --probe
uv run --with beautifulsoup4 scripts/download_earnings.py --discover
uv run --with beautifulsoup4 scripts/download_earnings.py --resolve-filings
uv run --with beautifulsoup4 scripts/download_earnings.py --collect
uv run --with beautifulsoup4 --with 'pypdf[crypto]' scripts/audit_earnings.py
```

The supplemental candidate file preserves manually researched Tesla/Adobe links and Alphabet mirror links. Downloads are resumable; existing successful records are skipped. The audit removes only files previously created by this downloader that have become superseded or excluded by the selection rules.

## Official archives

- [meta](https://investor.atmeta.com/financials/default.aspx)
- [apple](https://investor.apple.com/investor-relations/)
- [amazon](https://ir.aboutamazon.com/quarterly-results/default.aspx)
- [netflix](https://ir.netflix.net/financials/quarterly-earnings/default.aspx)
- [alphabet](https://abc.xyz/investor/earnings/)
- [microsoft](https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q4/press-release-webcast)
- [nvidia](https://investor.nvidia.com/financial-info/quarterly-results-and-annual-reports/default.aspx)
- [uber](https://investor.uber.com/financials/default.aspx)
- [amd](https://ir.amd.com/financial-information/financial-results)
- [intel](https://www.intc.com/financial-info/financial-results)
- [adobe](https://www.adobe.com/investor-relations/financial-documents.html)
- [salesforce](https://investor.salesforce.com/financials/default.aspx)
- [oracle](https://investor.oracle.com/financial-reporting/quarterly-reports/default.aspx)
- [airbnb](https://investors.airbnb.com/financials/default.aspx)
- [tesla](https://ir.tesla.com/)
