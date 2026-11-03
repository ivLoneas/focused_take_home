# Prompt-aligned baseline versus agent v2 — 3 November 2026

Both agents were freshly evaluated on **the same 114 questions and grading contract**, after aligning baseline prompts with the revised policy. The separate ten-case acceptance suite was also rerun for both agents. V2, the datasets, grader, discovery/retrieval code and baseline graph/provider/schema stayed frozen.

## Full-suite comparison

| Measure | Baseline, aligned prompts | V2, unchanged |
| --- | ---: | ---: |
| Strict passes | 103/114 (90.4%) | 101/114 (88.6%) |
| LLM answer-quality passes | 103/109 | 102/114 |
| Workflow passes | 109/109 | 110/114 |
| Exact-format check passes | 8/10 | 10/10 |
| Provider runtime errors | 5 | 0 |
| Mean answer latency, completed responses | 31.38s | 10.81s |
| Median answer latency | 30.79s | 10.72s |
| p95 answer latency | 61.45s | 23.32s |
| Mean provider latency, all invocations | 30.02s | 10.83s |
| Recorded runtime API estimate, models + embeddings | $0.880284 | $0.273608 |
| Recorded runtime estimate / question | $0.007722 | $0.002400 |
| Grading estimate, separately | $0.097352 | $0.112206 |
| Mean / median completed-answer words | 44.1 / 38 | 38.8 / 32 |
| Acceptance-suite strict passes | 8/10 | 8/10 |

On this run, Baseline passed 2 more full-suite cases than v2. V2 was **2.90× faster by mean completed-answer latency**, and baseline's recorded runtime token-cost estimate was **3.22× v2's**. These are descriptive single-run results, not a statistical guarantee or a Jev-only ablation.

**Runtime failures remain in the 114-case strict-accuracy denominator.** Answer-quality and workflow rows use the number of checks actually executed; provider exceptions are not presented as completed grading judgments. Completed-answer latency uses 109 baseline and 114 v2 responses and excludes grading. The separate all-invocation provider latency includes failures and wrapper overhead. P95 uses sorted index floor((n−1)×0.95). Word counts use whitespace splitting, not a naturalness or factuality judge.

**Cost completeness:** baseline usage is missing for ['ACC04', 'IF07', 'NOD06', 'CAL02', 'CAL07']; v2 usage is missing for []. Provider exceptions do not export their incurred model usage, so affected recorded totals understate spend. Cost ratios compare recorded estimates. Grading is evaluation expense, not production runtime cost. Infrastructure, LangSmith fees, taxes and unrecorded retries are excluded; estimates are not invoices.

## Topic results under identical expectations

| Topic | Aligned baseline | V2 |
| --- | ---: | ---: |
| deterministic_accuracy | 10/11 | 10/11 |
| tool_usage | 13/14 | 13/14 |
| out_of_distribution | 10/10 | 10/10 |
| multiple_companies | 10/10 | 10/10 |
| conditional_reasoning | 9/10 | 10/10 |
| in_domain_no_data | 9/10 | 8/10 |
| extra_calculation | 8/10 | 8/10 |
| ambiguous_questions | 9/9 | 7/9 |
| image_questions | 8/10 | 5/10 |
| table_questions | 9/10 | 10/10 |
| formatting_questions | 8/10 | 10/10 |

The revised ambiguity and unavailable-data rules apply equally to both providers; no cases or assertions were weakened for baseline. Strict pass requires every applicable deterministic and judge check, not just a plausible financial answer.

## Paired outcomes

| Outcome | Cases | IDs |
| --- | ---: | --- |
| both pass | 92 | See summary.json |
| baseline only pass | 11 | ACC06, TOOL05, NOD01, NOD03, CAL01, CAL03, AMB03, AMB05, IMG05, IMG09, IMG10 |
| v2 only pass | 9 | ACC04, TOOL08, IF07, NOD06, CAL02, CAL07, TAB02, FMT01, FMT02 |
| both fail | 2 | IMG01, IMG02 |

