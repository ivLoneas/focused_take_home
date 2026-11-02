"""Command-line entry point for the Docker image and local development."""

import argparse
import json
from pathlib import Path

from etl.settings import Settings


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m etl")
    subcommands = result.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="process PDFs into Silver artifacts and PostgreSQL Gold")
    run.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    run.add_argument("--manifest", type=Path, default=Path("data/active_manifest.csv"),
                     help="source inventory; PDF paths remain relative to --raw-dir")
    run.add_argument("--silver-dir", type=Path, default=Path("data/silver"))
    run.add_argument("--cache-dir", type=Path, default=Path("data/gold/embedding_cache"))
    run.add_argument("--report", type=Path, default=Path("data/etl_runs/latest.json"))
    run.add_argument("--database-url", default=None)
    run.add_argument("--company", action="append", help="company to include; may be repeated")
    run.add_argument("--per-company-limit", type=int, help="cap the reports retained per company")
    run.add_argument("--keep", choices=("oldest", "newest"), default="oldest",
                     help="which reports survive a per-company cap")
    run.add_argument("--limit", type=int)
    run.add_argument("--max-chars", type=int, default=1000)
    run.add_argument("--overlap", type=int, default=200)
    run.add_argument("--no-pictures", action="store_true")
    run.add_argument("--parse-only", action="store_true")
    run.add_argument("--fail-fast", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = Settings()
    database_url = args.database_url or settings.database_url
    client = None
    if not args.parse_only or not args.no_pictures:
        if settings.openai_api_key is None:
            raise SystemExit("OPENAI_API_KEY is required for embeddings or picture descriptions")
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    from etl.runner import run
    report = run(
        args.raw_dir, args.silver_dir, args.cache_dir, args.report, database_url, client,
        manifest_path=args.manifest,
        pictures=not args.no_pictures, max_chars=args.max_chars, overlap=args.overlap,
        company=args.company, per_company_limit=args.per_company_limit, keep=args.keep, limit=args.limit,
        parse_only=args.parse_only, fail_fast=args.fail_fast,
    )
    print(json.dumps(report["totals"], indent=2))
    return 0 if report["totals"]["documents_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
