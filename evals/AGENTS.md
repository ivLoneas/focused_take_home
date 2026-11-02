# Evaluation dataset

`evals_tests.csv` is the 114-question suite for the agentic retrieval workflow. Most topics contain ten cases;
deterministic accuracy has eleven and ambiguous questions has nine after AMB04's reclassification. Topics are:

- deterministic accuracy;
- tool usage, including a no-search control;
- out-of-distribution handling;
- multiple-company retrieval;
- conditional reasoning;
- in-domain questions whose evidence is absent;
- derived calculations;
- ambiguous questions;
- image and chart interpretation;
- table lookup.
- exact output formatting.

`AMB04` retains its ID for historical comparisons but belongs to `deterministic_accuracy`: its wording permits
using the annual report's fiscal period. Expect a direct cited FY2025 sales answer with the fiscal year-end date,
without requiring a clarification question. Saved results from earlier runs retain their original classification.

Four additional `COV01`–`COV04` tool-usage cases check company/period listings, an unavailable quarter and annual
filing, and a mixed supported/unsupported comparison. The optional CSV fields `required_tools`,
`required_period_companies`, and `allow_no_retrieval` define deterministic discovery expectations. Supported factual
cases require both discovery tools and every relevant company argument. Missing-data cases may return a verified
coverage gap without report retrieval. Never treat a tool name mentioned in answer text as an actual invocation.

`FMT01`–`FMT10` add number-only and company-name-only answers, explicit unit conversion, signs, and decimal
precision. `output_pattern` opts into a deterministic full-match check after trimming surrounding whitespace;
formatting-topic cases must supply a valid pattern. Format compliance is independent of factual correctness.
The LLM judge sees the original question and treats reviewed sources/pages as non-exhaustive references. Accept
equivalent evidence elsewhere in the active corpus and do not require every source, inline citations, or explanatory
operands unless the question explicitly asks for them. Keep material units, periods, signs, and GAAP labels correct.

## Active retrieval corpus

The positive grounded questions must use the same bounded corpus as the Docker ETL: the newest 20 reports for each of Alphabet, Amazon, Apple, Meta, and Netflix. `data/active_manifest.csv` is the single pinned inventory for those 100 source documents and their checksums. The current selection contains 3,503 pages, primarily from 2025 and 2026, with Apple and Netflix 2024 documents retained where they fall inside each company's newest 20. `data/AGENTS.md` defines the source-data contract.

Every `data/raw/*.pdf` citation in `evals_tests.csv` must occur in `data/active_manifest.csv`. Positive grounded topics must not reference excluded companies. Out-of-distribution and in-domain-no-data cases may name excluded companies specifically to test scope handling, but their expected answers must state that the evidence is unavailable in the active corpus and must not encourage external sourcing.

Annual fact, comparison, conditional, calculation, and table questions use retained 2025 Forms 10-K. Image questions use retained Q4 2025 presentations. Preserve the cited PDF page, units, fiscal period, and GAAP/non-GAAP labels when changing expected answers.

Run the independent alignment checks after any corpus or evaluation change:

```sh
uv run pytest -q tests/etl/test_eval_alignment.py
```
