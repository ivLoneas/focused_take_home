"""Estimate standard short-context API cost from measured per-model usage."""

# USD per million input, cached-input, and output tokens; verified 2026-11-04.
# https://developers.openai.com/api/docs/pricing
# https://docs.typesafe.ai/models.md
MODEL_PRICES = {
    "gpt-6.1-terra": (1.0, 0.05, 5.0),
    "gpt-6-luna": (0.1, 0.01, 0.5),
    "jev-1.14.0": (0.042, 0.042, 0.0),
    "jev-1.13.0": (0.042, 0.042, 0.0),
}
EMBEDDING_PRICES = {"text-embedding-3-small": 0.02, "text-embedding-3-large": 0.13, "text-embedding-ada-002": 0.10}


def summarize_usage(telemetry: dict, embedding_model: str) -> dict:
    """Keep unknown usage or prices explicit instead of returning partial totals."""
    models = telemetry.get("by_model", {})
    model_calls = telemetry.get("model_calls", 0)
    embedding_calls = telemetry.get("embedding_calls", 0)
    unknown = {"total_tokens": None, "cost_usd": None}
    if not (model_calls or embedding_calls):
        return unknown
    if sum(model["model_calls"] for model in models.values()) != model_calls:
        return unknown

    embedding_tokens = telemetry.get("embedding_input_tokens", 0)
    result = {"total_tokens": telemetry.get("total_tokens", 0) + embedding_tokens, "cost_usd": None}
    cost = 0.0
    for name, usage in models.items():
        if name not in MODEL_PRICES:
            return result
        input_rate, cached_rate, output_rate = MODEL_PRICES[name]
        cached = min(usage["input_tokens"], max(0, usage.get("cached_input_tokens", 0)))
        cost += (usage["input_tokens"] - cached) * input_rate + cached * cached_rate + usage["output_tokens"] * output_rate
    if embedding_calls:
        if embedding_model not in EMBEDDING_PRICES:
            return result
        cost += embedding_tokens * EMBEDDING_PRICES[embedding_model]
    result["cost_usd"] = cost / 1_000_000
    return result
