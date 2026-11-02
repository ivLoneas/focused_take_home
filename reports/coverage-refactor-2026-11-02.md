# Database coverage discovery refactor — 2 November 2026

Implemented `listed_companies` and `company_periods` as traced LangChain tools over published `etl_documents` rows.
The database retains individual quarters. Tool output merges only adjacent quarters, preserves gaps, and reports
annual filing years separately. Prompts receive verified tool output as message context rather than a fixed inventory.
The backend and evaluation provider inject discovery, and Promptfoo checks actual calls and relevant company arguments.

Validation:

- Full pytest suite: 681 passed, 19 optional integration tests skipped.
- Focused agent/eval/backend/alignment suite after the final graph simplification: 436 passed.
- Ruff and `git diff --check`: passed.
- Live PostgreSQL smoke check: all five current companies and their intervals/annual years matched published rows.
- Focused Promptfoo: 8/9 overall, 9/9 workflow/tool-usage checks, zero runtime errors.
- New COV01–COV04 cases: 4/4 overall.

The one overall failure was ACC03: the model returned the correct Apple Services net-sales value ($109,158 million)
but cited annual-report pages 26 and 39, while the reviewed expectation cites page 32. Discovery and retrieval
trajectory checks passed. Citation equivalence was not investigated in this data-source refactor.

The run covered ACC03, TOOL10, NOD01, NOD03, NOD04, and COV01–COV04. The complete 104-case model evaluation was not run.
Raw results: [coverage-refactor-2026-11-02.json](coverage-refactor-2026-11-02.json).
