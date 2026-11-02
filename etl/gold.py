"""Restartable embedding batches with measured API usage and tamper detection."""

import json
from pathlib import Path
from typing import Any, cast

from etl.embeddings import DIMENSIONS, MODEL, validate_vector
from utils import read_json, sha256_json, write_json

CACHE_VERSION = 1
USD_PER_MILLION_TOKENS = 0.02


def _batch_key(texts: list[str]) -> str:
    return sha256_json(
        {
            "cache_version": CACHE_VERSION,
            "model": MODEL,
            "dimensions": DIMENSIONS,
            "texts": texts,
        }
    )


def _path(cache_dir: Path, texts: list[str]) -> Path:
    key = _batch_key(texts)
    return cache_dir / key[:2] / f"{key}.json"


def _read_valid(path: Path, texts: list[str]) -> dict[str, Any] | None:
    try:
        payload = read_json(path)
        if not isinstance(payload, dict):
            return None
        integrity = payload.pop("integrity_sha256")
        if sha256_json(payload) != integrity:
            return None
        if payload.get("key") != _batch_key(texts):
            return None
        vectors = cast(list[list[float]], payload["vectors"])
        if len(vectors) != len(texts):
            return None
        for vector in vectors:
            validate_vector(vector, DIMENSIONS)
        payload["integrity_sha256"] = integrity
        return payload
    except OSError, ValueError, KeyError, TypeError, json.JSONDecodeError:
        return None


def _write(path: Path, payload: dict) -> None:
    payload = payload | {"integrity_sha256": sha256_json(payload)}
    write_json(path, payload, indent=None)


def _request(client, texts: list[str]) -> tuple[list[list[float]], dict]:
    result = client.embeddings.create(
        input=texts,
        model=MODEL,
        dimensions=DIMENSIONS,
        encoding_format="float",
    )
    ordered = sorted(result.data, key=lambda item: item.index)
    if [item.index for item in ordered] != list(range(len(texts))):
        raise ValueError("Embedding response indices do not match the request")
    vectors = [list(item.embedding) for item in ordered]
    for vector in vectors:
        validate_vector(vector, DIMENSIONS)
    usage = getattr(result, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens) or prompt_tokens)
    return vectors, {"prompt_tokens": prompt_tokens, "total_tokens": total_tokens, "api_calls": 1}


def cached_embeddings(client, texts: list[str], cache_dir: Path, batch_size: int = 64) -> list[list[float]]:
    """Reuse verified content-addressed batches and request only missing or corrupt ones."""

    if not 1 <= batch_size <= 64:
        raise ValueError("batch_size must be in 1..64")
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("Embedding input must be nonempty text")
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        path = _path(cache_dir, batch)
        payload = _read_valid(path, batch)
        if payload is None:
            batch_vectors, usage = _request(client, batch)
            payload = {
                "cache_version": CACHE_VERSION,
                "key": _batch_key(batch),
                "model": MODEL,
                "dimensions": DIMENSIONS,
                "texts_sha256": sha256_json(batch),
                "vectors": batch_vectors,
                "usage": usage,
            }
            _write(path, payload)
        vectors.extend(cast(list[list[float]], payload["vectors"]))
    return vectors


def cached_usage(texts: list[str], cache_dir: Path, batch_size: int = 64) -> dict:
    """Return the original measured API usage for the exact current embedding batches."""
    totals = {"prompt_tokens": 0, "total_tokens": 0, "api_calls": 0}
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        payload = _read_valid(_path(cache_dir, batch), batch)
        if payload is None:
            raise ValueError("Embedding cache is missing or invalid")
        for key in totals:
            totals[key] += int(payload.get("usage", {}).get(key, 0))
    totals["cost_usd"] = totals["prompt_tokens"] / 1_000_000 * USD_PER_MILLION_TOKENS
    return totals
