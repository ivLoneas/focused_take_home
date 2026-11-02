"""Inputs, evidence, and dependency contracts for retrieval tools."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from etl.companies import Company


@dataclass(frozen=True)
class RetrievalRequest:
    company: Company
    query: str
    required_facts: tuple[str, ...]
    attempt: int


class RetrievalToolInput(BaseModel):
    company: Company = Field(description="Required company; search only its dedicated vector table")
    query: str = Field(description="Focused query including fiscal period, metric, and report type", min_length=1)


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class QueryEmbeddings(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


class DocumentRetriever(Protocol):
    def invoke(self, query: str) -> Sequence[Document]: ...


class InvokableRetriever(Protocol):
    def invoke(self, request: RetrievalRequest) -> Sequence[RetrievedChunk]: ...


type Retriever = Callable[[RetrievalRequest], Sequence[RetrievedChunk]] | InvokableRetriever
