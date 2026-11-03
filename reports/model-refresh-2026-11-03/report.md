# Model refresh: baseline and agent v2 — 3 November 2026

Both agents were freshly evaluated on the same 114 questions and assertions. The separate ten-case behavior suite was then run for both agents. Cache and sharing were disabled; global concurrency was four. Each case/provider has one measured invocation per suite.

| Measure | Baseline | Agent v2 |
| --- | ---: | ---: |
| Strict full-suite passes | 109/114 (95.6%) | 109/114 (95.6%) |
| Provider runtime errors | 0 | 0 |
| Mean answer latency (seconds) | 9.52 | 6.97 |
| Median answer latency (seconds) | 9.12 | 6.89 |
| p95 answer latency (seconds) | 15.72 | 12.56 |
| Behavior-suite strict passes | 6/10 | 7/10 |

Strict passes require every applicable validity, workflow, quality and formatting check. Runtime failures remain in the 114-case denominator. Answer latency excludes grading and uses completed responses only. P95 uses sorted index floor((n−1)×0.95).

## Model audit and compatibility

- Baseline answering/planning, backend chat, evaluation chat and all four active Promptfoo graders use `gpt-6.1-terra`. V2 planning/sufficiency uses `gpt-6-luna`; Jev remains the domain gate.
- The initially edited `gpt-6-terra` default had no official model page. The official catalog lists `gpt-6.1-terra`, matching the pre-existing local `.env`. API model retrieval verified both selected model IDs.
- Baseline evaluation no longer sends `temperature=0`. Baseline keeps model-default reasoning, and v2 keeps low reasoning. The graph uses JSON-schema structured outputs; this change does not introduce model-bound function calls or migrate endpoints.
- Active source/config/docs/tests contain no older GPT model IDs. Historical report exports and snapshots retain the model names actually used when they were produced. Explicit valid model overrides remain supported.

