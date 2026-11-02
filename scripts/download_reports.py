"""Resume public PDF downloads and record independently measured file metadata.

Run with Python and pypdf installed. Source candidates are versioned separately.
"""

import argparse
import csv
import json
import logging
import re
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

from utils import read_json, sha256_bytes, write_json

ROOT = Path(__file__).resolve().parents[1] / "data" / "raw"
META = ROOT / "_metadata"
logging.getLogger("pypdf").setLevel(logging.ERROR)


def acquire(row, cached=None):
    """Reuse verified files or retry download, PDF validation, and metadata extraction."""

    row = dict(row)
    if "annual report" in row["title"].lower():
        row["report_type"] = "annual_report"
    path = ROOT / row["path"]
    if not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Unsafe destination path")
    path.parent.mkdir(parents=True, exist_ok=True)
    if cached and cached["status"] == "downloaded" and cached["url"] == row["url"] and path.exists():
        data = path.read_bytes()
        if sha256_bytes(data) == cached["sha256"]:
            cached = dict(cached)
            if row.get("report_type") == "annual_report":
                cached["report_type"] = "annual_report"
            return cached, cached.pop("text_sample", "")
    previous_hash = row.get("sha256", "")
    for attempt in range(3):
        try:
            if path.exists():
                data = path.read_bytes()
            else:
                temporary = path.with_suffix(".part")
                try:
                    response = subprocess.run(
                        [
                            "curl",
                            "-s",
                            "-S",
                            "-f",
                            "-L",
                            "--max-time",
                            "60",
                            "-o",
                            str(temporary),
                            "-w",
                            "%{url_effective}",
                            row["url"],
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    data = temporary.read_bytes()
                    row["final_url"] = response.stdout
                except subprocess.CalledProcessError:
                    with urllib.request.urlopen(row["url"], timeout=60) as response:
                        data = response.read()
                        row["final_url"] = response.url
                    temporary.write_bytes(data)
                if not data.startswith(b"%PDF-"):
                    raise ValueError("Response is not a PDF")
                reader = PdfReader(temporary)
                if not len(reader.pages):
                    raise ValueError("PDF has no pages")
                temporary.replace(path)
            reader = PdfReader(path)
            pages = len(reader.pages)
            sample = "\n".join(reader.pages[i].extract_text() or "" for i in range(min(pages, 3)))
            digest = sha256_bytes(data)
            row.update(
                bytes=len(data),
                pages=pages,
                sha256=digest,
                retrieved_at=datetime.now(UTC).isoformat(),
                previous_hash_matches=(digest == previous_hash) if previous_hash else "",
                sample_text_characters=len(sample),
                report_type="annual_report"
                if row.get("report_type") == "annual_report"
                or (
                    row["role"] == "regulatory_filing"
                    and row["quarter"] == "4"
                    and re.search(r"FORM\s+10[–—-]?K", sample, re.IGNORECASE)
                )
                else row["role"],
                status="downloaded",
            )
            return row, sample[:12000]
        except Exception as exc:  # noqa: BLE001 - retry any download, parse, or validation failure
            if attempt == 2:
                path.with_suffix(".part").unlink(missing_ok=True)
                row.update(status="failed", error=str(exc))
                return row, ""
            time.sleep(attempt + 1)


def main():
    """Resume candidate downloads in parallel and publish the acquisition ledger."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    candidates = [
        r
        for r in csv.DictReader((META / "previous_inventory" / "manifest.csv").open())
        if r["format"] == "pdf" and 2022 <= int(r["fiscal_year"]) <= 2026
    ]
    extra = META / "annual_candidates.json"
    if extra.exists():
        candidates.extend(read_json(extra))
    overrides = META / "source_overrides.json"
    if overrides.exists():
        replacements = read_json(overrides)
        for row in candidates:
            if row["path"] in replacements:
                row.update(replacements[row["path"]])
    cache = {}
    if (META / "acquisition.jsonl").exists():
        for line in (META / "acquisition.jsonl").read_text().splitlines():
            item = json.loads(line)
            cache[item["path"]] = item
    results = []
    with (META / "acquisition.jsonl").open("w") as log, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(acquire, r, cache.get(r["path"])) for r in candidates]
        for i, future in enumerate(as_completed(futures), 1):
            row, sample = future.result()
            results.append(row)
            log.write(json.dumps({**row, "text_sample": sample}) + "\n")
            log.flush()
            if i % 25 == 0 or row["status"] != "downloaded" or i == len(candidates):
                print(
                    f"{i}/{len(candidates)} {row['company']} {row['fiscal_year']} {row['status']} {row.get('error', '')}",
                    flush=True,
                )
    results.sort(key=lambda r: (r["company"], int(r["fiscal_year"]), str(r["quarter"]), r["path"]))
    write_json(META / "download_results.json", results)
    print(
        json.dumps(
            {
                "downloaded": sum(r["status"] == "downloaded" for r in results),
                "failed": sum(r["status"] != "downloaded" for r in results),
            }
        )
    )


if __name__ == "__main__":
    main()
