# API cost comparison — 3 November 2026

Estimates from recorded usage at Standard short-context list rates. These are not billing invoices. Runtime includes OpenAI model calls, unchanged Jev screening and embedding calls. Grading is separate.

| Suite / agent | Previous runtime | New runtime | Change | Previous grading | New grading |
| --- | ---: | ---: | ---: | ---: | ---: |
| full.json / baseline | $0.8803 | $1.2895 | +46.5% | $0.0974 | $0.1276 |
| full.json / v2 | $0.2736 | $0.6058 | +121.4% | $0.1122 | $0.1260 |
| behavior.json / baseline | $0.1082 | $0.1938 | +79.1% | $0.0101 | $0.0146 |
| behavior.json / v2 | $0.0279 | $0.0678 | +142.7% | $0.0098 | $0.0122 |

Full-suite runtime per 1,000 comparable questions: baseline $7.72 → $11.31; v2 $2.40 → $5.31. V2 remains approximately 53% cheaper than current baseline on this workload.

Both suites and both providers combined, including grading: $1.5195 → $2.4374 (+60.4%). Smoke, preflight and other task traffic are excluded.

The previous baseline lost usage on five failed invocations. Comparing only the 109 baseline questions with recorded usage in both runs gives $0.8803 → $1.2310 (+39.8%). This still measures different actual model trajectories, not a controlled pricing-only change.

Terra costs $1.00/$0.05/$5.00 per million uncached-input/cached-input/output tokens, compared with mini at $0.25/$0.025/$2.00. Luna costs $0.10/$0.01/$0.50 versus nano at $0.05/$0.005/$0.40. Higher input rates outweigh reduced output usage. Source: [official OpenAI pricing](https://developers.openai.com/api/docs/pricing).

Runtime telemetry does not preserve cache-creation token counts, so unrecorded cache-write premiums are excluded. Grading includes recorded 30-minute cache-write counts at 1.25× input rates. Regional/Fast surcharges, credits, discounts, taxes, infrastructure and LangSmith fees are excluded. No individual model request exceeded the short-context threshold based on the total input across calls per case. Jev uses the unchanged previously documented $0.042/M input rate and free output.

Raw per-model costs and assumptions: [cost-comparison.json](cost-comparison.json).
