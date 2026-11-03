**Follow-up:** Both agents have now been rerun after baseline prompt alignment on the same contract. See the [fresh baseline/v2 comparison](../agent-v2-aligned-comparison-2026-11-03/report.md). Results below preserve the earlier refinement run.

# Agent v2 prompt refinement and domain-screening benchmark — 3 November 2026

**Final evaluation: 98/114 strict passes (86.0%), 16 assertion failures and no runtime errors.** Missing-data questions pass **9/10**; the revised ambiguity set passes **6/9**. The separate ten-case v2 acceptance suite passes **8/10**. These prompt changes improve observed behavior but do not make routing reliable in every case.

## What changed

- Known missing company, explicit filing or period coverage is an `answered` boundary explanation after discovery. The planning prompt includes the Uber FY2025 net-income example and explicitly sets `needs_clarification=false`, with an empty retrieval-company list and a concrete coverage gap. It prohibits external-search/upload offers and confirmation of already specified tasks. Mixed requests retain supported companies. These are prompt/schema descriptions; no question-matching overrides or answer postprocessing were added.
- Bounded profit/earnings and margin terms receive labeled alternatives. Broad performance/results, unidentified companies, unspecified growth and unspecified spending require one targeted clarification. “Show me Alphabet's 2026 results” passes in the final run; missing annual coverage must not silently turn this broad request into a full-year refusal.
- Final-answer prompts include hypothetical fact, profit, calculation, missing-company, missing-period and bare-number examples. They favor one or two factual sentences, adjacent citations, explicit units/signs and no preambles, repeated source lists, workflow narration or unsolicited search offers.
- The 114-case suite retains its IDs and topic counts. AMB03/05/08/09/10 now contain genuinely underspecified financial questions. AMB02 asks only for the unidentified company. AMB06 expects the quarter/metric clarification without an inventory recital. Answerable earlier questions remain in the versioned behavior suite; V210 adds operating/net-margin comparisons. Seven main-suite rows changed; the other 107 are identical as parsed CSV rows.
- The rubric now explicitly accepts a specific company-level gap without manifest/tool names or redundant dates when the whole company is excluded. Optional “Would you like to ask about something else?” is allowed. Factual values, grounding, external-search prohibitions and deterministic status/format checks are preserved.

Snapshots and changes: [before dataset](before-evals_tests.csv), [after dataset](after-evals_tests.csv), [row changes](dataset-changes.json), [before prompts](before-prompts.py), [final prompts](candidate-prompts.py), [run manifest](run-manifest.json). Historical exports and their scores were not rewritten.

## Final live results

| Measure | Earlier inspectable v2 | Final revision |
| --- | ---: | ---: |
| Strict pass | 88/114 | 98/114 |
| Mean invocation latency, excluding grading | 12.82s | 11.26s |
| Median invocation latency | 12.70s | 11.48s |
| Estimated agent models | $0.297321 | $0.256372 |
| Estimated embeddings + grading + models | $0.409199 | $0.372783 |
| Mean answer length, all questions | 94.6 words | 39.5 words |
| Median answer length | 78 words | 33 words |

**The aggregate accuracy change is not a matched-contract improvement claim:** seven case rows and the missing-data rubric changed, and these are single trials. The earlier raw run is `eval-1Hb-2026-11-02T16:31:01`; the final run is `eval-kW1-2026-11-03T13:15:53`. The preceding completion report's 83/114 run remains report-only because its original raw artifacts are absent. Do not combine its figures with the 88/114 export.

For the same **85 unchanged factual/tool/format questions**, mean answer length fell from **95.5 to 44.1 words**, and median from 85 to 37. This supports shorter responses; length alone does not establish correctness or naturalness. See [style comparison](style-comparison.json).

| Topic | Earlier saved v2 | Final revision |
| --- | ---: | ---: |
| deterministic_accuracy | 11/11 | 11/11 |
| tool_usage | 11/14 | 12/14 |
| out_of_distribution | 10/10 | 10/10 |
| multiple_companies | 10/10 | 10/10 |
| conditional_reasoning | 10/10 | 9/10 |
| in_domain_no_data | 2/10 | 9/10 |
| extra_calculation | 10/10 | 7/10 |
| ambiguous_questions | 2/9 | 6/9 |
| image_questions | 4/10 | 5/10 |
| table_questions | 9/10 | 9/10 |
| formatting_questions | 9/10 | 10/10 |

