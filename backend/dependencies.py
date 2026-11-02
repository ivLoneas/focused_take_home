"""Construction of production agent dependencies."""

from functools import partial
from typing import cast

import psycopg
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from agents.baseline import BaselineAgent
from agents.baseline.baseline_agent import ChatModel
from agents.settings import AgentConfig
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
    embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=api_key)
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
    return BaselineAgent(
        cast(ChatModel, model), retriever=adapter, config=agent_config,
        coverage=DatabaseCoverage(connection_factory=partial(psycopg.connect, settings.database_url)),
    )
