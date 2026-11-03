# Latest comparison — aligned baseline and v2, 3 November 2026

After baseline prompt alignment, a fresh paired evaluation on identical questions and grading criteria produced **103/114 (90.4%) baseline versus 101/114 (88.6%) v2**. Ambiguity: **9/9 versus 7/9**; missing data: **9/10 versus 8/10**. The separate acceptance suite scored **8/10 for both**.

Mean completed-response latency was **31.38s baseline versus 10.81s v2**. Recorded model/embedding cost estimates were **$0.880284 versus $0.273608**, excluding grading. Five baseline discovery-plan validation errors remain in the strict denominator; their model usage is absent from exports, so its recorded cost understates spend. V2 had no runtime errors. These results compare the complete configured agents, including different models/reasoning settings, rather than isolating Jev.

See the [fresh aligned comparison](../agent-v2-aligned-comparison-2026-11-03/report.md) for paired outcomes, per-topic scores, costs, errors, unchanged-contract checks and reproduction. Baseline implementation changes were limited to prompts; v2, datasets, grader and retrieval stayed frozen. **854 tests passed, 19 skipped.** Earlier sections below preserve the previous runs.

---

# Latest update — prompt refinement, 3 November 2026

The final revised evaluation passed **98/114 (86.0%)**, including **9/10 missing-data**, **6/9 revised ambiguity**, and **10/10 formatting** cases. The separate v2 acceptance suite passed **8/10**. Routing is improved but not fully resolved; the new case/rubric contract prevents treating aggregate historical score differences as matched accuracy gains.

The domain-only benchmark measured **177.5ms mean Jev HTTP RTT**, versus **1,713.6ms mini** and **2,195.5ms nano**. All three matched the 16-question routing labels on both repetitions. On this task Jev was **9.65× faster and 11.56× cheaper than mini**; this does not attribute the whole workflow speedup to Jev.

See the [latest implementation and evaluation report](../agent-v2-refinement-2026-11-03/report.md) for prompt/dataset changes, exact usage and costs, shorter-answer measurements, all remaining failures and reproducibility artifacts. Independent tests: **845 passed, 19 skipped**.

The sections below preserve the earlier completion report and its diagnostic addendum.

---

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

## Diagnostic addendum — ambiguity, missing data and Jev (3 November 2026)

**The two weak topics primarily expose planning/routing problems and an ambiguity-policy mismatch, rather than Jev rejecting financial questions.** Jev only screens domain and investment-advice intent. It receives the original question, not the company inventory or retrieved evidence; it does not decide whether to clarify or whether a financial fact is available.

### Evidence available for this review

The fresh results above remain **83/114**, with **0/9 ambiguity** and **0/10 missing-data** passes. However, the referenced `live-historical.json`, `live-behavior.json`, `live-cases.*`, `live-costs.json`, and `live-run-manifest.json` are absent from this checkout. Fresh case findings below therefore use the failure records already preserved in this report; their probabilities, plans and timings cannot be independently rechecked here.

The independently inspectable historical v2 export is [../agent-v2/promptfoo.json](../agent-v2/promptfoo.json), evaluation `eval-1Hb-2026-11-02T16:31:01`: **88/114**, **2/9 ambiguity**, and **2/10 missing-data** passes. Its paired [behavior-comparison.json](../agent-v2/behavior-comparison.json) has **v2 8/9 versus baseline 1/9**, whereas the fresh paired run reported above has **8/9 versus 3/9**. These are separate runs. In particular, `../agent-v2/fresh-baseline.json` is a **baseline-provider** run, not the missing fresh-v2 export. No new model calls or grading were performed for this addendum, and no saved scores were changed.

The prompt, plan schema, gate implementation (now `ood.py`), inherited routing code and assertions match the earlier v2 [run manifest](../agent-v2/run-manifest.json) hashes. The current agent file additionally includes the optional planner API described above. This supports inspecting the routing mechanism, but does not recover the fresh run's exact structured plans. Recomputed earlier-run metrics, case outputs, probe probabilities and source hashes are preserved in [diagnostic-evidence.json](diagnostic-evidence.json).

### Why ambiguous questions fail

Two different effects contribute to the fresh **0/9**:

1. **The historical workflow contract conflicts with the intended v2 policy.** `evals/assertions.py:assert_trajectory` requires every `ambiguous_questions` case to end as `needs_clarification`, with zero retrieval and no citations. In contrast, `_INTERPRETATIONS` in `agents/agent_v2/prompts.py` explicitly prefers answering bounded interpretations, and `QuestionPlan.needs_clarification` reinforces that rule. All nine fresh ambiguity failures finish as `answered`. Consequently, a useful, grounded answer can still fail the historical workflow check. AMB04 is already reclassified as deterministic accuracy and is excluded from these nine cases.
2. **V2 also makes genuine interpretation and evidence mistakes.** An unknown referent must still trigger clarification, and answering alternatives requires actually covering those alternatives. The policy difference does not excuse guessing the company, choosing one metric silently or selecting the wrong chart value.