The ambiguity column uses revised questions. Missing-data workflow checks are unchanged and pass 9/10, compared with 2/10 in the earlier raw run. Ambiguity workflow passes 7/9 but strict pass is 6/9 because one clarification omits the missing spending measure. Exact-format checks pass 10/10, as does formatting-topic factual quality.

Actual final responses:

- Uber unavailable-data case: “I do not have reports for Uber. Would you like to ask about one of the companies I do have (Alphabet, Amazon, Apple, Meta, Netflix)?”
- Broad Alphabet results: “Which quarter(s) of 2026 and which metrics would you like (e.g., revenue and net income for Q1FY2026–Q3FY2026, or a full FY2026 summary if available)?”
- Bounded Amazon profit: “Amazon reported FY2025 operating income of $79,975 million and net income of $77,670 million (for the year ended December 31, 2025) [10-K p. 37; Earnings Release p. 1-2].”

## Acceptance-suite regression check

The expanded planning prompt over-clarified simple profit questions: its paired run scored **v2 3/10 versus baseline 2/10**. The final shorter planner recovered **v2 8/10**, including both profit questions, the new margin comparison, comparative-period evidence, and all three exact-format controls. The baseline 2/10 is from that earlier paired invocation, not a simultaneous final rerun. The final original nine-case subset passes **7/9**, versus 8/9 in the earlier saved v2 export; therefore no overall acceptance-suite improvement is claimed.

Final failures: V201 reports correct revenue/net-income figures but omits the acceptance contract's explicit fiscal/calendar equivalence explanation; V205 selects different capex figures/bases instead of the reviewed slide values. Concision does not excuse unsupported or mislabeled financial values. Final [acceptance results](behavior-final.json), earlier [paired results](candidate-3-behavior.json).

## Jev versus standalone domain-only classifiers

We ran **16 public questions twice per model**, covering report facts, unavailable companies/periods, genuine ambiguity, coverage, unrelated requests, injection wording and investment advice. Each model had one separate warmup. Calls were serial within the experiment, with seeded shuffled model order, pooled HTTP clients, no LangChain response cache, and OpenAI low reasoning. Other evaluation traffic could overlap; this is a small observed comparison, not a controlled-load service guarantee.

Jev used its unchanged two-Noul production gate. Mini and nano answered the same two semantic judgments as structured booleans, using the same criteria, with no retrieval or financial answering. All three matched manually reviewed expected gate decisions on all 32 measured calls, with no errors. This is 16 distinct questions, not 32 independent domain examples, and not a calibration/generalization benchmark.

**RTT is now directly measured:** `httpx.Client.send` through the complete response body, including network and API service, excluding LangChain parsing and trace scheduling. It differs from the earlier 166ms whole-refusal-path proxy. Warmups are excluded below; p95 uses sorted index floor((n−1)×0.95).

| Classifier | Correct gate decisions | Mean HTTP RTT | Median | p95 | Cost for 32 calls | Estimated cost / 1,000 calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| jev | 32/32 | 177.5ms | 170.0ms | 197.0ms | $0.000632 | $0.01973 |
| mini | 32/32 | 1713.6ms | 1673.5ms | 2188.4ms | $0.007298 | $0.22806 |
| nano | 32/32 | 2195.5ms | 2147.6ms | 3440.7ms | $0.003848 | $0.12025 |

Resolved models: `jev-1.14.0`, `gpt-5-mini-2025-08-07`, `gpt-5-nano-2025-08-07`. Jev was **9.65× faster and 11.56× cheaper than mini**, and **12.37× faster and 6.09× cheaper than nano**, for this isolated task. Against mini, that is about **1.54 seconds and $0.000208 saved per standalone screening call**. Nano generated more reasoning/output tokens than mini on this sample despite the same low-reasoning setting; its observed slower timing is not a general model ranking.

**This does not isolate Jev's causal contribution to the complete baseline/v2 difference.** Baseline combines domain screening and other planning in one call; separating it into a new classifier changes the work. The component comparison is the requested estimate, not a justification for subtracting a whole baseline planning call. V2 also changes routing, model sizes, discovery, answer length and assessment scheduling.