Sources: [OpenAI model catalog](https://developers.openai.com/api/docs/models), [GPT-6.1 Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra), [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [migration parameter rules](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra#migration-quickstart).

## Check and topic results

| Check | Baseline | Agent v2 |
| --- | ---: | ---: |
| answer_quality | 109/114 | 109/114 |
| format_compliance | 10/10 | 9/10 |
| response_validity | 114/114 | 114/114 |
| workflow_behavior | 113/114 | 114/114 |

| Topic | Baseline | Agent v2 |
| --- | ---: | ---: |
| deterministic_accuracy | 11/11 | 11/11 |
| tool_usage | 12/14 | 13/14 |
| out_of_distribution | 10/10 | 10/10 |
| multiple_companies | 10/10 | 10/10 |
| conditional_reasoning | 10/10 | 10/10 |
| in_domain_no_data | 10/10 | 10/10 |
| extra_calculation | 10/10 | 9/10 |
| ambiguous_questions | 9/9 | 9/9 |
| image_questions | 7/10 | 8/10 |
| table_questions | 10/10 | 10/10 |
| formatting_questions | 10/10 | 9/10 |

## Remaining failures

### full.json

**Agent v2 - unchanged:**

- TOOL08: The answer omits both requested figures and incorrectly treats the cited excerpt as sufficient to conclude the figures are unavailable. The slides report Google Cloud revenue of $17.664 billion and an operating margin of 30.1%.
- CAL03: The response does not provide the requested percentage and incorrectly claims the figures are unavailable; the Apple 2025 Form 10-K contains them. The answer is approximately 26.23%.
- IMG05: The output does not provide either requested endpoint value and incorrectly claims the evidence is unavailable.
- IMG09: The answer provides neither requested label and incorrectly claims the chart is unavailable despite the cited earnings slides containing it.
- FMT01: The response fails to provide the requested revenue figure and incorrectly claims it is absent from the available evidence. The reported figure is 90234 million.

**Baseline - aligned prompts:**

- TOOL08: The answer gives neither requested figure and incorrectly claims the evidence does not establish them. The expected revenue is $17.664 billion and operating margin is 30.1%.
- TOOL10: The output refuses to calculate gross profit from the supplied values and does not provide the correct answer of $45 million.
- IMG05: The answer provides neither requested endpoint value, although the chart is available in the cited corpus. Its claim that the evidence is unavailable is unsupported.
- IMG07: The annual increase is correct, but the answer does not identify it as the larger increase and incorrectly says the quarterly comparison cannot be made. The quarterly increase was $7.301 billion.
- IMG09: The answer provides neither requested label and incorrectly claims the relevant chart is unavailable in the corpus.

### behavior.json

**Agent v2:**

- V201: The revenue and net income figures are correct and cited, but the answer does not explicitly address fiscal versus calendar year or provide evidence that the periods match.
- V204: The answer correctly reports 15% annual growth, but fails to identify the 18% figure as Q4 year-over-year growth and incorrectly says the supplied evidence does not establish the quarterly comparison.
- V207: The output does not provide the requested revenue figure and incorrectly claims the evidence is unavailable; the answer is 90234 million.

**Baseline:**

- V201: The figures and source page are provided, but the answer does not explicitly address whether Amazon’s fiscal and calendar years coincide or identify an evidence gap, as required.
- V204: The 18% Q4 and 15% full-year figures are correctly distinguished and cited. However, the claim that the available evidence does not establish Q1 revenue is false: subtracting the stated Q2, Q3 and Q4 revenues from the annual total gives Q1 revenue of $90.234 billion.
- V205: The response asks for clarification instead of providing both Q4 and full-year 2025 capital expenditures.
- V210: The operating margins and Apple’s net margin are correct, but the answer omits Netflix’s available net margin of about 24.30% and incorrectly says it cannot be determined. This leaves the requested comparison materially incomplete.

## Comparison limits and reproducibility

The previous aligned run reported baseline 103/114 and v2 101/114, with both at 8/10 on the behavior suite. Those runs used older answer/routing models and an older grader. The new scores therefore do not isolate answer-model improvement: grader changes, single-run variation and the concurrent agent independence refactor captured in this source snapshot also limit causal comparisons.

The source was frozen before live evaluation to prevent concurrent workspace edits from changing an in-flight run. `source-snapshot.tar.gz` contains the exact source, tests and evaluation inputs used; `run-manifest.json` records their hashes, effective model choices and snapshot location. Labels containing “unchanged” are inherited Promptfoo labels, not a claim that models match historical runs.

Preflight verified the exact 100 document paths/checksums and 20,274 chunks against `data/active_manifest.csv`. No source data, ETL or embeddings were changed. LangSmith tracing was enabled, synchronous trace create/update succeeded, and both live smoke responses completed with actual model usage. This does not claim remote readback of every stored span.

Independent regression tests were written first and failed for the stale defaults and unsupported temperature setting. After the fix, the full suite passed: **881 passed, 19 opt-in tests skipped**. Ruff passed on the changed Python files and `git diff --check` passed.

Recorded tokens and model-level v2 usage are in `summary.json`; raw responses, discovery/retrieval trajectories and grader explanations are in `full.json` and `behavior.json`. Provider exceptions can omit incurred token usage. No dollar estimate reuses historical model prices.

Full evaluation: `eval-Woy-2026-11-03T15:08:01`. Behavior evaluation: `eval-8XK-2026-11-03T15:18:56`.

From `evals/`, rerun the current configuration:

```sh
PYTHONPATH=.. PROMPTFOO_PYTHON=../.venv/bin/python ./node_modules/.bin/promptfoo eval \
  -c promptfooconfig.aligned_comparison.yaml --env-file ../.env --no-cache --no-share \
  --max-concurrency 4 --no-table --no-progress-bar -o ../reports/next-model-full.json
PYTHONPATH=.. PROMPTFOO_PYTHON=../.venv/bin/python ./node_modules/.bin/promptfoo eval \
  -c promptfooconfig.agent_v2_behavior.yaml --env-file ../.env --no-cache --no-share \
  --max-concurrency 4 --no-table --no-progress-bar -o ../reports/next-model-behavior.json
```
