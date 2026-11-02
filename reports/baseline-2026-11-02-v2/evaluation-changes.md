# Evaluation revision v2

Only evaluation code, evaluation data, evaluation tests, and documentation were changed in this revision. Agent, tool, and provider source files were snapshotted before edits and will be checked against the final run.

## Judge changes

- The judge now sees the original question and its requested output.
- Reviewed reports and pages are non-exhaustive references. Equivalent evidence elsewhere in the active corpus is accepted; every listed source need not appear in the response.
- Explicit quotation/source requests still apply. Material units, fiscal periods, currency, signs, and GAAP/non-GAAP distinctions remain required.
- Citations, explanatory formulas, and every comparison operand are not required unless requested. Bare numbers use the question's units; winner-only comparisons can contain just the company name.
- Financial correctness is graded separately from deterministic format compliance. A correct verbose answer can pass quality and fail formatting; a wrong bare number can pass formatting and fail quality.
- A scope refusal or clarification does not need financial figures or report citations.

## Dataset and deterministic checks

The original 104 cases and their existing 9 field values are preserved exactly. Ten FMT cases are appended, for 114 total. Discovery requirements and the factual retrieval workflow checks are preserved. The new output_pattern field is mandatory for formatting_questions and opts any case into a format_compliance assertion. The complete trimmed answer must match the pattern; only surrounding whitespace is ignored. Format success says nothing about the numeric value or winning company.

| ID | Question | Expected answer | Required full-match pattern |
| --- | --- | --- | --- |
| FMT01 | What was Google's (Alphabet's) total revenue in Q1 fiscal 2025? Return only the number in millions, without commas, currency symbols, prose, or citations. | 90234 | \d+ |
| FMT02 | Who earned more net income in fiscal 2024: Apple or Amazon? Use their issuer fiscal years. Return only the company's name, Apple or Amazon, without punctuation or explanation. | Apple | (?:Apple\|Amazon) |
| FMT03 | What was Alphabet's total revenue for fiscal 2025? Return only the number in billions with exactly three decimal places, without currency symbols, commas, or citations. | 402.836 | \d+\.\d{3} |
| FMT04 | What was Meta's GAAP net income for full-year fiscal 2025? Return only the number in millions, without separators, currency symbols, prose, or citations. | 60458 | \d+ |
| FMT05 | What was Netflix's total revenue for fiscal 2025? Return only the number in millions with exactly three decimal places, without currency symbols, separators, prose, or citations. | 45183.036 | \d+\.\d{3} |
| FMT06 | How much Services net sales did Apple report for fiscal 2025? Return only the number in billions with exactly three decimal places, without currency symbols, prose, or citations. | 109.158 | \d+\.\d{3} |
| FMT07 | What signed amount appears in Amazon's Interest expense row for full-year fiscal 2025? Return only the negative integer in millions using a leading minus sign, without commas, parentheses, prose, or citations. | -2274 | -\d+ |
| FMT08 | What GAAP diluted earnings per share did Meta report for full-year fiscal 2025? Return only the number in dollars per share with exactly two decimal places, without a currency symbol, prose, or citations. | 23.49 | \d+\.\d{2} |
| FMT09 | Who reported more total revenue for full-year fiscal 2025: Alphabet or Meta? Return only the company's name, Alphabet or Meta, without punctuation or explanation. | Alphabet | (?:Alphabet\|Meta) |
| FMT10 | What were Apple's total net sales for fiscal 2025? Return only the integer in millions, without commas, currency symbols, prose, or citations. | 416161 | \d+ |

Formatting cases have four required checks: response validity, workflow, answer quality, and format compliance. Existing cases retain three. The LLM threshold remains 0.8 and the grader remains gpt-5-mini.

FMT01 was verified against the retained Alphabet Q1 2025 filing: consolidated revenue 90,234 million. FMT02 was verified using comparative 2024 columns in retained 2025 annual reports: Apple 93,736 million versus Amazon 59,248 million. No external documents were sourced.

The previous 100-question full run predates a separate coverage-discovery refactor and used different grading requirements. The new run is therefore not a controlled measurement of judge changes alone. The report separates the original 100 questions, four coverage cases, and ten formatting cases.
