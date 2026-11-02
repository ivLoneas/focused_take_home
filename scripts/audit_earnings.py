#!/usr/bin/env python3
"""Finalize this collection and verify its downloaded files and PDF structures."""
from __future__ import annotations

import collections
import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

from download_earnings import RAW, META, SOURCES, selected_candidates, microsoft_attachments, role, summarize

logging.getLogger("pypdf").setLevel(logging.ERROR)


def main():
    log_path = META / "downloads.jsonl"
    history = [json.loads(line) for line in log_path.read_text().splitlines()]
    def key(r): return r["company"],r["fiscal_year"],r["quarter"],r["url"]
    latest = {key(r):r for r in history}
    good = [r for r in latest.values() if r["status"]=="downloaded"]
    wanted = {key(r) for r in selected_candidates()+microsoft_attachments(good)}
    excluded_path = META / "excluded_documents.json"
    excluded = json.loads(excluded_path.read_text()) if excluded_path.exists() else []
    with log_path.open("a") as log:
        for record in good:
            if key(record) in wanted:
                continue
            updated = dict(record,status="excluded",reason="Duplicate HTML rendering superseded by PDF, unrelated proxy statement, or mislinked source filing")
            latest[key(record)] = updated
            log.write(json.dumps(updated)+"\n")
            excluded.append(updated)
            path = RAW / record["path"]
            if path.is_file():
                path.unlink()
    (META / "excluded_documents.json").write_text(json.dumps(excluded,indent=2)+"\n")
    records = list(latest.values())
    good = [r for r in records if r["status"]=="downloaded"]
    errors, observations, pdf_pages = [], [], 0
    document_audits = []
    for number, record in enumerate(good,1):
        path = RAW / record["path"]
        try:
            data = path.read_bytes()
            assert len(data)==record["bytes"], "File size mismatch"
            assert hashlib.sha256(data).hexdigest()==record["sha256"], "SHA-256 mismatch"
            audit = {"path":record["path"],"bytes":len(data),"sha256_verified":True}
            text = ""
            if record["format"]=="pdf":
                reader = PdfReader(path,strict=False)
                pages = len(reader.pages)
                assert pages>0,"Empty PDF"
                audit["pages"] = pages
                pdf_pages += pages
                if role(record)=="earnings_report":
                    text = " ".join(p.extract_text() or "" for p in reader.pages[:3])
            elif record["format"] in ("docx","xlsx","pptx"):
                with zipfile.ZipFile(path) as z:
                    assert z.testzip() is None,"Corrupt Office document"
                    if record["format"]=="docx":
                        text = " ".join(ET.fromstring(z.read("word/document.xml")).itertext())
            elif record["format"]=="html":
                soup = BeautifulSoup(data,"html.parser")
                for node in soup(["script","style"]):node.decompose()
                text = soup.get_text(" ",strip=True)
            if role(record)=="earnings_report":
                audit["financial_text_present"] = bool(re.search(r"revenue|net income|earnings per share|financial",text,re.I))
                if not audit["financial_text_present"]:
                    observations.append({"path":record["path"],"observation":"No financial keywords in first three PDF pages / HTML"})
                if record["company"]=="alphabet" and record["fiscal_year"]==2021:
                    expected = {1:"First",2:"Second",3:"Third",4:"Fourth"}[record["quarter"]]
                    assert re.search(expected+r"\s+Quarter(?:\s+and\s+Fiscal\s+Year)?\s+2021",text,re.I),"Alphabet 2021 quarter mismatch"
            document_audits.append(audit)
        except Exception as exc:
            errors.append({"path":record["path"],"error":str(exc)})
        if number%200==0:print(f"Verified {number}/{len(good)} files",flush=True)
    summary = dict(verified_documents=len(document_audits),pdf_pages=pdf_pages,errors=errors,
                   observations=observations,excluded_documents=len(excluded))
    (META / "validation.json").write_text(json.dumps(summary,indent=2)+"\n")
    (META / "document_validation.json").write_text(json.dumps(document_audits,indent=2)+"\n")
    summarize(records)
    report = json.loads((RAW / "summary.json").read_text())
    report["total_pdf_pages"] = pdf_pages
    report["total_gb"] = round(report["total_bytes"]/1e9,6)
    report["total_gib"] = round(report["total_bytes"]/1024**3,6)
    report["validation_errors"] = errors
    report["document_counts_exclude_metadata"] = True
    report["unique_content_documents"] = len({r["sha256"] for r in good})
    (RAW / "summary.json").write_text(json.dumps(report,indent=2)+"\n")
    write_readme(report,summary)
    # Repeat to include summary.json's own final serialized size in the directory total.
    for _ in range(3):
        report["raw_directory_total_bytes_including_metadata"] = sum(p.stat().st_size for p in RAW.rglob("*") if p.is_file())
        (RAW / "summary.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)
    if errors:
        raise SystemExit(1)


def write_readme(report,validation):
    lines = ["# Quarterly technology-company earnings collection", "", "Snapshot date: **30 October 2026**.", "",
        f"**{report['total_documents']:,} original documents; {report['total_bytes']:,} bytes "
        f"({report['total_gb']:.3f} GB / {report['total_gib']:.3f} GiB); "
        f"{report['covered_quarters']} company-quarters across 15 companies.**", "",
        "## Scope and dates", "",
        "FAANG (Meta/Facebook, Apple, Amazon, Netflix, Alphabet/Google), plus Microsoft, NVIDIA, Tesla, Uber, AMD, Intel, Adobe, Salesforce, Oracle, and Airbnb.", "",
        "Folders use each company's **fiscal year and fiscal quarter**, for fiscal years 2021–2026. "
        "Fiscal and calendar years differ for several companies: a fiscal 2021 quarter may have ended in calendar 2020. "
        "Fiscal 2027 results are outside this collection, even when published in calendar 2026. "
        "Q4/full-year earnings releases are included. Only reports already published by the snapshot date are available.", "",
        "The collection contains earnings releases/shareholder letters, financial statements/tables, presentations, "
        "prepared remarks, transcripts, and regulatory filings linked from quarterly earnings archives. "
        "It preserves the downloaded bytes; HTML is saved as HTML rather than converted to PDF. "
        "Audio, video, webcast landing pages, and unrelated proxy statements are excluded. "
        "PDFs are preferred when the archive also links a redundant HTML earnings release or filing.", "",
        "## Company totals", "", "| Company | Reported quarters | Documents | MB (decimal) |", "|---|---:|---:|---:|"]
    for row in report["company_summaries"]:
        lines.append(f"| {row['company']} | {row['quarters']} | {row['documents']} | {row['bytes']/1e6:.2f} |")
    lines += ["", "## File formats", ""]
    for fmt,count in sorted(report["formats"].items()):lines.append(f"- {fmt.upper()}: {count:,}")
    lines += ["",f"PDFs contain **{report['total_pdf_pages']:,} pages** in total.","",
        "## Layout and provenance", "", "```text", "data/raw/", "  <company>/<fiscal-year>/Q<quarter>/<document>.<format>",
        "  manifest.csv", "  coverage.csv", "  summary.json", "  _metadata/", "```", "",
        "- `manifest.csv`: document roles, relative paths, sizes, SHA-256 hashes, download URLs, original archive URLs, and retrieval times.",
        "- `coverage.csv`: all 360 requested company/year/quarter combinations, with downloaded and not-yet-available states.",
        "- `summary.json`: exact totals and breakdowns. Report sizes exclude indexes, metadata, and this README.",
        "- `_metadata/`: original archive/API snapshots, discovery candidates, acquisition log, rejected attempts, exclusions, and validation results.", "",
        "Alphabet's four 2021 earnings PDFs are original Alphabet releases mirrored in Google's public "
        "`cloud-samples-data` bucket. The original Alphabet URLs now redirect to the new site, and direct SEC retrieval rejected access. "
        "The original SEC exhibit URLs and mirror notes are recorded in the manifest. All four PDFs were checked for the correct quarter and year.","",
        "Meta's JavaScript filing viewers were resolved through its public filing index to the underlying filing PDFs. "
        "One Salesforce FY2025 Q4 archive link points to the same 10-Q as FY2026 Q3; the mislinked FY2025 Q4 copy is excluded. "
        "Original fiscal-quarter associations otherwise follow the companies' own earnings archives.","",
        "Rejected network responses and source links remain in the acquisition log for reproducibility; they are not counted as documents. "
        "Some rejected attempts were superseded by working alternate links. These counts do not represent missing earnings quarters.","",
        "## Validation", "",
        f"All {validation['verified_documents']:,} retained files passed SHA-256 and size verification. "
        "PDFs were opened and their page trees read; Office ZIP packages were checked for corruption. "
        "Earnings reports were checked for financial text. HTML challenge/error pages and non-PDF responses from PDF URLs were rejected.","",
        f"Unreleased quarters: {report['not_yet_available_quarters']}. Missing published quarters: {len(report['missing_quarters'])}.","",
        "## Re-run", "", "From the project root:", "", "```sh",
        "uv run --with beautifulsoup4 scripts/download_earnings.py --probe",
        "uv run --with beautifulsoup4 scripts/download_earnings.py --discover",
        "uv run --with beautifulsoup4 scripts/download_earnings.py --resolve-filings",
        "uv run --with beautifulsoup4 scripts/download_earnings.py --collect",
        "uv run --with beautifulsoup4 --with 'pypdf[crypto]' scripts/audit_earnings.py", "```", "",
        "The supplemental candidate file preserves manually researched Tesla/Adobe links and Alphabet mirror links. "
        "Downloads are resumable; existing successful records are skipped. The audit removes only files previously created by this downloader "
        "that have become superseded or excluded by the selection rules.", "", "## Official archives", ""]
    lines += [f"- [{company}]({url})" for company,url in SOURCES.items()]
    (RAW / "README.md").write_text("\n".join(lines)+"\n")


if __name__=="__main__":main()
