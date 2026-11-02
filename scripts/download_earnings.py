#!/usr/bin/env python3
"""Download original quarterly earnings documents and preserve their provenance."""
from __future__ import annotations

import argparse
import concurrent.futures
import collections
import csv
import datetime as dt
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import io
import zipfile
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
META = RAW / "_metadata"
SOURCES = {
    "meta": "https://investor.atmeta.com/financials/default.aspx",
    "apple": "https://investor.apple.com/investor-relations/",
    "amazon": "https://ir.aboutamazon.com/quarterly-results/default.aspx",
    "netflix": "https://ir.netflix.net/financials/quarterly-earnings/default.aspx",
    "alphabet": "https://abc.xyz/investor/earnings/",
    "microsoft": "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q4/press-release-webcast",
    "nvidia": "https://investor.nvidia.com/financial-info/quarterly-results-and-annual-reports/default.aspx",
    "uber": "https://investor.uber.com/financials/default.aspx",
    "amd": "https://ir.amd.com/financial-information/financial-results",
    "intel": "https://www.intc.com/financial-info/financial-results",
    "adobe": "https://www.adobe.com/investor-relations/financial-documents.html",
    "salesforce": "https://investor.salesforce.com/financials/default.aspx",
    "oracle": "https://investor.oracle.com/financial-reporting/quarterly-reports/default.aspx",
    "airbnb": "https://investors.airbnb.com/financials/default.aspx",
    "tesla": "https://ir.tesla.com/",
}
QUARTERS = {"First Quarter": 1, "Second Quarter": 2, "Third Quarter": 3, "Fourth Quarter": 4}


def candidate(company, year, quarter, title, url, source_url, **extra):
    return dict(company=company, fiscal_year=int(year), quarter=int(quarter), title=title,
                url=urllib.parse.urljoin(source_url, html.unescape(url)), source_url=source_url, **extra)


def discover_q4(company):
    base = SOURCES[company]
    endpoint = urllib.parse.urljoin(base, "/feed/FinancialReport.svc/GetFinancialReportList")
    params = dict(LanguageId=1, reportTypes="|".join(QUARTERS), year=-1,
                  pageSize=-1, pageNumber=0, includeTags="true", excludeSelection=1)
    url = endpoint + "?" + urllib.parse.urlencode(params)
    data, _, _ = fetch(url)
    (META / f"{company}_financial_reports.json").write_bytes(data)
    reports = json.loads(data)["GetFinancialReportListResult"]
    found = []
    for report in reports:
        year, quarter = report.get("ReportYear"), QUARTERS.get(report.get("ReportSubType"))
        if not quarter or not year or not 2021 <= int(year) <= 2026:
            continue
        for doc in report.get("Documents", []):
            url = doc.get("DocumentPath", "")
            title = doc.get("DocumentTitle", "")
            if not url or re.search(r"webcast|youtube|mp3|mp4", url, re.I):
                continue
            found.append(candidate(company, year, quarter, title, url, base,
                                   report_date=report.get("ReportDate", ""),
                                   category=doc.get("DocumentCategory", "")))
    return found


def discover_equity(company):
    base = SOURCES[company]
    soup = BeautifulSoup((META / f"{company}_archive.html").read_bytes(), "html.parser")
    found = []
    for info in soup.select(".results-info"):
        text = info.get_text(" ", strip=True)
        y = re.search(r"20\d{2}", text)
        q = re.search(r"\bQ([1-4])\b", text)
        if not y or not 2021 <= int(y[0]) <= 2026:
            continue
        quarter = int(q[1]) if q else 4
        block = info.parent
        for a in block.select("a[href]"):
            url = a["href"]
            title = a.get("aria-label") or a.get("title") or a.get_text(" ", strip=True)
            if not re.search(r"\.(pdf|xlsx?|docx?|pptx?)(?:$|\?)|press-releases/detail", url, re.I):
                continue
            # Earnings releases and their supporting documents; omit annual/SEC/XBRL bundles.
            if re.search(r"sec-filings|all-sec-filings|stockpr.com/sec|annual_report", url):
                continue
            found.append(candidate(company, y[0], quarter, title, url, base))
    return found


