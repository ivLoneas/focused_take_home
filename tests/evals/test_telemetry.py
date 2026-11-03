"""Independent contract for per-invocation evaluation telemetry."""

import json
from uuid import uuid4

import httpx
import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, Generation, LLMResult
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda

from evals.telemetry import RunMetrics, record_embedding_response


class ExampleRetriever(BaseRetriever):
    def _get_relevant_documents(self, query: str, *, run_manager) -> list[Document]:
        if query == "fail":
            raise RuntimeError("retrieval unavailable")
        return [] if query == "empty" else [Document(page_content="evidence")]


def start_model(metrics: RunMetrics, *, model: str = "example-model"):
    run_id = uuid4()
    metrics.on_chat_model_start({}, [[]], run_id=run_id, invocation_params={"model": model})
    return run_id


def usage_result(*, inputs: int = 20, outputs: int = 7) -> LLMResult:
    return LLMResult(
        generations=[
            [
                ChatGeneration(
                    message=AIMessage(
                        content="answer",
                        usage_metadata={
                            "input_tokens": inputs,
                            "output_tokens": outputs,
                            "total_tokens": inputs + outputs,
                            "input_token_details": {"cache_read": 4},
                            "output_token_details": {"reasoning": 3},
                        },
                    )
                )
            ]
        ]
    )


def test_empty_metrics_have_stable_zero_counters() -> None:
    metrics = RunMetrics()

    assert isinstance(metrics, BaseCallbackHandler)
    values = metrics.metadata()
    for field in (
        "model_calls",
        "model_errors",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "retrieval_calls",
        "retrieval_errors",
        "empty_retrievals",
        "retrieved_chunks",
        "retrieval_latency_ms",
        "embedding_calls",
        "embedding_input_tokens",
    ):
        assert values[field] == 0, field
    assert values["model_names"] == []


def test_chat_usage_is_aggregated_across_calls_with_sorted_unique_models() -> None:
    metrics = RunMetrics()
    for name in ("z-model", "a-model", "z-model"):
        run_id = start_model(metrics, model=name)
        metrics.on_llm_end(usage_result(), run_id=run_id)

    values = metrics.metadata()
    assert values["model_calls"] == 3
    assert values["input_tokens"] == 60
    assert values["output_tokens"] == 21
    assert values["total_tokens"] == 81
    assert values["cached_input_tokens"] == 12
    assert values["reasoning_tokens"] == 9
    assert values["model_names"] == ["a-model", "z-model"]


def test_duplicate_model_start_and_completion_do_not_double_count() -> None:
    metrics = RunMetrics()
    run_id = start_model(metrics)
    metrics.on_llm_start({}, ["prompt"], run_id=run_id, invocation_params={"model": "example-model"})
    metrics.on_llm_end(usage_result(), run_id=run_id)
    metrics.on_llm_end(usage_result(), run_id=run_id)

    assert metrics.metadata()["model_calls"] == 1
    assert metrics.metadata()["total_tokens"] == 27


def test_provider_token_usage_is_a_fallback_when_message_usage_is_absent() -> None:
    metrics = RunMetrics()
    run_id = start_model(metrics)
    response = LLMResult(
        generations=[[Generation(text="answer")]],
        llm_output={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 15,
                "total_tokens": 115,
                "prompt_tokens_details": {"cached_tokens": 30},
                "completion_tokens_details": {"reasoning_tokens": 5},
            }
        },
    )
    metrics.on_llm_end(response, run_id=run_id)

    values = metrics.metadata()
    assert values["input_tokens"] == 100
    assert values["output_tokens"] == 15
    assert values["total_tokens"] == 115
    assert values["cached_input_tokens"] == 30
    assert values["reasoning_tokens"] == 5


