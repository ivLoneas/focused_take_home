# Big-tech quarterly earnings documents

Downloaded earnings materials for 15 companies, covering fiscal years 2021–2026 as available on 30 October 2026.

The dataset is in [`data/raw`](data/raw), organized as `<company>/<fiscal-year>/Q<quarter>/`.
See the [dataset README](data/raw/README.md) for company totals, scope, source notes, file formats, validation, and reproduction commands.

- [Source manifest and checksums](data/raw/manifest.csv)
- [Quarter-by-quarter coverage](data/raw/coverage.csv)
- [Machine-readable size summary](data/raw/summary.json)

The resumable downloader is `scripts/download_earnings.py`; the integrity audit is `scripts/audit_earnings.py`.
