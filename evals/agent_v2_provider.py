"""Opt-in Promptfoo provider with per-model usage, including Jev."""

from functools import lru_cache, partial
from time import perf_counter

import httpx
import psycopg
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from agents.agent_v2 import AgentV2, AgentV2Config, JevDomainGate
from agents.telemetry import ModelMetrics, record_embedding_response
from agents.tools import BaselineRetrieverAdapter, DatabaseCoverage, PgVectorRetriever
from etl.companies import COMPANY_TABLES
from evals.provider import ProviderSettings
from utils import require_nonblank_string


def build_agent(settings: ProviderSettings) -> AgentV2:
    config = AgentV2Config(model=settings.chat_model, streaming=False)
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
