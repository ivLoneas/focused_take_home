"""Run Bronze → Silver → Gold and emit a machine-readable spend/progress report."""

import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from etl.embeddings import DIMENSIONS, MODEL, embedding_text
from etl.gold import USD_PER_MILLION_TOKENS, cached_embeddings, cached_usage
from etl.manifest import load_manifest
from etl.parsing import build_converter, parser_config
from etl.pictures import (
    DETAIL as PICTURE_DETAIL,
)
from etl.pictures import (
    INPUT_USD_PER_MILLION_TOKENS as PICTURE_INPUT_PRICE,
)
from etl.pictures import (
    MODEL as PICTURE_MODEL,
)
from etl.pictures import (
    OUTPUT_USD_PER_MILLION_TOKENS as PICTURE_OUTPUT_PRICE,
)
from etl.pictures import (
    empty_usage as empty_picture_usage,
)
from etl.pipeline import prepare_document, read_chunks
from etl.store import initialize, is_current, reconcile_documents, replace_document
from utils import financial_report_sort_key, read_json, sha256_json, sha256_text, write_json


def _generation(source, chunks, texts) -> str:
    return sha256_json(
        {
            "source": asdict(source),
            "chunk_ids": [chunk.chunk_id for chunk in chunks],
            "embedding_text_sha256": sha256_text("\0".join(texts)),
            "model": MODEL,
            "dimensions": DIMENSIONS,
        },
        compact=False,
    )


def _select_sources(sources, company, per_company_limit, limit, keep):
    if keep not in {"oldest", "newest"}:
        raise ValueError("keep must be 'oldest' or 'newest'")
    if per_company_limit is not None and per_company_limit <= 0:
        raise ValueError("per_company_limit must be positive")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")

    requested = None
    if company:
        requested = sorted({company} if isinstance(company, str) else set(company))
        available = {source.company for source in sources}
        missing = sorted(set(requested) - available)
        if missing:
            raise ValueError(f"Unknown requested companies: {', '.join(missing)}")
        sources = sorted(
            (source for source in sources if source.company in requested),
            key=financial_report_sort_key,
        )
    elif per_company_limit is not None:
        raise ValueError("per_company_limit requires at least one company")

    if per_company_limit is not None:
        grouped = {name: [] for name in requested or []}
        for source in sources:
            grouped[source.company].append(source)
        sources = []
        for name in sorted(grouped):
            group = grouped[name]
            sources.extend(group[-per_company_limit:] if keep == "newest" else group[:per_company_limit])
    if limit is not None:
        sources = sources[:limit]
    return sources, requested


