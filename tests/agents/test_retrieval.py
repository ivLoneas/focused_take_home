"""Behavioral contract for reusable pgvector retrieval and baseline adaptation."""

from collections.abc import Mapping, Sequence
from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pgvector.psycopg.vector import register_vector_info
from psycopg.adapt import AdaptersMap, PyFormat, Transformer
from psycopg.types import TypeInfo

from agents.baseline.models import RetrievalRequest, RetrievedChunk
from agents.retrieval import BaselineRetrieverAdapter, PgVectorRetriever
from agents.retrieval import retriever as retrieval_module
from etl import store


class FakeEmbeddings:
    """Deterministic LangChain-style query embeddings without network access."""

    def __init__(self, vector: Sequence[float] = (0.1, 0.2, 0.3), error: Exception | None = None) -> None:
        self.vector = list(vector)
        self.error = error
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        if self.error is not None:
            raise self.error
        return list(self.vector)


class FakeDocumentRetriever:
    """Capture adapter calls while returning prebuilt LangChain documents."""

    def __init__(self, response: Sequence[Document] | Exception) -> None:
        self.response = response
        self.inputs: list[str] = []

    def invoke(self, query: str) -> Sequence[Document]:
        self.inputs.append(query)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_retriever(
    monkeypatch: pytest.MonkeyPatch,
    *,
    embeddings: FakeEmbeddings | None = None,
    connection: Mock | None = None,
    register_vector: Mock | None = None,
    search: Mock | None = None,
    **configuration: Any,
) -> tuple[PgVectorRetriever, FakeEmbeddings, Mock, Mock, Mock, Mock]:
    embeddings = embeddings or FakeEmbeddings()
    connection = connection or Mock(name="connection")
    connection_factory = Mock(name="connection_factory", return_value=connection)
    register_vector = register_vector or Mock(name="register_vector")
    search = search or Mock(name="search", return_value=[])
    monkeypatch.setattr(retrieval_module, "register_vector", register_vector, raising=False)
    monkeypatch.setattr(store, "search", search)
    retriever = PgVectorRetriever(
        embeddings=embeddings,
        connection_factory=connection_factory,
        **configuration,
    )
    return retriever, embeddings, connection_factory, connection, register_vector, search


def retrieval_row() -> dict[str, Any]:
    """Return the complete row contract currently exposed by ``etl.store.search``."""

    return {
        "chunk_id": "apple-2025-10k:42",
        "document_id": "apple-2025-10k",
        "text": "Apple's 2025 net sales were $416.161 billion.",
        "company": "Apple",
        "fiscal_year": 2025,
        "quarter": "FY",
        "report_type": "10-K",
        "title": "Apple Inc. 2025 Form 10-K",
        "url": "https://example.test/apple-2025-10k.pdf",
        "source_path": "data/raw/apple-2025-10k.pdf",
        "headings": ["Item 8", "Financial Statements"],
        "pages": [28, 29],
        "source_refs": ["#/texts/101", "#/tables/4"],
        "kind": "text",
        "score": 0.91,
    }


def test_pgvector_retriever_is_langchain_retriever_and_maps_complete_search_row(monkeypatch):
    row = retrieval_row()
    search = Mock(return_value=[row])
    retriever, embeddings, connection_factory, connection, register_vector, _ = make_retriever(
        monkeypatch,
        search=search,
        limit=7,
        company="Apple",
        fiscal_year=2025,
    )

    documents = retriever.invoke("Apple FY2025 net sales")

    assert isinstance(retriever, BaseRetriever)
    assert embeddings.queries == ["Apple FY2025 net sales"]
    connection_factory.assert_called_once_with()
    register_vector.assert_called_once_with(connection)
    search.assert_called_once_with(
        connection,
        [0.1, 0.2, 0.3],
        limit=7,
        company="Apple",
        fiscal_year=2025,
    )
    assert documents == [
        Document(
            page_content="Apple's 2025 net sales were $416.161 billion.",
            metadata={
                "chunk_id": "apple-2025-10k:42",
                "document_id": "apple-2025-10k",
                "company": "Apple",
                "fiscal_year": 2025,
                "quarter": "FY",
                "report_type": "10-K",
                "title": "Apple Inc. 2025 Form 10-K",
                "url": "https://example.test/apple-2025-10k.pdf",
                "source_path": "data/raw/apple-2025-10k.pdf",
                "headings": ("Item 8", "Financial Statements"),
                "pages": (28, 29),
                "source_refs": ("#/texts/101", "#/tables/4"),
                "kind": "text",
                "score": 0.91,
            },
        )
    ]
    connection.close.assert_called_once_with()
    assert row["headings"] == ["Item 8", "Financial Statements"]
    assert row["pages"] == [28, 29]
    assert row["source_refs"] == ["#/texts/101", "#/tables/4"]


