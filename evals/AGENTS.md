# Evaluation dataset

`evals_tests.csv` is the baseline 100-question suite for the agentic retrieval workflow. It contains ten cases for each of these topics:

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

## Active retrieval corpus

The positive grounded questions must use the same bounded corpus as the Docker ETL: the newest 20 reports for each of Alphabet, Amazon, Apple, Meta, and Netflix. `data/active_manifest.csv` is the single pinned inventory for those 100 source documents and their checksums. The current selection contains 3,503 pages, primarily from 2025 and 2026, with Apple and Netflix 2024 documents retained where they fall inside each company's newest 20. `data/AGENTS.md` defines the source-data contract.

Every `data/raw/*.pdf` citation in `evals_tests.csv` must occur in `data/active_manifest.csv`. Positive grounded topics must not reference excluded companies. Out-of-distribution and in-domain-no-data cases may name excluded companies specifically to test scope handling, but their expected answers must state that the evidence is unavailable in the active corpus and must not encourage external sourcing.

Annual fact, comparison, conditional, calculation, and table questions use retained 2025 Forms 10-K. Image questions use retained Q4 2025 presentations. Preserve the cited PDF page, units, fiscal period, and GAAP/non-GAAP labels when changing expected answers.

Run the independent alignment checks after any corpus or evaluation change:

```sh
uv run pytest -q tests/etl/test_eval_alignment.py
```