def discover():
    META.mkdir(parents=True, exist_ok=True)
    jobs = [(c, discover_q4) for c in ["meta", "apple", "amazon", "netflix", "alphabet", "nvidia", "uber", "salesforce", "oracle", "airbnb"]]
    jobs += [(c, discover_equity) for c in ["amd", "intel"]]
    def one(job):
        company, fn = job
        try:
            found = fn(company)
            print(f"{company}: {len(found)} documents, {len(set((x['fiscal_year'],x['quarter']) for x in found))} quarters", flush=True)
            return found
        except Exception as exc:
            print(f"{company}: ERROR {exc}", flush=True)
            return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        found = [x for group in pool.map(one, jobs) for x in group]
    # Microsoft keeps stable, individually addressable quarterly earnings pages.
    for year in range(2021, 2027):
        for quarter in range(1, 5):
            found.append(candidate("microsoft", year, quarter, "Earnings release",
                f"https://www.microsoft.com/en-us/Investor/earnings/FY-{year}-Q{quarter}/press-release-webcast", SOURCES["microsoft"]))
    unique = {(x["company"], x["fiscal_year"], x["quarter"], x["url"]): x for x in found}
    (META / "candidates.json").write_text(json.dumps(list(unique.values()), indent=2) + "\n")
    print(f"TOTAL {len(unique)} document candidates", flush=True)


def role(item):
    title = item["title"].lower()
    category = item.get("category", "").lower()
    if category in ("news", "news-pdf", "letter", "earnings release") or re.search(
        r"earnings release|press release|letter to shareholders|shareholder letter|quarterly shareholder update|reports.*quarter.*(?:results|financial)", title
    ) or "/earnings_release/" in item["url"]:
        return "earnings_report"
    if re.search(r"10.?[qk]|ten[ qk]", category + " " + title):
        return "regulatory_filing"
    return "supporting_document"


def selected_candidates():
    items = json.loads((META / "candidates.json").read_text())
    items += json.loads((META / "supplemental_candidates.json").read_text())
    unique = {}
    for item in items:
        url, title = item["url"], item["title"]
        if re.search(r"proxy statement|proxy materials", title, re.I):
            continue
        # The source archive mistakenly links FY2026 Q3's 10-Q under FY2025 Q4.
        if (item["company"], item["fiscal_year"], item["quarter"]) == ("salesforce",2025,4) and "63299f7c-f24e-44a2-9abf-4a1574c8883e" in url:
            continue
        if re.search(r"webcast|earnings call replay", title, re.I) or re.search(
            r"events\.q4inc|media-server|youtube|youtu\.be|/events/event|event\.webcasts|\.mp[34](?:$|\?)", url, re.I):
            continue
        item["url"] = re.sub(r"^http:", "https:", url).split("#")[0].rstrip("/")
        item["role"] = role(item)
        unique[(item["company"], item["fiscal_year"], item["quarter"], item["url"])] = item
    items = list(unique.values())
    # Prefer a PDF release/filing to a redundant HTML rendering of the same report.
    pdf_roles = {(i["company"], i["fiscal_year"], i["quarter"], i["role"]) for i in items
                 if re.search(r"\.pdf(?:$|\?)", i["url"], re.I)}
    return [i for i in items if not (i["role"] in ("earnings_report", "regulatory_filing")
            and (i["company"], i["fiscal_year"], i["quarter"], i["role"]) in pdf_roles
            and not re.search(r"\.pdf(?:$|\?)", i["url"], re.I)
            and i["company"] != "tesla")]


def validate(data, url, content_type):
    suffix = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).suffix.lower()
    if data.startswith(b"%PDF-"):
        if b"%%EOF" not in data[-4096:]:
            raise ValueError("Truncated PDF: missing end-of-file marker")
        return ".pdf"
    if suffix == ".pdf" or "application/pdf" in content_type:
        raise ValueError("PDF URL returned non-PDF content")
    if data.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            for folder, ext in [("xl/", ".xlsx"), ("word/", ".docx"), ("ppt/", ".pptx")]:
                if any(n.startswith(folder) for n in names):
                    return ext
        return ".zip"
    if data.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        return suffix if suffix in (".xls", ".doc", ".ppt") else ".xls"
    if suffix in (".xlsx", ".docx", ".pptx", ".xls", ".doc", ".ppt"):
        raise ValueError("Office document URL returned non-Office content")
    soup = BeautifulSoup(data, "html.parser")
    for node in soup(["script", "style", "nav", "header", "footer"]):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    if re.search(r"attention required|access denied|just a moment|request unsuccessful", text[:1000], re.I):
        raise ValueError("Access/error page returned")
    if len(text) < 1000 or not re.search(r"revenue|net income|financial results|earnings per share", text, re.I):
        raise ValueError("HTML does not contain substantive financial report content")
    return ".html"