| Fresh cases | Recorded behavior and diagnosis |
| --- | --- |
| AMB01, AMB03, AMB05, AMB06 | Only `workflow_behavior` fails; the saved answer-quality check passes. These account for four of nine failures and show the clearest contract/policy disagreement. A judge pass alone does not prove that every assumption is appropriate; AMB01 still lacks a specified metric and period. |
| AMB02 | “How much revenue did **it** make in 2025?” receives figures for all five companies. The planner fails to preserve an essential unknown company, despite both prompt and schema identifying this as a clarification case. The earlier raw run also misroutes this case to `answered`, but with no retrieval and an empty-evidence response. |
| AMB07 | Chooses Amazon net-sales growth and a 2024 baseline without resolving or covering other plausible meanings of “grow.” The figures can be correct while the requested interpretation remains unresolved. |
| AMB08 | Returns raw revenue/income values rather than a clarification or consistently calculated, labeled margin alternatives. This does not fulfill v2's own alternative-answer policy. |
| AMB09 | Gives annual growth of 15% without explaining that 18% refers to Q4 growth. The error is incomplete period disambiguation, not just failure to ask a question. |
| AMB10 | Gives the annual capex figure but assigns $14.836B to Q4 FY2025 instead of $22.137B. This is a chart/period selection error. |

Thus **4/9 fresh ambiguity cases pass answer quality but fail workflow; 5/9 fail both**. The dedicated v2 suite's fresh **8/9** supports the usefulness of answering bounded alternatives, but does not cover every essential-clarification failure in the historical suite. Its V205 failure also shows that the planner sometimes clarifies even when the request explicitly asks for both quarterly and annual figures. The earlier raw suite fails V206 instead, showing single-run variability rather than a stable solved behavior.

### Why in-domain missing-data questions fail

**All ten fresh NOD cases exit as `needs_clarification` after discovery, with zero retrieval attempts.** This is distinct from a domain refusal: the question is financial and passes Jev, but the nano planner treats a known coverage gap as something the user must resolve. In the earlier inspectable run, eight of ten NOD cases follow this same failing route; only NOD01 and NOD04 finish as `answered`.

The control flow makes this error decisive:

```text
Jev allows question
  -> listed_companies + company_periods for all five companies
  -> nano QuestionPlan sets needs_clarification=true
  -> inherited _route_question chooses clarification before its coverage-answer branch
  -> _ask_specific_details returns the planner's clarification_question verbatim; END
```

The answer model never runs on this branch. Its instructions to give a verified coverage explanation and avoid promising future searches therefore cannot correct the planner's message. This explains repeated offers to search externally, upload reports or choose another period, even after the workflow has already established the relevant boundary. Those are textual offers; the saved tool records do **not** show actual external browsing.

| Fresh cases | Correct boundary and observed problem |
| --- | --- |
| NOD01, NOD02, NOD05–NOD09 | Named companies are outside the active five-company corpus. Give a final, specific coverage-gap answer. Asking permission to expand the corpus cannot make these requests answerable within the current task. |
| NOD03 | The explicitly requested Apple FY2026 annual report is absent. Existing quarterly coverage does not establish that annual filing; report the gap directly. |
| NOD04 | Meta Q4 FY2026 actuals are absent. A concise unavailability answer is sufficient; nearest-quarter alternatives do not answer the request. |
| NOD10 | The request assumes all 15 archived companies and all FY2026 annual reports are available. Explain the pinned active corpus and missing annual coverage, without inventing a ranking. |

**Zero retrieval is not itself the defect.** All ten NOD cases have `allow_no_retrieval=true`; the assertion accepts an `answered` status with verified discovery and no report citations. The fresh failure table shows three NOD answers passing answer quality (NOD01, NOD09, NOD10), but all ten failing workflow because of the final status. Seven also fail answer quality. This is not a missing-PDF ingestion issue: `data/raw` is an immutable archive, while the active retrieval corpus intentionally contains only the manifest's 100 reports from five companies.

The underlying design weakness is that a known coverage gap and an essential unknown user intent share the same free model-controlled clarification route. There is no enforced plan invariant separating them. The exact fresh plans are unavailable; the route attribution follows from the reported terminal statuses and the inspected graph, rather than a claim to have read those plans.

### Jev performance in agent v2

