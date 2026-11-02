"""Opt-in Promptfoo provider with per-model usage, including Jev."""

from functools import lru_cache, partial
from time import perf_counter

import httpx
import psycopg
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from agents.agent_v2 import AgentV2, AgentV2Config, JevDomainGate
from agents.tools import BaselineRetrieverAdapter, DatabaseCoverage, PgVectorRetriever
from etl.companies import COMPANY_TABLES
from evals.provider import ProviderSettings
from evals.telemetry import RunMetrics, record_embedding_response
from utils import require_nonblank_string


def build_agent(settings: ProviderSettings) -> AgentV2:
    config = AgentV2Config(model=settings.chat_model)
    model_options = {"api_key": settings.openai_api_key, "max_tokens": 4096, "timeout": 90, "max_retries": 1}
    model = ChatOpenAI(model=config.model, reasoning_effort="low", **model_options)
    routing = ChatOpenAI(model=config.routing_model, reasoning_effort="low", **model_options)
    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model, dimensions=settings.embedding_dimensions,
        api_key=settings.openai_api_key,
        http_client=httpx.Client(event_hooks={"response": [record_embedding_response]}),
    )
    connect = partial(psycopg.connect, settings.database_url)
    retrievers = {
        company: PgVectorRetriever(
            embeddings=embeddings, connection_factory=connect, limit=settings.retrieval_limit, company=company,
        ) for company in COMPANY_TABLES
    }
    return AgentV2(
        model, routing_model=routing, domain_gate=JevDomainGate(config),
        retriever=BaselineRetrieverAdapter(retrievers=retrievers),
        coverage=DatabaseCoverage(connection_factory=connect),
        max_retrieval_attempts=settings.max_retrieval_attempts, config=config,
    )


@lru_cache(maxsize=1)
def get_agent() -> AgentV2:
    return build_agent(ProviderSettings())


class ModelMetrics(RunMetrics):
    """Preserve existing counters and aggregate actual response-model token usage."""

    def __init__(self) -> None:
        super().__init__()
        self.usage = UsageMetadataCallbackHandler()
        self.calls: dict[str, int] = {}

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        if run_id in self._finished_models:
            return
        super().on_llm_end(response, run_id=run_id, **kwargs)
        self.usage.on_llm_end(response, run_id=run_id, **kwargs)
        if response.generations and response.generations[0]:
            message = getattr(response.generations[0][0], "message", None)
            name = getattr(message, "response_metadata", {}).get("model_name")
            if name:
                with self._lock:
                    self.calls[name] = self.calls.get(name, 0) + 1

    def metadata(self) -> dict:
        by_model = {
            name: {
                "model_calls": self.calls.get(name, 0),
                "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                "total_tokens": usage["total_tokens"],
                "cached_input_tokens": usage.get("input_token_details", {}).get("cache_read", 0),
                "reasoning_tokens": usage.get("output_token_details", {}).get("reasoning", 0),
            } for name, usage in self.usage.usage_metadata.items()
        }
        return {**super().metadata(), "by_model": by_model}


def call_api(prompt: object, options: dict, context: dict) -> dict:
    del options, context
    prompt = require_nonblank_string(prompt, field_name="prompt")
    started = perf_counter()
    with ModelMetrics() as metrics:
        result = get_agent().invoke(prompt)
    usage = metrics.metadata()
    return {
        "output": result.answer,
        "metadata": {
            "status": result.status, "citations": list(result.citations),
            "retrieval_attempts": result.retrieval_attempts, "tool_calls": list(result.tool_calls),
            "answer_latency_ms": (perf_counter() - started) * 1000, "telemetry": usage,
        },
        "tokenUsage": {
            "prompt": usage["input_tokens"], "completion": usage["output_tokens"],
            "total": usage["total_tokens"], "cached": usage["cached_input_tokens"], "numRequests": usage["model_calls"],
        },
    }