Recorded pricing, verified 3 November 2026, USD per million input / cached input / output: [mini](https://developers.openai.com/api/docs/models/gpt-5-mini) 0.25 / 0.025 / 2.00; [nano](https://developers.openai.com/api/docs/models/gpt-5-nano) 0.05 / 0.005 / 0.40; [Jev](https://docs.typesafe.ai/models) 0.042 input, output free. Costs use actual reported usage, including reasoning in output exactly once. Embeddings use the existing $0.02/million input rate. These are estimates, not invoices.

Artifacts: [summary](domain-benchmark-summary.json), [per-call RTT/usage/probabilities](domain-benchmark-cases.jsonl), [payload/labels](domain-benchmark-payload.json), [benchmark source](benchmark_domain.py). An initial attempt exhausted a 512-token reasoning allowance; it is preserved separately and excluded from the comparison. The completed run allows 2,048 output tokens. Recorded cost across all evaluation iterations, warmups, and the interrupted experiment is approximately **$1.3280**; [cost accounting](task-costs.json) excludes infrastructure, tracing fees, taxes and unrecorded usage.

## Remaining failures and validation

The core unresolved routing failures are NOD05 (asks for clarification about excluded Airbnb), AMB03/05 (chooses arbitrary FY2025 summaries for broad performance requests), AMB10 (asks for period but assumes the spending measure), COV03 (clarifies a known missing filing), and COV04 (drops the supported Apple part of a mixed-coverage request). Prompt examples substantially improve coverage handling but do not enforce it deterministically. A stronger planner comparison through the existing optional planning-model boundary remains a useful follow-up; it was not enabled here.

Other failures involve missing evidence, chart/period selection, units or arithmetic rounding. They remain real financial-answering limitations. All final failures are listed below; full text and judge reasons are in [evaluation-summary.json](evaluation-summary.json).

| Case | Final status | Failed checks |
| --- | --- | --- |
| IF09 | answered | answer_quality |
| NOD05 | needs_clarification | workflow_behavior, answer_quality |
| CAL03 | answered | answer_quality |
| CAL06 | answered | answer_quality |
| CAL07 | answered | answer_quality |
| AMB03 | answered | workflow_behavior, answer_quality |
| AMB05 | answered | workflow_behavior, answer_quality |
| AMB10 | needs_clarification | answer_quality |
| IMG01 | answered | answer_quality |
| IMG02 | answered | answer_quality |
| IMG05 | answered | answer_quality |
| IMG07 | needs_clarification | workflow_behavior, answer_quality |
| IMG09 | answered | answer_quality |
| TAB02 | answered | answer_quality |
| COV03 | needs_clarification | workflow_behavior, answer_quality |
| COV04 | answered | workflow_behavior, answer_quality |

Independent tests were authored before implementation and initially failed as expected. Final pytest: **845 passed, 19 skipped**; opt-in PostgreSQL integration tests were not enabled. Ruff and `git diff --check` pass. Database readback verifies all 100 manifest document paths/checksums and all 20,274 chunks are unchanged. The stopped project PostgreSQL container was restarted; no ETL, scraping or re-embedding occurred.

LangSmith remained enabled for live runs, preserving nested model, discovery and retrieval boundaries. A synchronous create/update ingestion canary succeeded; remote readback of every trace is not claimed. The benchmark also exports exact Jev responses, so per-call probabilities and resolved model IDs can be inspected locally. Export checks found no configured credentials in artifacts. See [database verification](database-verification.json), [trace verification](trace-verification.json), [pytest](pytest.xml).

Reproduce from the repository root with configured keys and PostgreSQL:

```sh
PYTHONPATH=. .venv/bin/python reports/agent-v2-refinement-2026-11-03/benchmark_domain.py
python3 reports/agent-v2-refinement-2026-11-03/summarize.py
```

From `evals/`, use the absolute repository Python path for `PROMPTFOO_PYTHON`:

```sh
PYTHONPATH=.. PROMPTFOO_PYTHON=/Users/ivansmirnov/work/focused/.venv/bin/python \
  ./node_modules/.bin/promptfoo eval -c promptfooconfig.agent_v2.yaml --env-file ../.env \
  --no-cache --no-share --max-concurrency 4 --no-table --no-progress-bar -o ../reports/next-v2.json
PYTHONPATH=.. PROMPTFOO_PYTHON=/Users/ivansmirnov/work/focused/.venv/bin/python \
  ./node_modules/.bin/promptfoo eval -c promptfooconfig.agent_v2_behavior.yaml --env-file ../.env \
  --filter-providers agent_v2_provider --no-cache --no-share --max-concurrency 4 \
  --no-table --no-progress-bar -o ../reports/next-v2-behavior.json
```