The original question, expected answer, annotations, optional discovery/format fields and assertions were verified identical for each pair. Individual pass differences and judge reasons are preserved in [summary.json](summary.json), with raw outputs and actual tool calls in [full.json](full.json).

## Ten-case acceptance comparison

| Case | Aligned baseline | V2 |
| --- | --- | --- |
| V201 | Pass | Pass |
| V202 | Pass | Pass |
| V203 | Pass | Pass |
| V204 | Pass | Pass |
| V205 | Fail | Pass |
| V206 | Pass | Fail |
| V207 | Fail | Pass |
| V208 | Pass | Pass |
| V209 | Pass | Pass |
| V210 | Pass | Fail |

The aligned baseline improved from the earlier **2/10 to 8/10** on an identical acceptance contract; row variables and assertions were checked against that earlier export. This is one before/after trial, not a repeated-trial causal estimate. See [baseline-before-after-acceptance.json](baseline-before-after-acceptance.json).

Remaining acceptance failures: baseline V205 unnecessarily asks which capex period instead of answering both, and V207 refuses the requested total revenue while giving a different metric and prose. V2 V206 asks permission to perform a fully specified comparison, and V210 incorrectly reports the Apple margin operands as unavailable.

This suite tests bounded earnings/profit/margin alternatives, quarterly/annual interpretations, comparative-year evidence and exact output formats. It was run after the full suite, on both providers in one evaluation; previous baseline-only or v2-only trials are not substituted for these results. See [behavior.json](behavior.json).

## What baseline alignment changed

Only `agents/baseline/prompts/templates.py` changed in the baseline implementation:

- Bounded company/year profit, earnings and margins requests receive labeled alternatives. Explicit quarterly/annual alternatives are answered directly. Identical fiscal/calendar periods are combined only with supporting evidence.
- Genuinely missing intent gets one specific clarification: broad results/performance, unknown company, unspecified growth/baseline or spending measure/period. The Alphabet 2026 results example asks for quarter and metric.
- Known company/filing/period gaps stay in domain and finish as `answered` after discovery: `needs_clarification=false`, empty unsupported retrieval companies, and a concrete gap. The Uber example demonstrates the intended response. Supported portions of mixed requests remain retrievable.
- Short factual answers, hypothetical few shots, exact-format citation exceptions, explicit units/signs/precision, and no external-search/upload offers. Retrieved citation provenance remains in the result even for bare-number output.
- Chart/table panel, series, period and accounting-basis checks remain evidence-bound; no ETL or vision change was made.

The two-stage baseline domain/discovery planner, single-model setup, schema, retrieval-refinement loop and trace instrumentation were retained. Before/after prompt snapshots are [before-baseline-prompts.py](before-baseline-prompts.py) and [aligned-baseline-prompts.py](aligned-baseline-prompts.py).

## Errors and limits

- Baseline - aligned prompts, ACC04: Error: Python error: Company 'Meta' has no verified company_periods result
- Baseline - aligned prompts, IF07: Error: Python error: Company 'Meta' has no verified company_periods result
- Baseline - aligned prompts, NOD06: Error: Python error: Company 'Uber' has no verified company_periods result
- Baseline - aligned prompts, CAL02: Error: Python error: Company 'Amazon' has no verified company_periods result
- Baseline - aligned prompts, CAL07: Error: Python error: Company 'Meta' has no verified company_periods result

The baseline validation guard correctly prevents retrieval without verified period discovery, but a rejected model plan still fails the user's invocation. These are planning/discovery failures rather than a database outage. They were not silently retried or removed.

All failed cases, including assertion failures:

- Agent v2 - unchanged: ACC06, TOOL05, NOD01, NOD03, CAL01, CAL03, AMB03, AMB05, IMG01, IMG02, IMG05, IMG09, IMG10.
- Baseline - aligned prompts: ACC04, TOOL08, IF07, NOD06, CAL02, CAL07, IMG01, IMG02, TAB02, FMT01, FMT02.

