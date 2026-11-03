# Agent v2 — completed development and live evaluations

The fresh uncached **114-case evaluation completed: 83/114 (72.8%) strict passes, 31 assertion failures, and 0 runtime errors**. The separate paired behavior suite completed all 18 invocations: **v2 8/9 (88.9%) versus baseline 3/9 (33.3%)**. All requested runs are complete; credentials are working.

## Development and environment

- Audited `cdca078` (baseline/retrieval/evaluation refactoring) and `5012436` (v2 implementation, tests, and saved evaluations). Three committed tests exposed an unfinished optional planning-model API.
- Completed `AgentV2(..., planning_model=None)`: a supplied model owns only planning after domain screening and discovery; omitted/None keeps nano routing/planning. Independent tests cover model ownership, default/None fallback, discovery order, domain rejection, and exception propagation.
- **850 Python tests passed**, including PostgreSQL integration tests; no failures or skips. Ruff passed for the changed Python files. These checks were completed before the live runs; the implementation stayed unchanged throughout evaluation.
- Migrated the local Gold database using the committed transactional migration. Before/after checksums confirm all 20,274 chunks and embeddings were preserved; all 100 document paths/checksums match the pinned manifest. No source PDFs, ETL extraction, embeddings, grader, or case datasets were changed.
- Corrected local `LANGSMITH_ENDPOINT` to `https://eu.api.smith.langchain.com`. The provided key is an EU tracing key. Trace ingestion works; project/readback access is not included in its permissions. No additional credentials are required to run.

## Historical-suite comparison

| Measure | Historical baseline | Previous v2 | Fresh v2 |
| --- | ---: | ---: | ---: |
| Strict pass | 84/114 (73.7%) | 88/114 (77.2%) | 83/114 (72.8%) |
| Runtime errors | 1 | 0 | 0 |
| Factual quality | 98/113 | 96/114 | 91/114 |
| Workflow | 100/113 | 96/114 | 92/114 |
| Response validity | 113/113 | 114/114 | 114/114 |
| Exact format | 0/10 | 10/10 | 10/10 |
| Mean answer latency | 33.83s | 12.82s | 12.98s |
| Median answer latency | 31.49s | 12.70s | 12.00s |
| p95 answer latency | 69.04s | 24.62s | 24.92s |

AMB04's contract changed between the original baseline and v2: it now accepts the annual-report fiscal period and requires a direct answer. Excluding that case gives a matched **84/113 (74.3%) baseline versus 82/113 (72.6%) fresh v2**. The previous v2 and fresh v2 use the same 114-case contract. No historical scores were rewritten.

Factual quality is the LLM judge result, not an independent proof that each citation entails the answer. Strict pass requires every applicable check. Latency covers completed answers only and excludes judge time; runtime errors remain in the strict denominator. These are single runs, so changes can reflect model/grader variability. The optional planner is not enabled in this provider; the fresh run measures the existing nano-planning default.

The fresh evidence does not support replacing the historical baseline on strict accuracy: matched-contract v2 is 1.7 percentage points lower. It does support the v2 policy on its dedicated behavior suite and shows substantially lower latency and exact-format compliance. The clearest next experiment is to inject GPT-5 mini through the new `planning_model` boundary while leaving nano on evidence assessment, then rerun both suites unchanged. All ten missing-data failures currently exit as `needs_clarification` with zero retrieval attempts despite completed coverage discovery, so planning/coverage routing is the highest-value target. This recommendation is not a measured improvement claim.

| Topic | Baseline | Previous v2 | Fresh v2 |
| --- | ---: | ---: | ---: |
| deterministic_accuracy | 6/10 | 11/11 | 11/11 |
| tool_usage | 13/14 | 11/14 | 12/14 |
| out_of_distribution | 10/10 | 10/10 | 10/10 |
| multiple_companies | 10/10 | 10/10 | 9/10 |
| conditional_reasoning | 8/10 | 10/10 | 10/10 |
| in_domain_no_data | 7/10 | 2/10 | 0/10 |
| extra_calculation | 9/10 | 10/10 | 7/10 |
| ambiguous_questions | 8/10 | 2/9 | 0/9 |
| image_questions | 5/10 | 4/10 | 5/10 |
| table_questions | 8/10 | 9/10 | 10/10 |
| formatting_questions | 0/10 | 9/10 | 9/10 |

## Changed outcomes and remaining failures

Improved versus the previous v2 run: IMG03, TAB02, COV03.

Regressed versus the previous v2 run: MUL07, NOD01, NOD04, CAL04, CAL07, CAL08, AMB01, AMB07.

Historical ambiguity cases can fail workflow even when their factual answer passes, because they demand clarification rather than bounded interpretations. The versioned behavior suite measures the intended v2 policy separately. Coverage, chart selection, units and comparative-period failures remain genuine limitations when factual quality fails; they are not excused by the policy difference.