def download_one(item):
    start = time.time()
    record = dict(item)
    try:
        data, final_url, content_type = fetch(item["url"])
        ext = validate(data, final_url, content_type)
        title = re.sub(r"[^a-z0-9]+", "-", item["title"].lower()).strip("-")[:65] or "report"
        token = hashlib.sha256(item["url"].encode()).hexdigest()[:10]
        relative = Path(item["company"]) / str(item["fiscal_year"]) / f"Q{item['quarter']}" / f"{title}--{token}{ext}"
        path = RAW / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        record.update(status="downloaded", path=str(relative), bytes=len(data),
                      sha256=hashlib.sha256(data).hexdigest(), final_url=final_url,
                      content_type=content_type, format=ext[1:],
                      retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat())
    except Exception as exc:
        record.update(status="failed", error=str(exc))
    record["elapsed_seconds"] = round(time.time()-start, 2)
    return record


def microsoft_attachments(records):
    extra = []
    for record in records:
        if record["company"] != "microsoft" or record.get("format") != "html" or record.get("role") != "earnings_report":
            continue
        soup = BeautifulSoup((RAW / record["path"]).read_bytes(), "html.parser")
        for a in soup.select("[href], [link]"):
            url = a.get("href") or a.get("link")
            if "view.officeapps.live.com" in url:
                url = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("src", [""])[0]
            if not re.search(r"\.(?:docx?|xlsx?|pptx?|pdf)(?:$|\?)", url, re.I):
                continue
            if not re.search(r"PressRelease|Slides|FinancialStatement|Transcript", url, re.I):
                continue
            year_q = f"FY{str(record['fiscal_year'])[-2:]}Q{record['quarter']}"
            if year_q.lower() not in url.lower():
                continue
            item = candidate("microsoft", record["fiscal_year"], record["quarter"],
                a.get_text(" ", strip=True) or Path(url).stem, url, record["url"], category="attachment")
            item["role"] = role(item)
            extra.append(item)
    return extra


def collect(retry_failed=False):
    log_path = META / "downloads.jsonl"
    existing = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
    latest = {(r["company"], r["fiscal_year"], r["quarter"], r["url"]): r for r in existing}
    candidates = selected_candidates()
    candidates += microsoft_attachments([r for r in latest.values() if r.get("status") == "downloaded"])
    def key(r): return r["company"], r["fiscal_year"], r["quarter"], r["url"]
    todo = {key(i): i for i in candidates if key(i) not in latest or
            (retry_failed and latest[key(i)]["status"] != "downloaded")}
    print(f"Downloading {len(todo)} documents; {sum(r['status']=='downloaded' for r in latest.values())} already saved", flush=True)
    with log_path.open("a") as log, concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(download_one, item) for item in todo.values()]
        for number, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            latest[key(result)] = result
            log.write(json.dumps(result) + "\n")
            log.flush()
            if number % 25 == 0 or result["status"] == "failed":
                print(f"{number}/{len(todo)} {result['company']} {result['fiscal_year']} Q{result['quarter']} {result['status']} {result.get('error','')}", flush=True)
    summarize(list(latest.values()))


def resolve_viewers():
    """Resolve JavaScript-only SEC viewer links to the original filing PDFs."""
    extra = json.loads((META / "supplemental_candidates.json").read_text())
    items = selected_candidates()
    for company, cik in [("meta", "0001326801"), ("airbnb", "0001559720")]:
        targets = {urllib.parse.parse_qs(urllib.parse.urlsplit(i["url"]).query)["FilingId"][0]: i
                   for i in items if i["company"] == company and "FilingId=" in i["url"]}
        if not targets:
            continue
        params = dict(LanguageId=1, exchange="CIK", symbol=cik, year=-1, pageSize=-1,
                      pageNumber=0, filingTypeList="10-Q,10-K", includeHtmlDocument="true")
        url = urllib.parse.urljoin(SOURCES[company], "/feed/SECFiling.svc/GetEdgarFilingList") + "?" + urllib.parse.urlencode(params)
        try:
            data, _, _ = fetch(url)
            (META / f"{company}_filings_index.json").write_bytes(data)
            filings = json.loads(data)["GetEdgarFilingListResult"]
            count = 0
            for filing in filings:
                target = targets.get(str(filing["FilingId"]))
                if not target:
                    continue
                docs = [d for d in filing.get("DocumentList", []) if d.get("DocumentType") == "CONVPDF"]
                if docs:
                    doc = dict(target, url=urllib.parse.urljoin(SOURCES[company], docs[0]["Url"]), source_url=target["url"])
                    extra.append(doc)
                    count += 1
            print(f"{company}: resolved {count} filing viewers", flush=True)
        except Exception as exc:
            print(f"{company}: filing resolution error: {exc}", flush=True)
    unique = {(x["company"],x["fiscal_year"],x["quarter"],x["url"]):x for x in extra}
    (META / "supplemental_candidates.json").write_text(json.dumps(list(unique.values()),indent=2)+"\n")


