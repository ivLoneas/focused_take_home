# Agent tools

Discovery and retrieval tools live here; the baseline graph owns question analysis, retries, and accumulated context.

| File | Responsibility |
| --- | --- |
| [`coverage.py`](coverage.py) | Discover companies and quarter intervals from published database rows. |
| [`retrieval.py`](retrieval.py) | Invoke retrieval, query pgvector, and format source labels. |
| [`models.py`](models.py) | Retrieval requests, evidence chunks, and dependency protocols. |
| [`__init__.py`](__init__.py) | Public imports for workflows, backend wiring, and evaluations. |

## Retrieval flow

```text
BaselineAgent retrieval node creates a RetrievalRequest
  -> invoke_retriever calls the injected callable or invoke(request)
  -> BaselineRetrieverAdapter validates request.company and invokes its structured tool
  -> tool selects exactly one company-bound PgVectorRetriever
  -> PgVectorRetriever embeds request.query and searches only that company's Gold table
  -> adapter converts Documents to RetrievedChunks with source names and pages
  -> graph accumulates chunks and assesses whether more retrieval is needed
```

`RetrievalRequest.company` is required and typed as `Literal["Alphabet", "Amazon", "Apple", "Meta", "Netflix"]`.
The model's `QuestionAnalysis.companies` plans arbitrary company names, then selects verified companies after discovery. Comparisons make a separate tool
call per company on each retrieval round; the retry limit counts rounds. Google maps to Alphabet and Facebook to Meta
during question analysis. Missing or unsupported company arguments fail before embeddings or database access.

| Required company literal | Physical vector table |
| --- | --- |
| `Alphabet` | `etl_chunks_alphabet` |
| `Amazon` | `etl_chunks_amazon` |
| `Apple` | `etl_chunks_apple` |
| `Meta` | `etl_chunks_meta` |
| `Netflix` | `etl_chunks_netflix` |

`PgVectorRetriever` requires a canonical company at construction and supports an optional fiscal-year filter. It preserves provenance metadata and closes its
database connection after each search, including failures. Its LangChain `BaseRetriever` interface preserves nested
retrieval tracing when called inside the graph. Embeddings must match those used to build the Gold index. Each table
has its own HNSW and full-text indexes; fiscal-year filters use exact search to avoid ANN post-filter under-filling.

Construct `BaselineRetrieverAdapter(retrievers={company: company_retriever, ...})`. Its `as_tool()` exposes
`retrieve_company_reports` with required `company` and `query` arguments, a literal company enum, and the complete
table mapping in the description. The graph also invokes this structured tool, preserving nested tool and retriever
traces. There is no default company or all-company fallback.

`invoke_retriever` materializes returned evidence as a list and propagates failures. The default
`placeholder_retriever` returns empty evidence; backend and evaluation wiring inject the pgvector adapter.

Import tools from `agents.tools` and their input/output contracts from `agents.tools.models`.

## Available data tools

Construct `DatabaseCoverage(connection_factory=...)`. Its `listed_companies` and `company_periods` attributes are
LangChain `StructuredTool` objects, so callers use `.invoke({})` and `.invoke({"company": "Apple"})` respectively.
The backend and Promptfoo provider inject them into `BaselineAgent(coverage=...)` without connecting at startup.

`listed_companies` returns sorted, distinct names from `etl_documents`, including newly published companies.
`company_periods` queries the individual `(fiscal_year, quarter, report_type)` rows for one company and returns:

```json
{"company": "ExampleCo", "intervals": ["Q3FY2025-Q2FY2026", "Q4FY2026"], "annual_reports": ["FY2025"]}
```

Duplicate reports do not duplicate quarters. Missing quarters split intervals; singleton quarters remain single
labels. Annual report years are reported independently and do not imply four available quarters. Unknown companies
return empty lists. Inputs are validated before connecting, SQL values are parameterized, database errors propagate,
and connections close after success or failure. Results are queried afresh each time and do not read manifests.