| Case | Status | Failed checks | Reason |
| --- | --- | --- | --- |
| TOOL08 | answered | answer_quality | The assistant claimed the Q4 Google Cloud revenue and operating margin were not present in the supplied evidence and offered to search for the page, but the Q4 2025 earnings slides do contain those figures (Google Cloud revenue $17.664 billion and operating margin 30.1%). The response therefore failed to provide the requested numeric answer and incorrectly reported the data as unavailable. |
| MUL07 | answered | answer_quality | The assistant correctly retrieved Apple's FY2025 revenue (416.161B) and summed, but used Amazon as $716.9B (rounded) rather than the expected $716.924B. That produces $1.133061T instead of the expected $1.133085T — a $24M (0.002%) shortfall. Because the combined total does not match the expected precise sum, this does not meet the rubric threshold. |
| NOD01 | needs_clarification | workflow_behavior | NOD01 must finish with status answered, got needs_clarification |
| NOD02 | needs_clarification | workflow_behavior, answer_quality | The assistant merely asked for confirmation to search for those annual reports instead of stating the required corpus boundary. The rubric expects the assistant to verify the active corpus and, if Samsung and Intel are not present, to state that concrete coverage gap (and not attempt external browsing or invent figures). This output fails to report the coverage gap or refuse per the constraint, so it does not meet the expected behavior. |
| NOD03 | needs_clarification | workflow_behavior, answer_quality | The assistant just repeated the user's request as a clarifying question and did not state the corpus coverage gap or refuse with a specific explanation. The rubric requires, for unavailable FY2026 annual-report data in the active corpus, a concrete coverage statement (e.g., that only FY2026 Q1–Q3 reports are present and the FY2026 annual report is not in the active corpus) rather than this open confirmation prompt. Therefore it fails the expected behavior. |
| NOD04 | needs_clarification | workflow_behavior, answer_quality | The assistant correctly identified the coverage gap (corpus contains only Q4FY2025–Q3FY2026 and no Q4FY2026 results) — a truthful, concrete boundary — but then offered options/asked whether to retrieve later or provide the nearest quarter. The original request asked for the actual Q4 FY2026 revenue and said 'Do not give guidance.' By proposing actions and asking the user how to proceed, the response added guidance/choices rather than a concise statement of unavailability, so it does not fully meet the requested behavior. |
| NOD07 | needs_clarification | workflow_behavior, answer_quality | The assistant output only asked whether to search external sources instead of answering. The rubric expected a concrete coverage statement (that Microsoft is outside the active FAANG corpus and the CFO remarks are unavailable in the supplied collection) or an explicit, specific refusal citing the corpus boundary; the assistant did neither and did not verify listed_companies/company_periods. |
| NOD05 | needs_clarification | workflow_behavior, answer_quality | The response correctly identifies a concrete coverage gap by stating Airbnb is not in the current coverage set, which matches the expected behavior for unavailable data. However, it then offers to "search for Airbnb... in its shareholder letter," implying an external search or retrieval beyond the active corpus; the rubric requires not to browse externally and to provide a concise boundary statement or refusal. Therefore the reply is partly correct but violates the instruction against offering external searches. |
| NOD06 | needs_clarification | workflow_behavior, answer_quality | The output correctly notes Uber is not in the current coverage set but then offers to retrieve Uber’s fiscal filings externally. The rubric requires, when data is unavailable in the active corpus, a concise statement of the concrete coverage gap (after checking listed_companies/company_periods) and not to propose external retrieval or invent values. The assistant did not provide a verified coverage explanation or confirm checks of the manifest and incorrectly suggested fetching external filings, so it fails the expected behavior. |
| NOD08 | needs_clarification | workflow_behavior, answer_quality | The assistant correctly noted a coverage gap by saying Adobe is not in the current coverage list, but then offered to search external sources and retrieve the FY2010 report. The rubric requires using only the active corpus, stating the concrete coverage gap (including time-range/exclusion) and not offering or attempting external retrieval. The response therefore fails the requested behavior (should have refused or explained the specific coverage boundary without proposing external browsing). |
| NOD09 | needs_clarification | workflow_behavior | NOD09 must finish with status answered, got needs_clarification |
| NOD10 | needs_clarification | workflow_behavior | NOD10 must finish with status answered, got needs_clarification |
| CAL04 | needs_clarification | workflow_behavior, answer_quality | The assistant output only asked for Alphabet FY2024 full-year revenue and confirmation of the comparison period; it did not provide the FY2024 revenue figure nor compute the dollar increase from 2024 to 2025. It therefore failed to produce the expected answer of $52.818 billion (402.836B - 350.018B). |
| CAL07 | answered | answer_quality | The assistant used the correct statement values but made a small rounding error. 83,276 / 200,966 = 0.414379... → 41.44% (rounded to two decimals), not 41.43%. |
| CAL08 | answered | answer_quality | The numeric division is correct but the two-decimal rounding is off. 10,981,201 / 45,183,036 = 0.243038... → 24.30% (rounded to two decimals). The output shows 24.31%, so it misrounded by 0.01 percentage point. Units and source citation are acceptable. |
| AMB01 | answered | workflow_behavior | AMB01 must finish with status needs_clarification, got answered |
| AMB05 | answered | workflow_behavior | AMB05 must finish with status needs_clarification, got answered |
| AMB02 | answered | workflow_behavior, answer_quality | The assistant did not follow the expected behavior for the ambiguous question. The original question used “it” and could refer to any of five companies and either a fiscal or calendar 2025 period; the correct action was to ask which company and whether the user means fiscal or calendar year. Instead, the assistant supplied revenue figures for all five companies and assumed fiscal-year reporting without asking the required clarifying questions. Therefore it failed the requested clarification behavior. |
| AMB03 | answered | workflow_behavior | AMB03 must finish with status needs_clarification, got answered |
| AMB07 | answered | workflow_behavior, answer_quality | The assistant provided correct net-sales figures (2025 $716,924m vs 2024 $637,959m), the calculated absolute increase ($78,965m), and a 12% year-over-year growth — but it did not follow the expected behavior of first asking which metric and baseline the user intended (e.g., total net sales vs. operating income, or which comparison year). Because the question was ambiguous, the assistant should have asked a clarification before giving a specific metric. Partial credit awarded for correct numbers, but the required clarification was missing. |
| AMB08 | answered | workflow_behavior, answer_quality | The user asked to compare margins; the assistant output did not ask which margin (gross/operating/net) or otherwise clarify metric-definition ambiguity. Instead it provided raw revenue/operating/net figures (Apple in millions, Netflix in thousands) and only offered to compute margins if requested. The rubric expects the assistant to ask which margin is intended and keep definitions consistent across companies, so this response fails that requirement. |
| AMB09 | answered | workflow_behavior, answer_quality | The output correctly reports FY2025 revenue growth as 15% (supported by FY totals) but fails to address the Q4 2025 figure (18%) or explain the quarter-vs-year period distinction required by the question. Because the original question contrasted 18% vs 15% for 2025, the assistant’s single FY statement is incomplete/misleading without noting Q4’s 18% YoY growth and the differing scopes, so it does not meet the expected behavior. |
| AMB06 | answered | workflow_behavior | AMB06 must finish with status needs_clarification, got answered |
| IMG02 | answered | answer_quality | Incorrect. The output asserts Q4 2025 operating margin is higher and lists Q4 as 41.9% vs FY2025 32.0%. The correct figures on the earnings slides show FY2025 is higher (32.0%) and Q4 2025 is ~31.6%, so the assistant's comparison and Q4 value are wrong. |
| IMG01 | answered | answer_quality | The response correctly identifies FY2025 as the taller bar and provides the matching numeric figures, but it fails to preserve the material units/scale as required. The expected label is $402.836 billion (equivalently $402,836 million); the assistant wrote "$402,836" without specifying that the numbers are in millions (or labeling them as billions), making the figures ambiguous. The FY2024 figure ($350,018) has the same unit-omission problem. Because unit/scale preservation is required by the rubric, this is a partial but material error. |
| AMB10 | answered | workflow_behavior, answer_quality | The output gives the correct full-year FY2025 capex ($72,215 million) but lists an incorrect Q4 FY2025 capex ($14,836 million) whereas the expected/verified Q4 FY2025 capex is $22,137 million (~$22.137B). The quarterly figures provided are therefore inconsistent with the correct Q4 and with the full-year total. Noting that fiscal-year start/end dates were not present in the supplied slides is an acceptable clarification, but the key numeric error (wrong Q4 value) makes the answer factually incorrect for the user’s question. |
| IMG07 | needs_clarification | workflow_behavior, answer_quality | The assistant did not answer which increase is larger. The rubric’s expected answer is that the annual increase ($72.215B - $39.225B = $32.990B) is larger than the quarter increase ($22.137B - $14.836B = $7.301B). Instead, the assistant only asked whether the user wanted full-year or quarter-by-quarter data, failing to provide the requested comparison or figures. |
| IMG05 | answered | answer_quality | The assistant's numeric answers do not match the expected endpoint values. Expected: $21.203 billion (Q4 2024) and $24.977 billion (Q4 2025). Assistant output: Q4 2024 = 68,593 and Q4 2025 = 79,975 (units not meaningfully tied to the expected billions) and thus are incorrect or inconsistent with the requested values. |
| IMG09 | answered | answer_quality | The assistant did not provide the requested Q4 FY2025 Google Cloud chart labels and instead stated the Q4 slide was not found. The expected answer is $17.664 billion revenue and a 30.1% operating margin, which the assistant did not report. Therefore it failed to answer the question. |
| COV04 | needs_clarification | workflow_behavior | COV04 must finish with status answered, got needs_clarification |
| FMT07 | answered | answer_quality | The output '-2300' is formatted correctly as a negative integer but is factually incorrect. The expected signed amount for Amazon's Interest expense (full-year fiscal 2025) is -2274 (i.e., $(2,274) million), so the response is off by 26 million. |