def test_message_usage_takes_precedence_over_duplicate_provider_usage() -> None:
    metrics = RunMetrics()
    run_id = start_model(metrics)
    response = usage_result()
    response.llm_output = {"token_usage": {"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27}}
    metrics.on_llm_end(response, run_id=run_id)

    assert metrics.metadata()["total_tokens"] == 27


def test_missing_model_usage_is_safe_and_retains_call_count() -> None:
    metrics = RunMetrics()
    run_id = start_model(metrics)
    metrics.on_llm_end(LLMResult(generations=[[Generation(text="answer")]]), run_id=run_id)

    assert metrics.metadata()["model_calls"] == 1
    assert metrics.metadata()["total_tokens"] == 0


def test_failed_model_call_counts_once_and_does_not_invent_tokens() -> None:
    metrics = RunMetrics()
    run_id = start_model(metrics)
    for _ in range(2):
        metrics.on_llm_error(RuntimeError("API secret or private prompt"), run_id=run_id)

    values = metrics.metadata()
    assert values["model_calls"] == 1
    assert values["model_errors"] == 1
    assert values["total_tokens"] == 0
    assert "private prompt" not in json.dumps(values)


def test_retrieval_records_distinct_calls_empty_results_chunks_and_failures() -> None:
    metrics = RunMetrics()
    for outcome in ("documents", "empty", "error"):
        run_id = uuid4()
        metrics.on_retriever_start({}, "private query", run_id=run_id)
        metrics.on_retriever_start({}, "private query", run_id=run_id)
        if outcome == "error":
            metrics.on_retriever_error(RuntimeError("database password"), run_id=run_id)
            metrics.on_retriever_error(RuntimeError("database password"), run_id=run_id)
        else:
            documents = [Document(page_content="one"), Document(page_content="two")] if outcome == "documents" else []
            metrics.on_retriever_end(documents, run_id=run_id)
            metrics.on_retriever_end(documents, run_id=run_id)

    values = metrics.metadata()
    assert values["retrieval_calls"] == 3
    assert values["retrieval_errors"] == 1
    assert values["empty_retrievals"] == 1
    assert values["retrieved_chunks"] == 2
    assert values["retrieval_latency_ms"] >= 0
    assert "private query" not in json.dumps(values)
    assert "database password" not in json.dumps(values)


def test_callbacks_for_unknown_runs_are_safe_no_ops() -> None:
    metrics = RunMetrics()
    metrics.on_llm_end(usage_result(), run_id=uuid4())
    metrics.on_llm_error(RuntimeError("unknown model"), run_id=uuid4())
    metrics.on_retriever_end([Document(page_content="unknown")], run_id=uuid4())
    metrics.on_retriever_error(RuntimeError("unknown retrieval"), run_id=uuid4())

    assert metrics.metadata()["total_tokens"] == 0
    assert metrics.metadata()["model_errors"] == 0
    assert metrics.metadata()["retrieval_errors"] == 0
    assert metrics.metadata()["retrieved_chunks"] == 0


def test_context_manager_collects_nested_model_and_retriever_without_explicit_callbacks() -> None:
    model = FakeListChatModel(responses=["answer"])
    retriever = ExampleRetriever()

    def workflow(question: str) -> str:
        retriever.invoke(question)
        return model.invoke(question).content

    with RunMetrics() as metrics:
        assert RunnableLambda(workflow).invoke("question") == "answer"

    assert metrics.metadata()["model_calls"] == 1
    assert metrics.metadata()["retrieval_calls"] == 1
    assert metrics.metadata()["retrieved_chunks"] == 1


def test_separate_contexts_do_not_leak_events() -> None:
    retriever = ExampleRetriever()
    with RunMetrics() as first:
        retriever.invoke("question")
    retriever.invoke("empty")
    with RunMetrics() as second:
        retriever.invoke("empty")

    assert first.metadata()["retrieval_calls"] == 1
    assert first.metadata()["empty_retrievals"] == 0
    assert second.metadata()["retrieval_calls"] == 1
    assert second.metadata()["empty_retrievals"] == 1


def test_context_cleanup_preserves_exception_and_stops_collecting() -> None:
    retriever = ExampleRetriever()
    with pytest.raises(RuntimeError, match="retrieval unavailable"), RunMetrics() as metrics:
        retriever.invoke("fail")
    retriever.invoke("question")

    assert metrics.metadata()["retrieval_calls"] == 1
    assert metrics.metadata()["retrieval_errors"] == 1
    assert metrics.metadata()["retrieved_chunks"] == 0


def test_embedding_hook_aggregates_usage_only_inside_active_context() -> None:
    response = httpx.Response(
        200,
        json={
            "model": "text-embedding-3-small",
            "data": [{"embedding": [0.1, 0.2]}],
            "usage": {"prompt_tokens": 13, "total_tokens": 13},
        },
    )
    record_embedding_response(response)
    with RunMetrics() as first:
        record_embedding_response(response)
        record_embedding_response(response)
    record_embedding_response(response)
    with RunMetrics() as second:
        record_embedding_response(response)

    assert first.metadata()["embedding_calls"] == 2
    assert first.metadata()["embedding_input_tokens"] == 26
    assert second.metadata()["embedding_calls"] == 1
    assert second.metadata()["embedding_input_tokens"] == 13
    assert "data" not in first.metadata()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"invalid json"),
        httpx.Response(500, json={"error": "private error details"}),
        httpx.Response(200, json={"model": "gpt-6.1-terra", "usage": {"prompt_tokens": 13}}),
        httpx.Response(200, json={"model": "text-embedding-3-small"}),
        httpx.Response(200, json={"model": "text-embedding-3-small", "usage": None}),
        httpx.Response(200, json=[]),
    ],
)
def test_embedding_hook_ignores_non_embedding_or_malformed_responses(response: httpx.Response) -> None:
    with RunMetrics() as metrics:
        record_embedding_response(response)

    assert metrics.metadata()["embedding_calls"] == 0
    assert metrics.metadata()["embedding_input_tokens"] == 0
    assert "private error details" not in json.dumps(metrics.metadata())


def test_embedding_hook_reads_streaming_response_body() -> None:
    response = httpx.Response(
        200, stream=httpx.ByteStream(b'{"model":"text-embedding-3-small","usage":{"prompt_tokens":9,"total_tokens":9}}')
    )
    assert not response.is_stream_consumed

    with RunMetrics() as metrics:
        record_embedding_response(response)

    assert response.is_stream_consumed
    assert metrics.metadata()["embedding_input_tokens"] == 9


def test_embedding_hook_uses_total_tokens_when_prompt_tokens_are_absent() -> None:
    response = httpx.Response(200, json={"model": "text-embedding-3-small", "usage": {"total_tokens": 11}})

    with RunMetrics() as metrics:
        record_embedding_response(response)

    assert metrics.metadata()["embedding_calls"] == 1
    assert metrics.metadata()["embedding_input_tokens"] == 11