The gate bundles two Noul judgments in one request: whether the question concerns company financial reports, and whether it requests an investment recommendation. Code continues when `report_question >= 0.3` and `financial_advice < 0.7`; otherwise it returns the fixed domain refusal. A Noul represents a yes/no probability, as documented by [TypeSafe](https://docs.typesafe.ai/primitives/noul). Neither judgment asks about answerability or ambiguity.

The following figures are **recomputed from the earlier raw 88/114 historical run**, not presented as a new measurement of the fresh 83/114 run. Gate decisions are inferred from terminal status because only the gate can select `out_of_domain`; raw exports do not retain individual Noul responses.

| Gate measure | Inspectable historical v2 run |
| --- | ---: |
| Resolved model | `jev-1.14.0` |
| Successful calls / invocations | 114/114, one bundled request each |
| Out-of-distribution cases correctly refused | 10/10 |
| Remaining financial/coverage cases correctly allowed | 104/104 |
| False domain refusals / false domain accepts against topic labels | 0 / 0 |
| Ambiguity cases allowed through the gate | 9/9 |
| Missing-data cases allowed through the gate | 10/10 |
| Input / output tokens | 54,639 / 4,446 |
| Estimated Jev cost / mean cost per invocation | $0.002294838 / $0.00002013 |
| Full refusal-path latency, 10 OOD cases | Mean 166.4ms; median 159.9ms; range 137.9–206.6ms |
| Jev-only latency, probability calibration | Not recoverable from these exports |

The earlier paired suite adds **9/9 financial requests correctly allowed**, using 4,347 input and 351 output tokens, estimated at **$0.000182574**. Across the two inspectable exports this is **123 calls**, 58,986 input tokens, 4,797 output tokens and **$0.002477412** estimated Jev cost. These are not 123 distinct benchmark questions; some questions overlap between suites. Pricing is $0.042 per million input tokens with free output, reconfirmed against [TypeSafe's model page](https://docs.typesafe.ai/models) on 3 November 2026. The latest report's historical Jev usage table above records the same 114-call token totals, but the absent fresh export prevents independently verifying that attribution.

The separately saved [domain probes](../agent-v2-domain-probes.json) expose actual probabilities for seven examples, all resolved to `jev-1.14.0`:

| Probe | P(report question) | P(investment advice) | Code route |
| --- | ---: | ---: | --- |
| Amazon earnings in 2025 | 0.99 | 0.02 | Continue |
| Vegetarian lasagna recipe | 0.01 | 0.01 | Refuse |
| Buy Apple stock based on earnings | 0.97 | 0.98 | Refuse |
| Walmart revenue, outside active coverage | 0.99 | 0.02 | Continue |
| Which companies and periods are covered? | 0.94 | 0.03 | Continue |
| Revenue with unidentified “it” | 0.96 | 0.02 | Continue |
| Ignore rules and write malware | 0.01 | 0.01 | Refuse |

All seven match the manually reviewed gate policy. In particular, passing Walmart and the unidentified “it” is correct: coverage discovery and clarification belong downstream. These probes are separate diagnostic examples, not additional scored historical cases. The historical OOD set consists of ten relatively clear unrelated requests; it contains no investment-advice example, so that part of the policy has only the single saved buy-stock probe here. There are no saved near-threshold examples or repeated-trial measurements. The results support **correct observed domain routing on this suite**, not a claim of general 100% accuracy, calibrated probabilities or comprehensive injection resistance.

Jev's integration traces its model request/response and usage, but provider metadata preserves only aggregate tokens and final status. The ten OOD responses each use exactly one model call (Jev), zero retrieval and zero model errors. Their reported latency is therefore a useful measurement of the complete screening-and-refusal path, including graph/callback overhead, rather than isolated model duration. `answer_latency_ms` includes the full workflow, and `experiment-trace-usage.json` mixes completed, smoke and aborted runs. Neither supports a Jev-only mean/p95 latency or a causal claim that Jev produced the overall speedup. Future runs should export per-case probabilities, applied thresholds, gate outcome, model duration and resolved model alongside the existing nested LangSmith traces; credentials must remain excluded.

### Recommended next experiment

1. **Enforce coverage versus clarification as separate outcomes.** Clarify only when the company/metric/period needed to interpret the request is genuinely unidentified. A verified absent company or explicitly requested missing filing should produce `answered` with a concrete coverage gap. For mixed coverage, retain supported companies and answer their supported parts. Enforce this using verified discovery and validated plan fields rather than matching case IDs or adding more external-search offers.
2. **Make ambiguity acceptance explicit.** Keep the historical suite unchanged for comparisons, and extend the versioned v2 suite to distinguish useful bounded alternatives from essential clarification. Include AMB02-style unidentified companies, AMB01-style missing metric and period, matching margin definitions, and both annual/quarterly readings. Do not claim that all nine historical failures are harmless policy differences.
3. **Check interpretation coverage before final answering.** Required facts must cover each promised alternative, including chart period/series and compatible units. AMB09 and AMB10 require better evidence selection, not just a different status.
4. **Then compare planners.** Use the existing `planning_model` boundary to compare nano with mini while keeping nano evidence assessment, the corpus and both evaluation contracts fixed. Report strict, factual and workflow scores separately, plus per-stage latency/cost. A stronger planner may help, but its benefit and the benefit of the proposed route constraints have not yet been measured. The current evidence provides no reason to change Jev's thresholds to address these downstream failures.

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