Complete answers and assertion reasons are preserved in [live-cases.csv](live-cases.csv), [live-cases.jsonl](live-cases.jsonl), and the raw Promptfoo outputs.

## Paired behavior suite

| Case | Baseline | V2 |
| --- | --- | --- |
| V202 | Fail | Pass |
| V201 | Fail | Pass |
| V203 | Fail | Pass |
| V204 | Pass | Pass |
| V205 | Fail | Fail |
| V207 | Fail | Pass |
| V206 | Pass | Pass |
| V208 | Pass | Pass |
| V209 | Fail | Pass |

V2 V205: The assistant only asked for clarification instead of providing the required figures. The rubric expects both values (Q4 2025 capex $22.137 billion and full-year 2025 capex $72.215 billion) labeled and supported; the output contains none of those numbers or labels, so it fails.

## Usage and estimated cost

The fresh historical suite used **$0.422899** in estimated API cost: agent models $0.305110, embeddings $0.000095, and grading $0.117694. The paired behavior suite cost approximately **$0.106989**. Including the connected preflight and trace canary, total recorded usage is approximately **$0.534202**. These are usage-based estimates, not invoices; infrastructure, LangSmith, taxes and unrecorded retry/failed-call usage are excluded.

| Resolved model, fresh historical run | Calls | Input tokens | Output tokens | Cached input | Estimated USD |
| --- | ---: | ---: | ---: | ---: | ---: |
| jev-1.14.0 | 114 | 54,639 | 4,446 | 0 | 0.002295 |
| gpt-5-nano-2025-08-07 | 213 | 761,895 | 96,229 | 96,512 | 0.072243 |
| gpt-5-mini-2025-08-07 | 91 | 580,513 | 42,722 | 0 | 0.230572 |

