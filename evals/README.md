# Promptfoo evaluation workflow

This workflow runs every row in `evals_tests.csv` against the baseline LangGraph agent and records three independent
metrics:

- `response_validity`: the provider returned a nonblank answer;
- `workflow_behavior`: routing, retrieval attempts, and citations match the scenario category;
- `answer_quality`: an OpenAI grader compares the answer with the reviewed answer, source, and annotations.

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

The CSV generator validates required headers, blank values, duplicate IDs, and the supported topic list before any
model calls are made. Pytest covers the workflow without calling OpenAI, PostgreSQL, Node.js, or Promptfoo:

```sh
uv run pytest -q tests/evals
```
