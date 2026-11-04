"""Measured usage is complete, request-local, and priced without double counting."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from backend.app import create_app
from backend.config import Settings


def summary(telemetry, embedding_model="text-embedding-3-small"):
    from backend.usage import summarize_usage
    return summarize_usage(telemetry, embedding_model)


def measured(models=None, *, embeddings=0, embedding_calls=0):
    models = models or {}
    return {"model_calls": sum(value["model_calls"] for value in models.values()), "by_model": models,
            "input_tokens": sum(value["input_tokens"] for value in models.values()),
            "output_tokens": sum(value["output_tokens"] for value in models.values()),
            "total_tokens": sum(value["total_tokens"] for value in models.values()),
            "embedding_calls": embedding_calls, "embedding_input_tokens": embeddings}


def usage(inputs, outputs, *, cached=0, reasoning=0, calls=1):
    return {"model_calls": calls, "input_tokens": inputs, "output_tokens": outputs,
            "total_tokens": inputs + outputs, "cached_input_tokens": cached, "reasoning_tokens": reasoning}


def test_mixed_model_cost_counts_cached_reasoning_and_embeddings_once():
    data = measured({
        "gpt-6.1-terra": usage(1000, 100, cached=200, reasoning=60),
        "gpt-6-luna": usage(2000, 200, cached=1000, calls=2),
        "jev-1.14.0": usage(100, 0),
    }, embeddings=500, embedding_calls=2)
    result = summary(data)
    assert result["total_tokens"] == 3900
    assert result["cost_usd"] == pytest.approx((800 + 10 + 500 + 100 + 10 + 100 + 4.2 + 10) / 1_000_000)


@pytest.mark.parametrize("model,expected", [("gpt-6.1-terra", 6), ("gpt-6-luna", .6),
                                             ("jev-1.14.0", .042), ("jev-1.13.0", .042)])
def test_standard_known_model_rates(model, expected):
    outputs = 0 if model.startswith("jev") else 1_000_000
    result = summary(measured({model: usage(1_000_000, outputs)}))
    assert result["cost_usd"] == pytest.approx(expected)


@pytest.mark.parametrize("model,expected", [("text-embedding-3-small", .02), ("text-embedding-3-large", .13),
                                             ("text-embedding-ada-002", .10)])
def test_embedding_only_usage_is_measured_and_priced(model, expected):
    assert summary(measured(embeddings=1_000_000, embedding_calls=1), model) == {
        "total_tokens": 1_000_000, "cost_usd": expected,
    }


def test_unknown_pricing_keeps_measured_total_but_does_not_report_partial_cost():
    assert summary(measured({"unknown-answer-model": usage(10, 2)}, embeddings=20, embedding_calls=1)) == {
        "total_tokens": 32, "cost_usd": None,
    }
    assert summary(measured({"gpt-6-luna": usage(10, 2)}, embeddings=20, embedding_calls=1), "unknown-embedding") == {
        "total_tokens": 32, "cost_usd": None,
    }


def test_missing_per_model_usage_makes_total_and_cost_unknown():
    data = measured({"gpt-6-luna": usage(10, 2)})
    data["model_calls"] = 2
    assert summary(data) == {"total_tokens": None, "cost_usd": None}


def test_no_calls_is_unknown_but_measured_zero_is_zero():
    assert summary(measured()) == {"total_tokens": None, "cost_usd": None}
    assert summary(measured({"gpt-6-luna": usage(0, 0)})) == {"total_tokens": 0, "cost_usd": 0.0}


def test_cached_input_above_inputs_is_clamped_for_price():
    result = summary(measured({"gpt-6.1-terra": usage(10, 2, cached=100)}))
    assert result["total_tokens"] == 12
    assert result["cost_usd"] == pytest.approx((10 * .05 + 2 * 5) / 1_000_000)


class UsageAgent:
    def answer(self, question):
        from agents.telemetry import record_embedding_response
        amount = 10 if question == "First" else 20
        model = FakeMessagesListChatModel(responses=[AIMessage(
            content="10", response_metadata={"model_name": "gpt-6-luna"},
            usage_metadata={"input_tokens": amount, "output_tokens": 2, "total_tokens": amount + 2},
        )])
        model.invoke(question)
        record_embedding_response(httpx.Response(200, json={
            "model": "text-embedding-3-small", "usage": {"prompt_tokens": 200, "total_tokens": 200},
        }))
        return SimpleNamespace(status="answered", answer="10", citations=(), retrieval_attempts=1, source_urls={})

    invoke = answer

    def stream(self, question):
        result = self.answer(question)
        yield {"type": "token", "text": "10"}
        yield {"type": "result", "result": result}


@pytest.mark.parametrize("endpoint", ["/api/run", "/api/run/stream"])
def test_api_reports_usage_on_final_result_and_isolates_requests(endpoint):
    agent = UsageAgent()
    client = TestClient(create_app(settings=Settings(_env_file=None), v2_agent_factory=lambda: agent))

    def run(question):
        import json
        response = client.post(endpoint, json={"agent_id": "agent_v2", "question": question})
        assert response.status_code == 200
        if endpoint.endswith("/stream"):
            frames = [json.loads(line) for line in response.iter_lines()]
            assert frames[0] == {"type": "token", "text": "10"}
            assert frames[-1]["type"] == "result", frames
            return frames[-1]["result"]["metrics"]
        return response.json()["metrics"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(run, ["First", "Second"]))
    assert first["total_tokens"] == 212
    assert second["total_tokens"] == 222
    assert first["cost_usd"] == pytest.approx(.000006)
    assert second["cost_usd"] == pytest.approx(.000007)


def test_incomplete_model_usage_is_explicitly_unknown_in_api():
    def invoke(question):
        FakeMessagesListChatModel(responses=[AIMessage(content="10", response_metadata={"model_name": "gpt-6-luna"})]).invoke(question)
        return SimpleNamespace(status="answered", answer="10", citations=(), retrieval_attempts=0)

    client = TestClient(create_app(settings=Settings(_env_file=None), v2_agent_factory=lambda: SimpleNamespace(invoke=invoke)))
    response = client.post("/api/run", json={"agent_id": "agent_v2", "question": "First"})
    assert response.json()["metrics"] == {"total_tokens": None, "cost_usd": None}


def test_shared_telemetry_keeps_eval_import_identity():
    from agents.telemetry import ModelMetrics, RunMetrics, record_embedding_response
    from evals import agent_v2_provider, telemetry
    assert telemetry.RunMetrics is RunMetrics
    assert telemetry.record_embedding_response is record_embedding_response
    assert agent_v2_provider.ModelMetrics is ModelMetrics