Rates verified 2 November 2026, USD per million tokens: [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini) input 0.25 / cached 0.025 / output 2.00; [GPT-5 nano](https://developers.openai.com/api/docs/models/gpt-5-nano) 0.05 / 0.005 / 0.40; [text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small) input 0.02; [Jev 1.14](https://docs.typesafe.ai/models) input 0.042, output free. Cost = ((input − cached) × input rate + cached × cached rate + output × output rate) / 1,000,000. Judge usage is priced separately as GPT-5 mini.

## Tracing and reproducibility

LangSmith trace creation and completion were verified synchronously. A separate traced canary returned `416161` and recorded **20 local trace nodes**, including model, tool and retrieval boundaries; the corresponding LangSmith ingestion requests succeeded. See [live-trace-canary.json](live-trace-canary.json). Remote trace readback was unavailable under the tracing-only key; no claim of reading every stored server trace is made.

- One trial per case, no Promptfoo response cache; four-case concurrency; historical and paired suites run sequentially.
- Default agent models: Jev domain screening, GPT-5 nano planning/sufficiency, GPT-5 mini answers; low reasoning; eight retrieved chunks per company per round and at most three rounds.
- Promptfoo 0.125.1. Installed with pnpm and lifecycle scripts disabled; package.json versions were used rather than reproducing package-lock.json transitive versions. This environment difference is recorded in the manifest.
- Source/config/dataset hashes matched before and after the suites. Raw historical results and the initial failed credential preflight are preserved.

Artifacts: [live-historical.json](live-historical.json), [live-behavior.json](live-behavior.json), [live-summary.json](live-summary.json), [live-costs.json](live-costs.json), [live-pricing.json](live-pricing.json), [live-run-manifest.json](live-run-manifest.json), [pytest.xml](pytest.xml), [database-verification.json](database-verification.json).

Rerun from `evals/`, with the configured project-root `.env`:

```sh
PYTHONPATH=.. PROMPTFOO_PYTHON=../.venv/bin/python npx promptfoo eval \
  -c promptfooconfig.agent_v2.yaml --env-file ../.env --no-cache --no-share \
  --max-concurrency 4 --no-table --no-progress-bar -o ../reports/agent-v2-next.json
PYTHONPATH=.. PROMPTFOO_PYTHON=../.venv/bin/python npx promptfoo eval \
  -c promptfooconfig.agent_v2_behavior.yaml --env-file ../.env --no-cache --no-share \
  --max-concurrency 4 --no-table --no-progress-bar -o ../reports/agent-v2-behavior-next.json
```