def test_pgvector_retriever_defaults_to_unfiltered_search(monkeypatch):
    retriever, _, _, connection, register_vector, search = make_retriever(monkeypatch)

    assert retriever.invoke("revenue") == []

    search.assert_called_once_with(
        connection,
        [0.1, 0.2, 0.3],
        limit=5,
        company=None,
        fiscal_year=None,
    )
    register_vector.assert_called_once_with(connection)
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("limit", [1, 100])
def test_pgvector_retriever_accepts_search_limit_boundaries(monkeypatch, limit):
    retriever, _, _, connection, _, search = make_retriever(monkeypatch, limit=limit)

    retriever.invoke("operating income")

    assert search.call_args.kwargs["limit"] == limit
    connection.close.assert_called_once_with()


def test_pgvector_retriever_returns_empty_list_for_no_matches(monkeypatch):
    retriever, _, connection_factory, connection, _, _ = make_retriever(monkeypatch)

    result = retriever.invoke("a valid query with no matching evidence")

    assert result == []
    connection_factory.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_embedding_error_propagates_without_opening_database_connection(monkeypatch):
    error = RuntimeError("embedding service unavailable")
    embeddings = FakeEmbeddings(error=error)
    retriever, _, connection_factory, connection, register_vector, search = make_retriever(
        monkeypatch,
        embeddings=embeddings,
    )

    with pytest.raises(RuntimeError, match="embedding service unavailable") as raised:
        retriever.invoke("Apple revenue")

    assert raised.value is error
    connection_factory.assert_not_called()
    register_vector.assert_not_called()
    search.assert_not_called()
    connection.close.assert_not_called()


def test_search_error_propagates_and_connection_is_closed(monkeypatch):
    error = RuntimeError("database search failed")
    search = Mock(side_effect=error)
    retriever, embeddings, connection_factory, connection, register_vector, _ = make_retriever(
        monkeypatch,
        search=search,
    )

    with pytest.raises(RuntimeError, match="database search failed") as raised:
        retriever.invoke("Apple revenue")

    assert raised.value is error
    assert embeddings.queries == ["Apple revenue"]
    connection_factory.assert_called_once_with()
    register_vector.assert_called_once_with(connection)
    connection.close.assert_called_once_with()


def test_pgvector_adapter_is_registered_once_before_search(monkeypatch):
    events = []
    connection = Mock(name="connection")
    connection.close.side_effect = lambda: events.append("close")
    register_vector = Mock(name="register_vector", side_effect=lambda _: events.append("register"))
    search = Mock(name="search", side_effect=lambda *_args, **_kwargs: events.append("search") or [])
    retriever, _, connection_factory, _, _, _ = make_retriever(
        monkeypatch,
        connection=connection,
        register_vector=register_vector,
        search=search,
    )
    connection_factory.side_effect = lambda: events.append("open") or connection

    retriever.invoke("Apple revenue")

    assert events == ["open", "register", "search", "close"]
    register_vector.assert_called_once_with(connection)


def test_registration_error_propagates_without_search_and_connection_is_closed(monkeypatch):
    error = RuntimeError("pgvector registration failed")
    register_vector = Mock(name="register_vector", side_effect=error)
    retriever, _, connection_factory, connection, _, search = make_retriever(
        monkeypatch,
        register_vector=register_vector,
    )

    with pytest.raises(RuntimeError, match="pgvector registration failed") as raised:
        retriever.invoke("Apple revenue")

    assert raised.value is error
    connection_factory.assert_called_once_with()
    register_vector.assert_called_once_with(connection)
    search.assert_not_called()
    connection.close.assert_called_once_with()


def test_pgvector_registered_adapter_can_dump_numpy_array_without_database():
    context = Mock(connection=None, adapters=AdaptersMap())
    register_vector_info(context, TypeInfo("vector", oid=12345, array_oid=0))
    vector = np.asarray([0.1, 0.2, 0.3], dtype=np.float32)

    dumper = Transformer.from_context(context).get_dumper(vector, PyFormat.AUTO)

    assert dumper.oid == 12345
    assert dumper.dump(vector)


