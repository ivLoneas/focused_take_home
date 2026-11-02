"""LangChain retrieval over the ETL PostgreSQL/pgvector store."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pgvector.psycopg import register_vector

from agents.baseline.models import RetrievalRequest, RetrievedChunk
from agents.retrieval.models import QueryEmbeddings
from etl import store
from utils import require_nonblank_string

_METADATA_FIELDS = (
    "chunk_id",
    "document_id",
    "company",
    "fiscal_year",
    "quarter",
    "report_type",
    "title",
    "url",
    "source_path",
    "headings",
    "pages",
    "source_refs",
    "kind",
    "score",
)
_SEQUENCE_FIELDS = frozenset({"headings", "pages", "source_refs"})


class DocumentRetriever(Protocol):
    def invoke(self, query: str) -> Sequence[Document]: ...


class PgVectorRetriever(BaseRetriever):
    """Embed a query, apply optional report filters, and return provenance-rich chunks."""

    embeddings: QueryEmbeddings
    connection_factory: Callable[[], Any]
    limit: int = 5
    company: str | None = None
    fiscal_year: int | None = None

    def __init__(
        self,
        *,
        embeddings: QueryEmbeddings,
        connection_factory: Callable[[], Any],
        limit: int = 5,
        company: str | None = None,
        fiscal_year: int | None = None,
        **kwargs: Any,
    ) -> None:
        self._validate_configuration(limit=limit, company=company, fiscal_year=fiscal_year)
        super().__init__(
            embeddings=embeddings,
            connection_factory=connection_factory,
            limit=limit,
            company=company.strip() if company is not None else None,
            fiscal_year=fiscal_year,
            **kwargs,
        )

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del run_manager
        query = require_nonblank_string(query, field_name="query")

        vector = self.embeddings.embed_query(query)
        connection = self.connection_factory()
        try:
            register_vector(connection)
            rows = store.search(
                connection,
                vector,
                limit=self.limit,
                company=self.company,
                fiscal_year=self.fiscal_year,
            )
            return [self._to_document(row) for row in rows]
        finally:
            connection.close()

    @staticmethod
    def _validate_configuration(*, limit: int, company: str | None, fiscal_year: int | None) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be in 1..100")
        if company is not None:
            require_nonblank_string(company, field_name="company")
        if fiscal_year is not None:
            if isinstance(fiscal_year, bool) or not isinstance(fiscal_year, int):
                raise TypeError("fiscal_year must be an integer")
            if fiscal_year <= 0:
                raise ValueError("fiscal_year must be positive")

    @staticmethod
    def _to_document(row: Mapping[str, Any]) -> Document:
        metadata = {}
        for field in _METADATA_FIELDS:
            if field not in row:
                continue
            value = row[field]
            if field in _SEQUENCE_FIELDS and isinstance(value, list):
                value = tuple(value)
            metadata[field] = value
        return Document(page_content=row["text"], metadata=metadata)


class BaselineRetrieverAdapter:
    """Convert retrieved documents into the baseline graph's evidence contract."""

    def __init__(self, *, retriever: DocumentRetriever) -> None:
        self.retriever = retriever

    def invoke(self, request: RetrievalRequest) -> list[RetrievedChunk]:
        documents = self.retriever.invoke(request.query)
        return [
            RetrievedChunk(
                text=document.page_content,
                source=self._source_label(document.metadata),
                metadata=document.metadata,
            )
            for document in documents
        ]

    @staticmethod
    def _source_label(metadata: Mapping[str, Any]) -> str:
        title = metadata.get("title")
        source_path = metadata.get("source_path")
        primary = title or (Path(str(source_path)).name if source_path else None)
        primary = primary or metadata.get("document_id") or metadata.get("chunk_id") or "Unknown source"

        parts = [str(primary)]
        company = metadata.get("company")
        if company and str(company) not in parts[0]:
            parts.append(str(company))

        fiscal_year = metadata.get("fiscal_year")
        quarter = metadata.get("quarter")
        if fiscal_year:
            period = f"FY{fiscal_year}"
            if quarter and str(quarter).upper() not in {"FY", "ANNUAL"}:
                quarter_label = str(quarter)
                if not quarter_label.upper().startswith("Q"):
                    quarter_label = f"Q{quarter_label}"
                period = f"{period} {quarter_label}"
            parts.append(period)
        elif quarter:
            parts.append(str(quarter))

        pages = metadata.get("pages")
        if isinstance(pages, Sequence) and not isinstance(pages, (str, bytes)) and pages:
            page_values = [str(page) for page in pages]
            page_label = page_values[0] if len(page_values) == 1 else "-".join((page_values[0], page_values[-1]))
            parts.append(f"p. {page_label}")
        return " | ".join(parts)