def summarize(records=None):
    if records is None:
        records = list({(r["company"], r["fiscal_year"], r["quarter"], r["url"]): r
            for r in [json.loads(line) for line in (META / "downloads.jsonl").read_text().splitlines()]}.values())
    # Classification can improve without downloading a document again.
    for r in records:
        r["role"] = role(r)
    good = [r for r in records if r["status"] == "downloaded"]
    fields = ["company", "fiscal_year", "quarter", "role", "title", "format", "path", "bytes", "sha256", "url", "final_url", "source_url", "retrieved_at", "mirror_note"]
    with (RAW / "manifest.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(good, key=lambda r: (r["company"],r["fiscal_year"],r["quarter"],r["path"])))
    coverage = []
    indexed_by_company = collections.defaultdict(list)
    for item in selected_candidates():
        indexed_by_company[item["company"]].append((item["fiscal_year"],item["quarter"]))
    for company in SOURCES:
        last_indexed = max(indexed_by_company[company])
        for year in range(2021,2027):
            for quarter in range(1,5):
                docs = [r for r in good if (r["company"],r["fiscal_year"],r["quarter"]) == (company,year,quarter)]
                core = [r for r in docs if r["role"] == "earnings_report"]
                missing_status = "not_yet_available" if (year,quarter) > last_indexed else "missing"
                coverage.append(dict(company=company,fiscal_year=year,quarter=quarter,
                    status="downloaded" if core else ("supporting_only" if docs else missing_status),
                    earnings_reports=len(core),documents=len(docs),bytes=sum(r["bytes"] for r in docs)))
    with (RAW / "coverage.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,list(coverage[0]));writer.writeheader();writer.writerows(coverage)
    (META / "failures.json").write_text(json.dumps([r for r in records if r["status"] != "downloaded"], indent=2)+"\n")
    summary = dict(as_of="2026-10-30", total_documents=len(good),total_bytes=sum(r["bytes"] for r in good),
        formats=dict(collections.Counter(r["format"] for r in good)),
        company_summaries=[dict(company=c,documents=sum(r["company"]==c for r in good),
            quarters=sum(x["company"]==c and x["status"]=="downloaded" for x in coverage),
            bytes=sum(r["bytes"] for r in good if r["company"]==c)) for c in sorted(SOURCES)],
        covered_quarters=sum(x["status"]=="downloaded" for x in coverage),
        not_yet_available_quarters=sum(x["status"]=="not_yet_available" for x in coverage),
        missing_quarters=[x for x in coverage if x["status"] in ("missing","supporting_only")],
        roles=dict(collections.Counter(r["role"] for r in good)),
        failed_download_attempts=sum(r["status"]=="failed" for r in records))
    (RAW / "summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)


def fetch(url: str) -> tuple[bytes, str, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; earnings-research/1.0)",
        "Accept": "text/html,application/pdf,application/json,*/*",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.read(), response.url, response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(url)


def probe() -> None:
    META.mkdir(parents=True, exist_ok=True)
    (META / "sources.json").write_text(json.dumps(SOURCES, indent=2) + "\n")
    def one(item):
        company, url = item
        try:
            data, final_url, content_type = fetch(url)
            (META / f"{company}_archive.html").write_bytes(data)
            return {"company": company, "bytes": len(data), "url": final_url, "type": content_type}
        except Exception as exc:
            return {"company": company, "error": str(exc)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(one, SOURCES.items()))
    for result in results:
        print(json.dumps(result), flush=True)
    (META / "probe.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument("--resolve-filings", action="store_true")
    args = parser.parse_args()
    if args.probe:
        probe()
    if args.discover:
        discover()
    if args.collect:
        collect(args.retry_failed)
    if args.summarize:
        summarize()
    if args.resolve_filings:
        resolve_viewers()