@pytest.mark.parametrize(
    ("query", "expected_error"),
    [
        (None, TypeError),
        (123, TypeError),
        (b"revenue", TypeError),
        ("", ValueError),
        ("   \t\n", ValueError),
    ],
)
def test_invalid_query_is_rejected_before_embedding_or_database_work(monkeypatch, query, expected_error):
    retriever, embeddings, connection_factory, connection, register_vector, search = make_retriever(monkeypatch)

    with pytest.raises(expected_error):
        retriever.invoke(query)

    assert embeddings.queries == []
    connection_factory.assert_not_called()
    register_vector.assert_not_called()
    search.assert_not_called()
    connection.close.assert_not_called()


@pytest.mark.parametrize("limit", [True, False, 1.5, "5", None])
def test_limit_must_be_an_integer(limit):
    with pytest.raises(TypeError):
        PgVectorRetriever(
            embeddings=FakeEmbeddings(),
            connection_factory=Mock(),
            limit=limit,
        )


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_limit_must_be_within_store_bounds(limit):
    with pytest.raises(ValueError):
        PgVectorRetriever(
            embeddings=FakeEmbeddings(),
            connection_factory=Mock(),
            limit=limit,
        )


@pytest.mark.parametrize("company", [123, b"Apple"])
def test_company_filter_must_be_a_string(company):
    with pytest.raises(TypeError):
        PgVectorRetriever(
            embeddings=FakeEmbeddings(),
            connection_factory=Mock(),
            company=company,
        )


@pytest.mark.parametrize("company", ["", "   \t\n"])
def test_company_filter_must_not_be_blank(company):
    with pytest.raises(ValueError):
        PgVectorRetriever(
            embeddings=FakeEmbeddings(),
            connection_factory=Mock(),
            company=company,
        )


@pytest.mark.parametrize("fiscal_year", [True, False, 2025.0, "2025"])
def test_fiscal_year_filter_must_be_a_non_boolean_integer(fiscal_year):
    with pytest.raises(TypeError):
        PgVectorRetriever(
            embeddings=FakeEmbeddings(),
            connection_factory=Mock(),
            fiscal_year=fiscal_year,
        )


@pytest.mark.parametrize("fiscal_year", [0, -1])
def test_fiscal_year_filter_must_be_positive(fiscal_year):
    with pytest.raises(ValueError):
        PgVectorRetriever(
            embeddings=FakeEmbeddings(),
            connection_factory=Mock(),
            fiscal_year=fiscal_year,
        )


def test_baseline_adapter_delegates_query_and_maps_documents_to_chunks():
    metadata: Mapping[str, Any] = {
        "chunk_id": "apple-2025-10k:42",
        "document_id": "apple-2025-10k",
        "company": "Apple",
        "fiscal_year": 2025,
        "quarter": "FY",
        "report_type": "10-K",
        "title": "2025 Form 10-K",
        "pages": (28, 29),
    }
    document = Document(page_content="Net sales were $416.161 billion.", metadata=dict(metadata))
    retriever = FakeDocumentRetriever([document])
    adapter = BaselineRetrieverAdapter(retriever=retriever)
    request = RetrievalRequest(
        query="Apple FY2025 net sales",
        required_facts=("net sales",),
        attempt=2,
    )

    chunks = adapter.invoke(request)

    assert retriever.inputs == ["Apple FY2025 net sales"]
    assert len(chunks) == 1
    assert isinstance(chunks[0], RetrievedChunk)
    assert chunks[0].text == "Net sales were $416.161 billion."
    assert chunks[0].metadata == metadata
    for expected_label_part in ("2025 Form 10-K", "Apple", "2025", "FY", "28", "29"):
        assert expected_label_part in chunks[0].source


@pytest.mark.parametrize(
    ("metadata", "expected_label_part"),
    [
        ({"source_path": "data/raw/fallback-report.pdf"}, "fallback-report.pdf"),
        ({"document_id": "fallback-document"}, "fallback-document"),
        ({"chunk_id": "fallback-chunk"}, "fallback-chunk"),
    ],
)
def test_baseline_adapter_builds_source_label_from_sparse_metadata(metadata, expected_label_part):
    document = Document(page_content="Evidence", metadata=metadata)
    adapter = BaselineRetrieverAdapter(retriever=FakeDocumentRetriever([document]))

    chunks = adapter.invoke(RetrievalRequest(query="evidence", required_facts=(), attempt=1))

    assert len(chunks) == 1
    assert expected_label_part in chunks[0].source
    assert chunks[0].metadata == metadata


def test_baseline_adapter_propagates_standard_retriever_errors():
    error = RuntimeError("retrieval failed")
    adapter = BaselineRetrieverAdapter(retriever=FakeDocumentRetriever(error))

    with pytest.raises(RuntimeError, match="retrieval failed") as raised:
        adapter.invoke(RetrievalRequest(query="Apple revenue", required_facts=(), attempt=1))

    assert raised.value is error