def run(
    raw_dir: Path,
    silver_dir: Path,
    cache_dir: Path,
    report_path: Path,
    database_url: str,
    openai_client,
    *,
    manifest_path: Path | None = None,
    pictures: bool = True,
    max_chars: int = 1000,
    overlap: int = 200,
    company: str | list[str] | tuple[str, ...] | None = None,
    per_company_limit: int | None = None,
    keep: str = "oldest",
    limit: int | None = None,
    parse_only: bool = False,
    fail_fast: bool = False,
) -> dict:
    """Run selected reports through Silver and Gold while publishing per-document progress."""

    sources = (
        load_manifest(raw_dir, manifest_path=manifest_path) if manifest_path is not None else load_manifest(raw_dir)
    )
    sources, companies = _select_sources(sources, company, per_company_limit, limit, keep)
    if not sources:
        raise ValueError("No source documents match the requested filters")

    started = datetime.now(UTC)
    report = {
        "status": "running",
        "started_at": started.isoformat(),
        "finished_at": None,
        "duration_seconds": 0.0,
        "selection": {
            "manifest": str(manifest_path if manifest_path is not None else raw_dir / "manifest.csv"),
            "companies": companies,
            "per_company_limit": per_company_limit,
            "keep": keep,
            "limit": limit,
            "documents": len(sources),
        },
        "configuration": {
            "pictures": pictures,
            "max_chars": max_chars,
            "overlap": overlap,
            "embedding_model": MODEL,
            "embedding_dimensions": DIMENSIONS,
            "embedding_price_usd_per_million_tokens": USD_PER_MILLION_TOKENS,
            "picture_model": PICTURE_MODEL if pictures else None,
            "picture_detail": PICTURE_DETAIL if pictures else None,
            "picture_input_price_usd_per_million_tokens": PICTURE_INPUT_PRICE if pictures else None,
            "picture_output_price_usd_per_million_tokens": PICTURE_OUTPUT_PRICE if pictures else None,
        },
        "totals": {
            "documents_succeeded": 0,
            "documents_failed": 0,
            "documents_pruned": 0,
            "chunks": 0,
            "prompt_tokens": 0,
            "total_tokens": 0,
            "api_calls": 0,
            "picture_input_tokens": 0,
            "picture_output_tokens": 0,
            "picture_total_tokens": 0,
            "picture_api_calls": 0,
            "picture_cost_usd": 0.0,
            "cost_usd": 0.0,
        },
        "documents": [],
    }
    write_json(report_path, report)
    converter = build_converter(pictures=pictures)
    config = parser_config(pictures=pictures)

    connection = None
    if not parse_only:
        # Autocommit keeps setup and read checks outside per-document publication transactions.
        connection = psycopg.connect(database_url, autocommit=True)
        initialize(connection)
    try:
        for position, source in enumerate(sources, start=1):
            item_started = time.monotonic()
            item = {
                "document_id": source.document_id,
                "path": source.path,
                "position": position,
                "status": "running",
                "chunks": 0,
                "silver_reused": False,
                "gold_reused": False,
                "prompt_tokens": 0,
                "api_calls": 0,
                "picture_input_tokens": 0,
                "picture_output_tokens": 0,
                "picture_total_tokens": 0,
                "picture_api_calls": 0,
                "picture_cost_usd": 0.0,
                "cost_usd": 0.0,
            }
            report["documents"].append(item)
            write_json(report_path, report)
            try:
                picture_arguments = (
                    {"picture_client": openai_client, "picture_cache_dir": cache_dir / "pictures"}
                    if pictures
                    else {}
                )
                artifact_dir, silver_reused = prepare_document(
                    source,
                    raw_dir,
                    silver_dir,
                    converter,
                    config,
                    max_chars,
                    overlap,
                    **picture_arguments,
                )
                picture_usage = (
                    read_json(artifact_dir / "metadata.json").get("picture_usage", empty_picture_usage())
                    if pictures
                    else empty_picture_usage()
                )
                for usage_key, report_key in (
                    ("input_tokens", "picture_input_tokens"),
                    ("output_tokens", "picture_output_tokens"),
                    ("total_tokens", "picture_total_tokens"),
                    ("api_calls", "picture_api_calls"),
                    ("cost_usd", "picture_cost_usd"),
                ):
                    item[report_key] = picture_usage[usage_key]
                    report["totals"][report_key] += picture_usage[usage_key]
                item["cost_usd"] += picture_usage["cost_usd"]
                report["totals"]["cost_usd"] += picture_usage["cost_usd"]
                chunks = read_chunks(artifact_dir / "chunks.json")
                item["chunks"] = len(chunks)
                item["silver_reused"] = silver_reused
                report["totals"]["chunks"] += len(chunks)
                if not parse_only:
                    texts = [embedding_text(source, chunk) for chunk in chunks]
                    generation = _generation(source, chunks, texts)
                    item["gold_reused"] = is_current(connection, source.document_id, generation, len(chunks))
                    document_cache = cache_dir / source.document_id
                    vectors = cached_embeddings(openai_client, texts, document_cache)
                    usage = cached_usage(texts, document_cache)
                    if not item["gold_reused"]:
                        replace_document(connection, source, chunks, texts, vectors, generation)
                    for key in ("prompt_tokens", "api_calls"):
                        item[key] = usage[key]
                        report["totals"][key] += usage[key]
                    item["cost_usd"] += usage["cost_usd"]
                    report["totals"]["cost_usd"] += usage["cost_usd"]
                    report["totals"]["total_tokens"] += usage["total_tokens"]
                item["status"] = "succeeded"
                report["totals"]["documents_succeeded"] += 1
            except Exception as error:
                item["status"] = "failed"
                item["error"] = f"{type(error).__name__}: {error}"
                report["totals"]["documents_failed"] += 1
                if fail_fast:
                    raise
            finally:
                item["duration_seconds"] = round(time.monotonic() - item_started, 3)
                report["duration_seconds"] = round((datetime.now(UTC) - started).total_seconds(), 3)
                write_json(report_path, report)
        if connection is not None and report["totals"]["documents_failed"] == 0:
            report["totals"]["documents_pruned"] = reconcile_documents(
                connection,
                [source.document_id for source in sources],
            )
            write_json(report_path, report)
    finally:
        if connection is not None:
            connection.close()
    report["status"] = "complete" if report["totals"]["documents_failed"] == 0 else "complete_with_errors"
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["duration_seconds"] = round((datetime.now(UTC) - started).total_seconds(), 3)
    report["totals"]["cost_usd"] = round(report["totals"]["cost_usd"], 8)
    report["totals"]["picture_cost_usd"] = round(report["totals"]["picture_cost_usd"], 8)
    write_json(report_path, report)
    return report
