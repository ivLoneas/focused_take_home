# Baseline financial-report agent

## Architecture

`baseline_agent.py` implements `baseline.png` as a compiled LangGraph workflow. Workflow contracts live in `models.py`,
tool implementations and contracts live in [`../tools`](../tools/README.md), and the three focused prompt templates
live in `prompts/templates.py`:

```text
question
  -> plan scope, companies, missing details, and required facts
  -> listed_companies, then company_periods for relevant companies
  -> analyze verified coverage and plan retrieval
     -> coverage listing or known company/period gap: formulate an answer from discovery results
     -> out of domain: return a bounded response
     -> missing details: ask one specific clarification question
     -> retrieve evidence
        -> assess whether every required fact is supported
           -> insufficient and attempts remain: refine query and retrieve again
           -> sufficient or three attempts used: formulate an evidence-bound answer
```

The workflow state keeps the original question, structured analysis, current retrieval query, raw retrieved chunks,
attempt count, sufficiency decision, and final response. Nodes return state updates; conditional edges own routing.

## Public interface

- `AgentConfig(model="gpt-5-mini")` validates the selected model name and LangSmith configuration. It reads the model
  override from `AGENT_MODEL`.
- `BaselineAgent(model, retriever=placeholder_retriever, max_retrieval_attempts=3, config=None, coverage=None)` compiles the workflow
  once and loads `AgentConfig` when none is supplied. The injected model keeps construction and testing independent of
  a specific provider client.
- `BaselineAgent.invoke(question)` returns `BaselineResult` with `status`, `answer`, `citations`, and
  `retrieval_attempts`, and discovery `tool_calls`.
- `RetrievalRequest` is the retriever input: required company literal, focused query, required facts, and one-based round number.
- `RetrievedChunk` is the temporary retriever output: evidence text, a human-readable source label, and metadata.

The model must implement the LangChain chat-model interface, including `invoke` and `with_structured_output`.
The retriever can be a callable or a LangChain-style object with `invoke`.

```python
from functools import partial

import psycopg
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings

from agents.baseline.baseline_agent import BaselineAgent
from agents.settings import AgentConfig
from agents.tools import BaselineRetrieverAdapter, DatabaseCoverage, PgVectorRetriever

config = AgentConfig()
model = ChatOpenAI(model=config.model, temperature=0)
retriever = PgVectorRetriever(
    embeddings=OpenAIEmbeddings(model="text-embedding-3-small", dimensions=1536),
    connection_factory=partial(psycopg.connect, "<database-url>"),
    company="Apple",
    fiscal_year=2025,
)
agent = BaselineAgent(
    model,
    retriever=BaselineRetrieverAdapter(retrievers={"Apple": retriever}),
    coverage=DatabaseCoverage(connection_factory=partial(psycopg.connect, "<database-url>")),
    config=config,
)
result = agent.invoke("What were Apple's net sales in FY2025?")
```

`PgVectorRetriever` is a standard LangChain `BaseRetriever`, so other LangChain agents can use it directly and receive
`Document` objects. It accepts any injected embedding implementation with `embed_query`; that implementation must
produce vectors compatible with the embeddings already stored in pgvector. Company is required at construction;
the fiscal-year filter is optional. Every returned document retains the ETL citation and provenance metadata.
The backend and evaluation provider register the company-bound retrievers and lazy `DatabaseCoverage` tools.
`QuestionAnalysis.companies` accepts company names for discovery, including names absent from the database.
After discovery, supported factual requests must select at least one verified company. Retrieval still validates
against the configured physical company tables; adding new retrieval tables is a separate ETL change.
Each round calls the structured retrieval tool separately per selected company and searches only its mapped physical
table. Repeated companies are deduplicated. Google maps to Alphabet and Facebook to Meta during question analysis.

## Implementation highlights

- The 3 November 2026 prompt alignment uses the revised evaluation policy: bounded profit/earnings/margin terms
  receive labeled alternatives; broad results/performance, unidentified companies, and unspecified growth/spending
  receive one specific clarification. Verified missing coverage stays in domain and returns `answered` with a
  concise company/filing/period gap, retaining supported parts of mixed requests. No external-search offers.
