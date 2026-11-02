"""Pin the newest 20 reports per FAANG company from the audited Bronze inventory."""

import csv
from collections import Counter
from pathlib import Path
from typing import cast

from utils import financial_report_sort_key, write_csv

ROOT = Path(__file__).resolve().parents[1]
RAW_MANIFEST = ROOT / "data" / "raw" / "manifest.csv"
ACTIVE_MANIFEST = ROOT / "data" / "active_manifest.csv"
COMPANIES = ("alphabet", "amazon", "apple", "meta", "netflix")
PER_COMPANY = 20


def main() -> None:
    """Select the newest bounded corpus per company and publish it atomically."""

    with RAW_MANIFEST.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = cast(list[dict[str, str]], list(reader))
    if not fields:
        raise ValueError("Raw manifest has no header")

    selected: list[dict[str, str]] = []
    for company in COMPANIES:
        company_rows = sorted((row for row in rows if row["company"] == company), key=financial_report_sort_key)
        if len(company_rows) < PER_COMPANY:
            raise ValueError(f"{company} has only {len(company_rows)} reports")
        selected.extend(company_rows[-PER_COMPANY:])
    selected.sort(key=financial_report_sort_key)

    counts = Counter(row["company"] for row in selected)
    if len(selected) != 100 or counts != Counter({company: PER_COMPANY for company in COMPANIES}):
        raise ValueError(f"Invalid active selection: {counts}")

    write_csv(ACTIVE_MANIFEST, selected, fieldnames=fields, quoting=csv.QUOTE_ALL)
    print(
        f"Wrote {len(selected)} documents / {sum(int(row['pages']) for row in selected):,} pages "
        f"to {ACTIVE_MANIFEST.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
