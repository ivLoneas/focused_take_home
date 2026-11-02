"""Per-invocation usage and retrieval measurements without storing prompts or secrets."""

from contextvars import ContextVar
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import UUID

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.tracers.context import register_configure_hook

_active_metrics: ContextVar[Any] = ContextVar("focused_eval_metrics", default=None)
register_configure_hook(_active_metrics, inheritable=True)


class RunMetrics(BaseCallbackHandler):
    """Collect nested LangChain events while preserving existing tracing callbacks."""

    run_inline = True

    def __init__(self) -> None:
        self._lock = Lock()
        self._values = dict.fromkeys(
            (
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
            ),
            0,
        )
        self._models: set[str] = set()
        self._model_runs: set[UUID] = set()
        self._finished_models: set[UUID] = set()
        self._retrieval_runs: dict[UUID, float] = {}
        self._finished_retrievals: set[UUID] = set()

    def __enter__(self):
        self._token = _active_metrics.set(self)
        return self

    def __exit__(self, *exc: object) -> None:
        _active_metrics.reset(self._token)

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            return {**self._values, "model_names": sorted(self._models)}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs) -> None:
        self.on_llm_start(serialized, messages, run_id=run_id, **kwargs)

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs) -> None:
        with self._lock:
            if run_id not in self._model_runs:
                self._model_runs.add(run_id)
                self._values["model_calls"] += 1
            params = kwargs.get("invocation_params") or {}
            name = params.get("model") or params.get("model_name")
            if isinstance(name, str):
                self._models.add(name)

    def on_llm_end(self, response: LLMResult, *, run_id, **kwargs) -> None:
        with self._lock:
            if run_id not in self._model_runs or run_id in self._finished_models:
                return
            self._finished_models.add(run_id)
            usage = None
            if response.generations and response.generations[0]:
                message = getattr(response.generations[0][0], "message", None)
                usage = getattr(message, "usage_metadata", None)
            if usage:
                inputs = usage.get("input_tokens", 0)
                outputs = usage.get("output_tokens", 0)
                cached = (usage.get("input_token_details") or {}).get("cache_read", 0)
                reasoning = (usage.get("output_token_details") or {}).get("reasoning", 0)
            else:
                usage = (response.llm_output or {}).get("token_usage") or {}
                inputs = usage.get("prompt_tokens", 0)
                outputs = usage.get("completion_tokens", 0)
                cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
            for field, value in {
                "input_tokens": inputs,
                "output_tokens": outputs,
                "total_tokens": usage.get("total_tokens", inputs + outputs),
                "cached_input_tokens": cached,
                "reasoning_tokens": reasoning,
            }.items():
                self._values[field] += value

    def on_llm_error(self, error, *, run_id, **kwargs) -> None:
        with self._lock:
            if run_id in self._model_runs and run_id not in self._finished_models:
                self._finished_models.add(run_id)
                self._values["model_errors"] += 1

    def on_retriever_start(self, serialized, query, *, run_id, **kwargs) -> None:
        with self._lock:
            if run_id not in self._retrieval_runs:
                self._retrieval_runs[run_id] = perf_counter()
                self._values["retrieval_calls"] += 1

    def _finish_retrieval(self, run_id: UUID) -> bool:
        if run_id not in self._retrieval_runs or run_id in self._finished_retrievals:
            return False
        self._finished_retrievals.add(run_id)
        self._values["retrieval_latency_ms"] += (perf_counter() - self._retrieval_runs[run_id]) * 1000
        return True

    def on_retriever_end(self, documents, *, run_id, **kwargs) -> None:
        with self._lock:
            if self._finish_retrieval(run_id):
                self._values["retrieved_chunks"] += len(documents)
                self._values["empty_retrievals"] += int(not documents)

    def on_retriever_error(self, error, *, run_id, **kwargs) -> None:
        with self._lock:
            if self._finish_retrieval(run_id):
                self._values["retrieval_errors"] += 1


def record_embedding_response(response: httpx.Response) -> None:
    """Read successful embedding API usage before the SDK discards the usage fields."""
    metrics = _active_metrics.get()
    if metrics is None or response.is_error:
        return
    try:
        response.read()
        body = response.json()
        if not isinstance(body, dict) or not str(body.get("model", "")).startswith("text-embedding-"):
            return
        usage = body.get("usage")
        if not isinstance(usage, dict):
            return
        tokens = usage.get("prompt_tokens", usage.get("total_tokens"))
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            return
    except ValueError, httpx.HTTPError:
        return
    with metrics._lock:
        metrics._values["embedding_calls"] += 1
        metrics._values["embedding_input_tokens"] += tokens
