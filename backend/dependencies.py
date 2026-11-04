"""Construction of production agent dependencies."""

from functools import partial
from typing import cast

import httpx
import psycopg
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from agents.agent_v2 import AgentV2, AgentV2Config, JevDomainGate
from agents.baseline import BaselineAgent
from agents.baseline.baseline_agent import ChatModel
from agents.settings import AgentConfig
from agents.telemetry import record_embedding_response
from agents.tools import BaselineRetrieverAdapter, DatabaseCoverage, PgVectorRetriever
from agents.tools.models import DocumentRetriever
from backend.config import Settings
from etl.companies import COMPANY_TABLES


def build_baseline_agent(settings: Settings) -> BaselineAgent:
    """Build the baseline graph without opening a database connection."""

    api_key = settings.openai_api_key
    if api_key is None:
        raise ValueError("OPENAI_API_KEY is required to construct the baseline agent")

    agent_config = AgentConfig(model=settings.chat_model)
    model = ChatOpenAI(model=agent_config.model, api_key=api_key)
    adapter, coverage = _build_retrieval(settings)
    return BaselineAgent(cast(ChatModel, model), retriever=adapter, config=agent_config, coverage=coverage)


def build_agent_v2(settings: Settings) -> AgentV2:
    """Enable final-answer streaming for the web app's v2 agent."""
    api_key = settings.openai_api_key
    if api_key is None:
        raise ValueError("OPENAI_API_KEY is required to construct agent v2")
    config = AgentV2Config(model=settings.chat_model, streaming=True)
    gate = JevDomainGate(config)
    options = {"api_key": api_key, "reasoning_effort": "low", "max_tokens": 4096, "timeout": 90, "max_retries": 1}
    model = ChatOpenAI(model=config.model, stream_usage=True, **options)
    routing = ChatOpenAI(model=config.routing_model, **options)
    adapter, coverage = _build_retrieval(settings)
    return AgentV2(
        cast(ChatModel, model), routing_model=cast(ChatModel, routing), domain_gate=gate,
        retriever=adapter, coverage=coverage, config=config,
    )


def _build_retrieval(settings: Settings) -> tuple[BaselineRetrieverAdapter, DatabaseCoverage]:
    api_key = settings.openai_api_key
    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model, api_key=api_key,
        http_client=httpx.Client(event_hooks={"response": [record_embedding_response]}),
    )
    retrievers = {
        company: cast(DocumentRetriever, PgVectorRetriever(
            embeddings=embeddings,
            connection_factory=partial(psycopg.connect, settings.database_url),
            limit=settings.retrieval_limit,
            company=company,
        ))
        for company in COMPANY_TABLES
    }
    adapter = BaselineRetrieverAdapter(retrievers=retrievers)
    return adapter, DatabaseCoverage(connection_factory=partial(psycopg.connect, settings.database_url))
