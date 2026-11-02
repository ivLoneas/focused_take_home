# Promptfoo evaluation workflow

This workflow runs every row in `evals_tests.csv` against the baseline LangGraph agent and records these evaluation
dimensions:

- `response_validity`: the provider returned a nonblank answer;
- `workflow_behavior`: routing, actual discovery tool calls and company arguments, retrieval attempts, and citations match each case;
- `answer_quality`: an OpenAI grader compares factual correctness with the reviewed answer and original question;
- `format_compliance`: for cases with `output_pattern`, a deterministic full-match check enforces the requested output.

The v2 judge accepts equivalent evidence from different retained reports or pages. Reviewed source locations are
non-exhaustive references; matching every reference or its page is not required. It preserves material units, fiscal
periods, signs, currency, and GAAP/non-GAAP distinctions. Inline citations or explanatory calculations are required
only when requested, and bare numeric answers use the question's requested units. Refusals and clarifications do
not need financial figures or report citations. The format check is separate from the factual judge: a correct value
with unwanted prose can pass quality while failing format compliance and the overall strict result.

## Prerequisites

The evaluation uses the same PostgreSQL/pgvector Gold store as the application. Complete the retrieval ETL first and
set these values in the repository-root `.env`:

```dotenv
OPENAI_API_KEY=...
DATABASE_URL=postgresql://rag:rag_local@localhost:55432/rag
```

Optional settings are `EVAL_CHAT_MODEL`, `EVAL_EMBEDDING_MODEL`, `EVAL_EMBEDDING_DIMENSIONS`,
`EVAL_RETRIEVAL_LIMIT`, `EVAL_MAX_RETRIEVAL_ATTEMPTS`, and `EVAL_DATABASE_URL`. The embedding model and dimensions
must match the vectors published by ETL.

Promptfoo 0.125.1 requires Node.js 22.22 or later. Install and run it from the repository root:

```sh
npm --prefix evals install
npm --prefix evals run eval
```

For a fresh measured run with exported results and the root credentials:

```sh
mkdir -p reports
npm --prefix evals run eval -- --env-file ../.env --no-cache --no-share -o ../reports/baseline.json
```

The provider exports per-question answer latency, nested chat-model token usage (including cached and reasoning
tokens), embedding API usage, and retrieval calls, errors, empty results, chunks, and cumulative retrieval latency in
`response.metadata`. Retrieval rounds and company-specific retrieval calls are separate counts. Chat tokens also
populate Promptfoo's `tokenUsage`; grader usage remains separate in `gradingResult.tokensUsed`. The provider's cost
field is not a billed-dollar measurement: calculate estimates from usage and dated model pricing.

For agent-based LangSmith workspaces, set `LANGSMITH_AGENT_ID` and `LANGSMITH_AGENT_ENVIRONMENT` together and use
the workspace's regional `LANGSMITH_ENDPOINT`. The baseline sends traces to that explicit agent address; without
the pair it uses `LANGSMITH_PROJECT`. Look under the agent's Tracing tab and selected environment. Never put API
keys into exported configuration or reports.

Promptfoo runs one case at a time with a five-minute per-case timeout. The target provider uses the repository's
virtual environment; the LLM rubric uses `openai:gpt-5-mini`. Results remain local under Promptfoo's storage. To open
the result viewer:

```sh
npm --prefix evals run view
```

Use Promptfoo filters while iterating on one category or case, for example:

```sh
cd evals
PYTHONPATH=.. PROMPTFOO_PYTHON=../.venv/bin/python npx promptfoo@0.125.1 eval -c promptfooconfig.yaml --filter-pattern ACC01
```

The 114 scenarios retain the previous 104 case IDs, including four coverage discovery cases, and append ten
`formatting_questions` (`FMT01`–`FMT10`). These cover number-only and company-name-only answers, millions/billions
conversion, negative signs, and decimal precision. `output_pattern` must be a valid Python regex and is mandatory
for this topic. The entire trimmed response must match; prose, citations, code fences, and extra internal lines fail.
The checker verifies shape, while the judge verifies the value. Existing cases retain their three checks, and the
formatting cases have four. CSV fields `required_tools` and
`required_period_companies` require actual calls recorded by the graph, including one period lookup for each
comparison company. `allow_no_retrieval=true` permits verified metadata-only answers for coverage listings and known
company/period gaps. Supported financial answers still require report retrieval and citations. Discovery calls are
exported as `response.metadata.tool_calls` and remain nested tool runs in LangSmith.

`AMB04` is now a deterministic-accuracy case, retaining its historical ID. Because its question permits the annual
report's fiscal period, a direct FY2025 sales answer with the fiscal year-end date is expected; clarification is not
required. Topic counts are eleven deterministic-accuracy cases, nine ambiguous cases, fourteen tool-usage cases,
and ten for each remaining topic. Historical saved runs and scores are not rewritten when the dataset changes.

The CSV generator validates required headers, blank values, duplicate IDs, discovery flags, output patterns, and the supported topic list before any
model calls are made. Pytest covers the workflow without calling OpenAI, PostgreSQL, Node.js, or Promptfoo:

```sh
uv run pytest -q tests/evals
```
