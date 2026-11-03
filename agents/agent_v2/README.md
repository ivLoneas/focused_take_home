# Financial-report agent v2

`AgentV2` is an opt-in LangGraph workflow. The baseline and its prompts remain independent.

```
question -> Jev domain judgments -> bounded refusal
                               -> discovery of all listed company periods -> Luna plan
                                      -> essential clarification / coverage answer
                                      -> retrieve per company -> Luna evidence check -> refine
                                                             -> Terra answer
```

Coverage is discovered deterministically before the single planning call. With the current five-company corpus,
these extra local metadata queries replace a model round trip and prevent incomplete discovery plans.

Defaults: `gpt-6-luna` handles planning and sufficiency, `gpt-6.1-terra` answers, and `jev-latest` screens domain.
The Promptfoo builder uses low reasoning for routing and answers. These are experiment
settings, not a guarantee that smaller models retain quality. The last retrieval round goes straight to answering,
where support is checked again; it is never marked sufficient simply because the retry limit was reached.
Exact repeated evidence is removed; provenance differences are preserved. Retrieval still uses the pinned
100-report database, company-specific pgvector tables, and the existing discovery tools.

Common ambiguity produces labeled alternatives, including revenue/net income and fiscal/calendar interpretations
for “What was Amazon's earnings in 2025?”. Periods are combined only when report evidence establishes matching
dates. Unknown companies such as “it” still need clarification. Source/page references are required unless a user
asks for a specific formatting; bare answers keep retrieved provenance in `result.citations`. There is no answer
rewriting or citation stripping after generation.

Chart/table prompts check panel, series, row, column, total/segment, quarter/annual, units, and accounting basis.
This is a text/description-based retrieval agent, not a new vision or extraction pipeline. Missing chart titles
and other extraction limitations can still prevent a supported answer.

## Configuration and API

Add these server-side settings to the project-root `.env`:

```dotenv
TYPESAFE_API_KEY=...
TYPESAFE_MODEL=jev-latest
TYPESAFE_TIMEOUT_SECONDS=15
AGENT_MODEL=gpt-6.1-terra
AGENT_V2_ROUTING_MODEL=gpt-6-luna
```

`AgentV2Config` inherits existing `LANGSMITH_*` configuration and validation. Enabled tracing requires a nonblank
LangSmith key and a valid destination. Jev runs as a LangChain chat model, preserving the exact JSON request,
validated response, resolved model ID, usage and errors beneath the invocation trace. API keys are sent in HTTP
headers only and excluded from model serialization and run metadata. Exceptions propagate; an API failure is
never converted to a refusal. A gate owns its HTTP client unless one is injected; call `gate.close()` on shutdown.

```python
from langchain_openai import ChatOpenAI
from agents.agent_v2 import AgentV2, AgentV2Config, JevDomainGate

config = AgentV2Config()
gate = JevDomainGate(config)
agent = AgentV2(
    ChatOpenAI(model=config.model, reasoning_effort="low"),
    routing_model=ChatOpenAI(model=config.routing_model, reasoning_effort="low"),
    domain_gate=gate,
    config=config,
    retriever=your_retriever_adapter,
    coverage=your_database_coverage,
)
result = agent.invoke("What was Amazon's earnings in 2025?")
gate.close()
```

Both models, the gate, coverage and retrieval are injectable. An optional `planning_model` owns only the planning
stage; omitting it or passing `None` uses `routing_model` for planning and sufficiency as before. This enables
separate planner experiments without changing the default evaluation configuration. The result uses the existing
`BaselineResult` contract.
`BaselineAgent` (v1) and `AgentV2` are sibling implementations of `FinancialReportAgent` in `agents/workflow.py`.
The shared base owns tracing, validation, retrieval and deterministic routing helpers; each version owns its graph
and model/prompt policy. Shared contracts live in `agents/models.py`; `BaselineResult` remains a compatible alias
for `AgentResult`. The application backend remains on the baseline until deliberately
switched; v2 can be evaluated without changing the demo.

## Jev policy

Two independent Noul judgments share the original question state. The question wording and thresholds live in
`ood.py`. No corpus inventory is guessed by the gate.

| Report question probability | Investment advice probability | Code action |
| --- | --- | --- |
| < 0.3 | Any | Refuse |
| >= 0.3 | >= 0.7 | Refuse |
| >= 0.3 | < 0.7 | Continue to discovery/planning |

Uncertain judgments proceed to the evidence-bound workflow. Financial questions about unavailable companies or
periods stay in domain; discovery explains missing coverage. HTTP, timeout and invalid-schema errors fail clearly.

API contract verified against [TypeSafe HTTP docs](https://docs.typesafe.ai/api/system-one.md),
[models/pricing](https://docs.typesafe.ai/models.md), and
[known model limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md).
The alias may change; traces record the resolved model. Jev 1.14 pricing observed 2 November 2026 is
$0.042 per million input tokens, with free output. OpenAI pricing is recorded separately in evaluation reports.

## Evaluation

The [completion review](../../reports/agent-v2-completion/report.md) audits the implementation commits and saved
live results, compares them with baseline v2, and records current test/replay validation and live-run prerequisites.

From `evals/`, using the existing installed Promptfoo and project Python environment:

```sh
PYTHONPATH=.. PROMPTFOO_PYTHON=../.venv/bin/python npx promptfoo eval \
  -c promptfooconfig.agent_v2.yaml --env-file ../.env --no-cache --no-share \
  -o ../reports/agent-v2/promptfoo.json
```

The 3 November 2026 revision keeps 114 case IDs but replaces five bounded-interpretation ambiguity questions
with genuinely underspecified requests; saved historical results retain their original questions and scores.
`agent_v2_cases.csv` separately tests answerable profit/earnings, explicit period alternatives, margins, and exact
formatting. Broad results/performance, unidentified companies and unspecified growth need one clarification.
Known company/filing/period coverage gaps instead finish as `answered` with a concise explanation. Jev input/output counts are included in total tokens and separately
attributed under `metadata.telemetry.by_model`; free Jev output tokens must not be priced like OpenAI output tokens.
