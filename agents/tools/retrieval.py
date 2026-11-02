"""LangChain retrieval over the ETL PostgreSQL/pgvector store."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import StructuredTool
from pgvector.psycopg import register_vector

from agents.tools.models import (
    DocumentRetriever,
    QueryEmbeddings,
    RetrievalRequest,
    RetrievalToolInput,
    RetrievedChunk,
    Retriever,
)
from etl import store
from etl.companies import Company, require_company
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

RETRIEVAL_DESCRIPTION = """Search public financial-report evidence for exactly one required company.
company must be one of these literals, each selecting only its dedicated vector table:
"Alphabet" -> etl_chunks_alphabet; "Amazon" -> etl_chunks_amazon;
"Apple" -> etl_chunks_apple; "Meta" -> etl_chunks_meta; "Netflix" -> etl_chunks_netflix.
query must specify the fiscal period, metric, and report type needed.
Google maps to Alphabet; Facebook maps to Meta. Use the canonical company literal in arguments.
For comparisons, make a separate call per company and combine the cited evidence.
There is no unfiltered or cross-company search and no external sourcing.
"""


def placeholder_retriever(_: RetrievalRequest) -> list[RetrievedChunk]:
    """Return empty evidence when no retrieval backend is configured."""

    return []


def invoke_retriever(retriever: Retriever, request: RetrievalRequest) -> list[RetrievedChunk]:
    """Invoke an injected retrieval tool and materialize its evidence, preserving failures."""

    require_company(request.company)
    if callable(retriever):
        retrieve = cast(Callable[[RetrievalRequest], Sequence[RetrievedChunk]], retriever)
        return list(retrieve(request))
    invoke = getattr(retriever, "invoke", None)
    if callable(invoke):
        return list(invoke(request))
    raise TypeError("retriever must be callable or provide invoke(request)")


class PgVectorRetriever(BaseRetriever):
    """Search one required company's vector table with an optional fiscal-year filter."""

    embeddings: QueryEmbeddings
    connection_factory: Callable[[], Any]
    limit: int = 5
    company: Company
    fiscal_year: int | None = None

    def __init__(
        self,
        *,
        embeddings: QueryEmbeddings,
        connection_factory: Callable[[], Any],
        limit: int = 5,
        company: Company,
        fiscal_year: int | None = None,
        **kwargs: Any,
    ) -> None:
        self._validate_configuration(limit=limit, company=company, fiscal_year=fiscal_year)
        super().__init__(
            embeddings=embeddings,
            connection_factory=connection_factory,
            limit=limit,
            company=company,
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
        require_company(self.company)

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
    def _validate_configuration(*, limit: int, company: Company, fiscal_year: int | None) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be in 1..100")
        require_company(company)
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

    def __init__(self, *, retrievers: Mapping[Company, DocumentRetriever]) -> None:
        for company, retriever in retrievers.items():
            require_company(company)
            configured_company = getattr(retriever, "company", None)
            if isinstance(configured_company, str) and configured_company != company:
                raise ValueError(f"Retriever for {company} is configured for {configured_company}")
        self.retrievers = dict(retrievers)
        self.tool = StructuredTool.from_function(
            self._retrieve,
            name="retrieve_company_reports",
            description=RETRIEVAL_DESCRIPTION,
            args_schema=RetrievalToolInput,
        )

    def as_tool(self) -> StructuredTool:
        """Expose required company/query arguments for other LangChain agents."""
        return self.tool

    def invoke(self, request: RetrievalRequest) -> list[RetrievedChunk]:
        require_company(request.company)
        return self.tool.invoke({"company": request.company, "query": request.query})

    def _retrieve(self, company: Company, query: str) -> list[RetrievedChunk]:
        company = require_company(company)
        query = require_nonblank_string(query, field_name="query")
        if company not in self.retrievers:
            raise ValueError(f"No retrieval backend configured for {company}")
        documents = self.retrievers[company].invoke(query)
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
