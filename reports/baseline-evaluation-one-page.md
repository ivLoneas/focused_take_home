# Baseline agent evaluation - one-page summary



Recorded Promptfoo v2 run, 2 November 2026; 114 questions.



Strict pass rate was **80.8% excluding formatting (84/104)** and **73.7% overall (84/114)**: 84 passes, 29 assertion failures and one runtime error. Strict pass requires every applicable quality, workflow, validity and formatting check. The results support a cost-reduction experiment with a smaller model and simpler workflow; savings and quality retention still need validation.



## Baseline and retrieval

**Models:** gpt-5-mini for question analysis, context assessment and answering; gpt-5-mini also grades answer quality. **Workflow:** LangChain/LangGraph analyses the question, discovers company/period coverage, retrieves evidence, checks sufficiency and refines the query for up to three rounds, then answers, clarifies or refuses. LangSmith records nested runs. **Retrieval:** text-embedding-3-small (1,536 dimensions), cosine-vector search in company-specific PostgreSQL/pgvector tables; up to eight chunks per company per round, with source/page metadata. Corpus: 100 PDFs from Alphabet, Amazon, Apple, Meta and Netflix.



## Time, tokens and spend

**Answer latency:** mean 33.83 s; median 31.49 s; p95 69.04 s (113 completed answers). Full run: 18 min 41 s at four-case concurrency.

**Tokens:** 1,611,370 agent + 137,844 judge + 4,455 embeddings = **1,753,669 total**.

**Estimated API spend:** $0.9642 agent including embeddings + $0.1135 grading = **$1.0777 total**, including the failed case; excludes ETL, infrastructure and taxes.



## Strict pass rate by section



| Section | Pass rate | Observed reason / interpretation |
| --- | --- | --- |
| Factual accuracy | 6/10; 60% | Four clarifications instead of factual answers. |
| Tool use / coverage | 13/14; 92.9% | Google Cloud evidence was not recovered. |
| Out-of-domain | 10/10; 100% | Bounded refusals passed the revised judge. |
| Multiple companies | 10/10; 100% | Comparisons passed current checks. |
| Conditional reasoning | 8/10; 80% | Missing evidence / missing period discovery. |
| Unavailable data | 7/10; 70% | Scope errors, invalid year text, one runtime error. |
| Calculations | 9/10; 90% | One unnecessary fiscal/calendar clarification. |
| Ambiguous questions | 8/10; 80% | Clarification wording and route-contract mismatch. |
| Images / charts | 5/10; 50% | Wrong panel/segment, missed slides, clarification. |
| Table lookup | 8/10; 80% | Coverage lookup and clarification failures. |
| Output formatting | 0/10; 0% | Citation instructions conflict; 7/10 quality passes. |



## Interpretation and next steps



**Main accuracy issue - over-clarification.** Requests such as "earnings in 2025" trigger revenue-versus-net-income and fiscal-versus-calendar questions. Many failures are failure to answer, rather than wrong arithmetic. Define metric/period defaults, state assumptions, and clarify when uncertainty prevents a defensible answer. The judge accepted some incomplete clarifications, so quality-only scores need manual review.

**Formatting - prompt/evaluation conflict.** The system mandates citations while users request a bare number or company name. Proposed change: honor explicit user formats and retain provenance separately. Assess the resulting instruction-following and prompt-injection risks in the next-generation agent; no prompt change was made for this report.

**Data quality versus agent error remains unresolved.** Image accuracy is weak; table lookup is 80%, with observed failures mainly in coverage/clarification. Inspect original PDF -> extracted table/figure description -> chunk -> retrieved context -> answer to isolate ETL loss, retrieval misses or generation mistakes. Apply the same audit to factual misses before attributing them to the model or scaling it down.



Source: saved v2 summary, cases and run manifest in reports/baseline-2026-11-02-v2/. Recorded scores; AMB04 was reclassified afterward. No tests/evaluations rerun. One trial per case; judge errors remain.