- Answers normally use one or two factual sentences. Exact number/company/CSV/JSON requests may omit inline
  citations, while retrieval provenance remains in `BaselineResult.citations`. Units, signs, precision, material
  fiscal periods, grounding and untrusted-evidence protections still apply. Few-shot figures are hypothetical.
- This alignment changes prompt text only. The original graph, single-model configuration, discovery sequence,
  retrieval loop and tracing remain independent of v2. Compare both through
  `evals/promptfooconfig.aligned_comparison.yaml` on the same frozen dataset/grader.
- Pydantic structured outputs make scope and context-sufficiency decisions explicit and validated.
- Prompt roles and decision rules are explicit, and each prompt is limited to one workflow responsibility.
- Prompts contain no company/period inventory. The graph first plans discovery, calls `listed_companies` and
  `company_periods`, then routes using their results in message context. A general coverage listing checks every
  company's periods; factual requests check only the relevant companies. Question analysis only plans and routes;
  coverage listings and verified gaps use final answer generation without report retrieval. Financial facts still
  require retrieved evidence with source pages.
- `etl_documents` remains the individual-quarter source of truth. `company_periods` merges adjacent quarters only
  when returning intervals; annual report years come from annual filing rows, without inferring missing quarters.
- Discovery calls are standard LangChain structured tools, nested under the invocation trace. Database errors
  propagate, and each call closes its connection. `BaselineResult.tool_calls` records actual names and arguments.
- Retrieved evidence is delimited and labeled as untrusted data; the model is told to ignore embedded instructions and
  avoid prior knowledge. This reduces, but cannot eliminate, indirect prompt-injection risk.
- Out-of-domain and clarification branches are deterministic after routing and never call retrieval or answer generation.
- Retrieved evidence is accumulated across refined-query attempts and retains citation metadata.
- Retrieval is capped at three rounds by default, with one call per selected company in each round; the final prompt
  explicitly receives the sufficiency decision.
- Unexpected model and retriever errors propagate so a failed run cannot silently become an unsupported answer.
- When `LANGSMITH_TRACING=true`, the root workflow, graph nodes, model calls, and standard LangChain retriever calls are
  recorded in the configured LangSmith project with baseline tags and non-sensitive run metadata, including the
  configured model name.
- The independent unit suite uses deterministic fakes and exercises happy paths, edge cases, invalid inputs, and failures.

## Current limitations

- Direct test callers may omit `coverage`; production and evaluation builders always inject database discovery.
  Without a coverage dependency, the graph has no verified inventory.
- The default `placeholder_retriever` still returns no evidence. Callers must configure `PgVectorRetriever` and wrap it
  with `BaselineRetrieverAdapter(retrievers={company: retriever, ...})`; available coverage depends on published Gold rows.
- Each invocation is stateless. A clarification response is returned to the caller, which must submit a new complete
  question; the graph does not pause and resume a conversation.
- Scope classification, fact planning, sufficiency assessment, and final citation use still depend on model quality.
- Citation labels are passed through from retrieval; the baseline does not verify that every generated claim cites a
  supporting chunk.
- Prompt-level defenses cannot guarantee safety against indirect prompt injection; there is no output-grounding or
  citation-entailment validator yet.
- The synchronous workflow has no context-size budget, reranker, hybrid retrieval, per-request fiscal-year filters, or
  deduplication of semantically repeated chunks.
- LangSmith persists execution traces and exposes latency, errors, and model token usage. Server-side alerting and
  online quality evaluators still need to be configured in the LangSmith project.

## TODO

1. Run the Promptfoo scenarios against the baseline and tune prompts, search limits, retry behavior, and the model from
   measured failure categories.
2. Configure LangSmith dashboards, alerts, sampling, and online evaluators for production monitoring.
3. Add citation-entailment checks and a bounded context selection/reranking step if evaluation results justify them.
