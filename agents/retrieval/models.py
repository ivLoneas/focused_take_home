"""Embedding contracts shared by retrieval implementations."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class QueryEmbeddings(Protocol):
    def embed_query(self, text: str) -> list[float]: ...
