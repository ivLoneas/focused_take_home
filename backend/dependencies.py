"""Construction of production agent dependencies."""

from functools import partial
from typing import cast

import psycopg
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from agents.baseline import BaselineAgent
from agents.baseline.baseline_agent import ChatModel
from agents.retrieval import BaselineRetrieverAdapter, PgVectorRetriever
from agents.retrieval.retriever import DocumentRetriever
from agents.settings import AgentConfig
from backend.config import Settings


def build_baseline_agent(settings: Settings) -> BaselineAgent:
    """Build the baseline graph without opening a database connection."""

    api_key = settings.openai_api_key
    if api_key is None:
        raise ValueError("OPENAI_API_KEY is required to construct the baseline agent")

    agent_config = AgentConfig(model=settings.chat_model)
    model = ChatOpenAI(model=agent_config.model, api_key=api_key)
    embeddings = OpenAIEmbeddings(model=settings.embedding_model, api_key=api_key)
    retriever = PgVectorRetriever(
        embeddings=embeddings,
        connection_factory=partial(psycopg.connect, settings.database_url),
        limit=settings.retrieval_limit,
    )
    adapter = BaselineRetrieverAdapter(retriever=cast(DocumentRetriever, retriever))
    return BaselineAgent(cast(ChatModel, model), retriever=adapter, config=agent_config)
