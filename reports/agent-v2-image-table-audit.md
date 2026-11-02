# Image/table failure audit for agent v2

Audit date: 2 November 2026. Inputs: frozen baseline v2 cases, active source PDFs, and read-only Gold queries.
No ETL, corpus, embeddings, or source documents were changed.

| Baseline case | Observed failure | Evidence check | v2 mitigation |
| --- | --- | --- | --- |
| IMG01 | Clarified instead of comparing annual revenue bars because FY2024 standalone filing was absent. | A retained FY2025 slide can contain both FY2024 and FY2025 bars. | Retrieve comparative periods; standalone-file availability does not decide fact availability. |
| IMG02 | Substituted Google Services Q4 operating margin 41.9% for Alphabet total Q4 margin 31.6%. | Rendered Alphabet FY2025 Q4 slides PDF p. 6: Q4 31.6%, annual 32.0%; corresponding Gold descriptions preserve both. Page 8's segment description contains 41.9%. | Require matching total/segment, panel and series in planning, sufficiency and answer prompts. |
| IMG05 | Answered AWS and TTM endpoints instead of consolidated quarterly operating income. | Frozen answer explicitly cites AWS/TTM rather than the requested chart. Root cause is an evidence-selection mismatch; extraction completeness has not been established for this case. | Preserve chart identity, quarterly/annual/TTM and segment/total in queries and evidence checks. |
| IMG07 | Asked fiscal/calendar and quarter clarifications instead of comparing two labeled changes. | Original question names quarterly and annual bars. | Answer bounded period alternatives, preserving labels and operands. |
| IMG09 | Claimed Google Cloud slide was unavailable and misread the merged quarter interval. | Rendered Alphabet slides PDF p. 9: revenue $17,664 million; margin 30.1%. Both stored picture descriptions preserve those labels. | Treat intervals as inclusive; refine retrieval for the named chart and metric; never turn failed retrieval into a claim that the document does not exist. |
| TAB08 | Skipped required period discovery and refused diluted-share lookup. | Frozen trajectory shows missing discovery rather than a demonstrated table-extraction failure. | Verify relevant company periods before retrieval; retain explicit discovery invariant. |
| TAB10 | Asked annual versus quarter clarification for Netflix's 2025 tax provision. | Question gives year and statements; full-year is a useful bounded interpretation. | Retrieve full-year statements and preserve table row, column, units and sign. |

The picture descriptions reviewed here say “no visible title”: Docling crops individual panels, and the chart title
can be outside the crop. Values can survive while semantic identity is weakened. Page/heading metadata therefore
matters even when generated descriptions look numerically complete. This is a concrete extraction-context limitation,
but this change does not rebuild image descriptions or add direct page vision. A focused later experiment could add
page-title context to picture descriptions, keeping the raw PDF immutable and measuring the changed ETL separately.

These observations diagnose selected failures; they do not establish improvements. See the v2 evaluation report for
measured outcomes and remaining retrieval errors.