Financial failures can still arise from missing retrieved operands, chart/quarter selection, units or rounding. LLM answer-quality scores are judge assessments, not independent citation-entailment proofs. One trial per case and grader/model variability limit claims about small score differences; v2 code was unchanged from its earlier 98/114 run; differences illustrate variation between runs, including model and grader effects.

## Performance interpretation and reproducibility

Baseline uses GPT-5 mini for all model stages, with the existing temperature=0 configuration and reasoning left at the provider default. V2 uses Jev screening, nano planning/sufficiency and mini answers with low reasoning. Both use eight retrieved chunks per company per round, at most three retrieval rounds, the same pgvector store and no Promptfoo response cache. The whole-agent timing/cost difference therefore includes model choices, reasoning settings, planning/discovery structure, assessment scheduling and answer length. It must not be attributed entirely to Jev.

The separate [domain-only benchmark](../agent-v2-refinement-2026-11-03/report.md#jev-versus-standalone-domain-only-classifiers) measured Jev's mean HTTP RTT at 177.5ms versus 1.71s for mini using low reasoning, with 16 questions repeated twice. That addresses the screening component; this report addresses the complete configured assistants.

In this fresh run the ten unrelated-request refusal paths averaged **3.335s baseline versus 0.199s v2**. Each provider used 10 and 10 model calls respectively across those ten cases, and neither used retrieval. This measures the full refusal path, rather than isolated network RTT.

Costs use actual exported tokens, including cached input and reasoning output without double counting, at the rates documented in the [preceding pricing record](../agent-v2-refinement-2026-11-03/report.md#jev-versus-standalone-domain-only-classifiers): mini $0.25/$0.025/$2.00 and nano $0.05/$0.005/$0.40 per million input/cached/output tokens, Jev $0.042 input with free output, embeddings $0.02 per million input. Pricing sources: [OpenAI mini](https://developers.openai.com/api/docs/models/gpt-5-mini), [OpenAI nano](https://developers.openai.com/api/docs/models/gpt-5-nano), [TypeSafe](https://docs.typesafe.ai/models). These rates were verified on 3 November 2026 during the preceding run.

Frozen source/config/dataset hashes and effective non-secret settings are in [run-manifest.json](run-manifest.json). Corpus verification confirms 100 document paths/checksums from the manifest and 20,274 chunks, with no ETL, sourcing or re-embedding. LangSmith tracing stayed enabled; synchronous trace create/update preflight succeeded. Remote readback of every stored trace is not claimed. See [preflight.json](preflight.json).

Independent tests were written first and initially failed as expected. **854 pytest tests passed, 19 skipped** (opt-in PostgreSQL integration tests were not enabled). Ruff and diff checks passed. See [pytest.xml](pytest.xml).

Full evaluation: `eval-euo-2026-11-03T13:36:25`; acceptance evaluation: `eval-03K-2026-11-03T14:02:29`. Both providers were paired within each suite, four-invocation global concurrency; suites ran sequentially. Rerun from `evals/`:

```sh
PYTHONPATH=.. PROMPTFOO_PYTHON=/Users/ivansmirnov/work/focused/.venv/bin/python \
  ./node_modules/.bin/promptfoo eval -c promptfooconfig.aligned_comparison.yaml --env-file ../.env \
  --no-cache --no-share --max-concurrency 4 --no-table --no-progress-bar -o ../reports/next-aligned-full.json
PYTHONPATH=.. PROMPTFOO_PYTHON=/Users/ivansmirnov/work/focused/.venv/bin/python \
  ./node_modules/.bin/promptfoo eval -c promptfooconfig.agent_v2_behavior.yaml --env-file ../.env \
  --no-cache --no-share --max-concurrency 4 --no-table --no-progress-bar -o ../reports/next-aligned-behavior.json
```

From repository root, regenerate metrics/report using `python3 reports/agent-v2-aligned-comparison-2026-11-03/summarize.py` and `python3 reports/agent-v2-aligned-comparison-2026-11-03/render_report.py`.
