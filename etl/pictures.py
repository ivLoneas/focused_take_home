"""Cached OpenAI vision descriptions for Docling picture items."""

import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from docling_core.types.doc import PictureItem
from docling_core.types.doc.common.meta import DescriptionMetaField
from docling_core.types.doc.items.picture.meta import PictureMeta

from etl.parsing import IMAGE_PROMPT
from utils import read_json, sha256_bytes, sha256_json, write_json

MODEL = "gpt-6-luna"
DETAIL = "high"
MAX_OUTPUT_TOKENS = 300
OUTPUT_TOKEN_LIMITS = (MAX_OUTPUT_TOKENS, 600, 1200, 2048)
INPUT_USD_PER_MILLION_TOKENS = 0.10
OUTPUT_USD_PER_MILLION_TOKENS = 0.50
CACHE_VERSION = 1


def empty_usage() -> dict[str, int | float]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "api_calls": 0,
        "cost_usd": 0.0,
    }


def _cache_key(image: bytes, model: str, prompt: str, detail: str) -> str:
    return sha256_json(
        {
            "cache_version": CACHE_VERSION,
            "image_sha256": sha256_bytes(image),
            "model": model,
            "prompt": prompt,
            "detail": detail,
        }
    )


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / key[:2] / f"{key}.json"


def _read_valid(path: Path, key: str) -> dict[str, Any] | None:
    try:
        payload = read_json(path)
        if not isinstance(payload, dict):
            return None
        integrity = payload.pop("integrity_sha256")
        if payload.get("key") != key or sha256_json(payload) != integrity:
            return None
        description = payload.get("description")
        usage = payload.get("usage")
        if not isinstance(description, str) or not description.strip() or not isinstance(usage, dict):
            return None
        required = {"input_tokens", "output_tokens", "total_tokens", "api_calls", "cost_usd"}
        if not required.issubset(usage):
            return None
        payload["integrity_sha256"] = integrity
        return payload
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def cached_description(
    client,
    png_bytes: bytes,
    cache_dir: Path,
    *,
    model: str = MODEL,
    prompt: str = IMAGE_PROMPT,
    detail: str = DETAIL,
) -> tuple[str, dict[str, int | float]]:
    """Describe one PNG, reusing only a verified exact-input cache entry."""

    if not isinstance(png_bytes, bytes) or not png_bytes:
        raise ValueError("Picture input must be nonempty PNG bytes")
    key = _cache_key(png_bytes, model, prompt, detail)
    path = _cache_path(cache_dir, key)
    payload = _read_valid(path, key)
    if payload is None:
        encoded = base64.b64encode(png_bytes).decode("ascii")
        request = {
            "model": model,
            "reasoning": {"effort": "none"},
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{encoded}",
                            "detail": detail,
                        },
                    ],
                }
            ],
        }
        measured = empty_usage()
        response = None
        for output_limit in OUTPUT_TOKEN_LIMITS:
            response = client.responses.create(max_output_tokens=output_limit, **request)
            response_usage = getattr(response, "usage", None)
            input_tokens = int(getattr(response_usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(response_usage, "output_tokens", 0) or 0)
            total_tokens = int(getattr(response_usage, "total_tokens", input_tokens + output_tokens) or 0)
            measured["input_tokens"] += input_tokens
            measured["output_tokens"] += output_tokens
            measured["total_tokens"] += total_tokens
            measured["api_calls"] += 1
            measured["cost_usd"] += (
                input_tokens * INPUT_USD_PER_MILLION_TOKENS
                + output_tokens * OUTPUT_USD_PER_MILLION_TOKENS
            ) / 1_000_000
            if getattr(response, "status", "completed") == "completed":
                break
            incomplete = getattr(response, "incomplete_details", None)
            if getattr(incomplete, "reason", None) != "max_output_tokens":
                raise ValueError(f"Picture description did not complete: {response.status}")
        else:
            raise ValueError("Picture description remained incomplete at the maximum output-token limit")
        description = getattr(response, "output_text", None)
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Picture description response was empty")
        payload = {
            "cache_version": CACHE_VERSION,
            "key": key,
            "model": model,
            "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
            "detail": detail,
            "image_sha256": sha256_bytes(png_bytes),
            "description": description.strip(),
            "usage": measured,
        }
        write_json(path, payload | {"integrity_sha256": sha256_json(payload)}, indent=None)
    return payload["description"], dict(payload["usage"])


def enrich_pictures(doc, client, cache_dir: Path) -> dict[str, int | float]:
    """Attach cached Luna descriptions to every renderable picture in a document."""

    totals = empty_usage()
    for item, _ in doc.iterate_items(traverse_pictures=True):
        if not isinstance(item, PictureItem):
            continue
        image = item.get_image(doc)
        if image is None:
            continue
        stream = BytesIO()
        image.save(stream, format="PNG")
        description, usage = cached_description(client, stream.getvalue(), cache_dir)
        description_field = DescriptionMetaField(text=description, created_by=MODEL)
        item.meta = (
            item.meta.model_copy(update={"description": description_field})
            if item.meta is not None
            else PictureMeta(description=description_field)
        )
        for key in totals:
            totals[key] += usage[key]
    return totals
