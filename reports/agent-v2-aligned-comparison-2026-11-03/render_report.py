"""Render the aligned comparison from saved summary metrics."""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent


def main():
    data = json.loads((OUT / 'summary.json').read_text())
    full = data['full.json']
    behavior = data['behavior.json']
    baseline = next(v for k, v in full['providers'].items() if 'baseline' in k.lower())
    v2 = next(v for k, v in full['providers'].items() if 'v2' in k.lower())
    base_behavior = next(v for k, v in behavior['providers'].items() if 'baseline' in k.lower())
    v2_behavior = next(v for k, v in behavior['providers'].items() if 'v2' in k.lower())
    base_cost = baseline['estimated_models_usd'] + baseline['estimated_embeddings_usd']
    v2_cost = v2['estimated_models_usd'] + v2['estimated_embeddings_usd']
    speedup = baseline['mean_answer_latency_ms'] / v2['mean_answer_latency_ms']
    cost_ratio = base_cost / v2_cost
    def passes(group, metric):
        return sum(t.get(metric + '_passes', 0) for t in group['topics'].values())
    topic_rows = '\n'.join(
        f"| {topic} | {baseline['topics'][topic]['strict_passes']}/{counts['cases']} | {counts['strict_passes']}/{counts['cases']} |"
        for topic, counts in v2['topics'].items()
    )
    pair_rows = '\n'.join(
        f"| {name.replace('_', ' ')} | {len(ids)} | {('See summary.json' if name == 'both_pass' else ', '.join(ids)) or 'None'} |"
        for name, ids in full['paired']['outcomes'].items()
    )
    behavior_rows = []
    base_cases = {c['id']: c for c in base_behavior['case_answers']}
    for case in v2_behavior['case_answers']:
        behavior_rows.append(f"| {case['id']} | {'Pass' if base_cases[case['id']]['strict_pass'] else 'Fail'} | {'Pass' if case['strict_pass'] else 'Fail'} |")
    errors = []
    for label, group in full['providers'].items():
        for case in group['provider_error_cases']:
            first_line = (case.get('error') or 'Provider response metadata missing').splitlines()[0]
            errors.append(f"- {label}, {case['id']}: {first_line}")
    error_text = '\n'.join(errors) or 'Neither provider raised a runtime error.'
    delta = baseline['strict_passes'] - v2['strict_passes']
    accuracy_sentence = (
        f"Baseline passed {delta} more full-suite cases than v2." if delta > 0 else
        f"V2 passed {-delta} more full-suite cases than baseline." if delta < 0 else
        "Both agents passed the same number of full-suite cases."
    )
    assertions = []
    for label, group in full['providers'].items():
        assertions.append(f"- {label}: {', '.join(c['id'] for c in group['failures']) or 'None'}.")
    text = f'''# Prompt-aligned baseline versus agent v2 — 3 November 2026

Both agents were freshly evaluated on **the same 114 questions and grading contract**, after aligning baseline prompts with the revised policy. The separate ten-case acceptance suite was also rerun for both agents. V2, the datasets, grader, discovery/retrieval code and baseline graph/provider/schema stayed frozen.

## Full-suite comparison

| Measure | Baseline, aligned prompts | V2, unchanged |
| --- | ---: | ---: |
| Strict passes | {baseline['strict_passes']}/114 ({baseline['strict_passes']/114:.1%}) | {v2['strict_passes']}/114 ({v2['strict_passes']/114:.1%}) |
| LLM answer-quality passes | {passes(baseline, 'answer_quality')}/{baseline['assertion_counts'].get('answer_quality', 0)} | {passes(v2, 'answer_quality')}/{v2['assertion_counts'].get('answer_quality', 0)} |
| Workflow passes | {passes(baseline, 'workflow_behavior')}/{baseline['assertion_counts'].get('workflow_behavior', 0)} | {passes(v2, 'workflow_behavior')}/{v2['assertion_counts'].get('workflow_behavior', 0)} |
| Exact-format check passes | {passes(baseline, 'format_compliance')}/{baseline['assertion_counts'].get('format_compliance', 0)} | {passes(v2, 'format_compliance')}/{v2['assertion_counts'].get('format_compliance', 0)} |
| Provider runtime errors | {len(baseline['provider_error_cases'])} | {len(v2['provider_error_cases'])} |
| Mean answer latency, completed responses | {baseline['mean_answer_latency_ms']/1000:.2f}s | {v2['mean_answer_latency_ms']/1000:.2f}s |
| Median answer latency | {baseline['median_answer_latency_ms']/1000:.2f}s | {v2['median_answer_latency_ms']/1000:.2f}s |
| p95 answer latency | {baseline['p95_answer_latency_ms']/1000:.2f}s | {v2['p95_answer_latency_ms']/1000:.2f}s |
| Mean provider latency, all invocations | {baseline['mean_provider_latency_ms_all_invocations']/1000:.2f}s | {v2['mean_provider_latency_ms_all_invocations']/1000:.2f}s |
| Recorded runtime API estimate, models + embeddings | ${base_cost:.6f} | ${v2_cost:.6f} |
| Recorded runtime estimate / question | ${base_cost/114:.6f} | ${v2_cost/114:.6f} |
| Grading estimate, separately | ${baseline['estimated_grading_usd']:.6f} | ${v2['estimated_grading_usd']:.6f} |
| Mean / median completed-answer words | {baseline['mean_completed_answer_words']:.1f} / {baseline['median_completed_answer_words']:.0f} | {v2['mean_completed_answer_words']:.1f} / {v2['median_completed_answer_words']:.0f} |
| Acceptance-suite strict passes | {base_behavior['strict_passes']}/10 | {v2_behavior['strict_passes']}/10 |

On this run, {accuracy_sentence} V2 was **{speedup:.2f}× faster by mean completed-answer latency**, and baseline's recorded runtime token-cost estimate was **{cost_ratio:.2f}× v2's**. These are descriptive single-run results, not a statistical guarantee or a Jev-only ablation.

**Runtime failures remain in the 114-case strict-accuracy denominator.** Answer-quality and workflow rows use the number of checks actually executed; provider exceptions are not presented as completed grading judgments. Completed-answer latency uses {baseline['completed_provider_responses']} baseline and {v2['completed_provider_responses']} v2 responses and excludes grading. The separate all-invocation provider latency includes failures and wrapper overhead. P95 uses sorted index floor((n−1)×0.95). Word counts use whitespace splitting, not a naturalness or factuality judge.

**Cost completeness:** baseline usage is missing for {baseline['usage_missing_cases']}; v2 usage is missing for {v2['usage_missing_cases']}. Provider exceptions do not export their incurred model usage, so affected recorded totals understate spend. Cost ratios compare recorded estimates. Grading is evaluation expense, not production runtime cost. Infrastructure, LangSmith fees, taxes and unrecorded retries are excluded; estimates are not invoices.

## Topic results under identical expectations

| Topic | Aligned baseline | V2 |
| --- | ---: | ---: |
{topic_rows}

The revised ambiguity and unavailable-data rules apply equally to both providers; no cases or assertions were weakened for baseline. Strict pass requires every applicable deterministic and judge check, not just a plausible financial answer.

## Paired outcomes

| Outcome | Cases | IDs |
| --- | ---: | --- |
{pair_rows}

The original question, expected answer, annotations, optional discovery/format fields and assertions were verified identical for each pair. Individual pass differences and judge reasons are preserved in [summary.json](summary.json), with raw outputs and actual tool calls in [full.json](full.json).

## Ten-case acceptance comparison

| Case | Aligned baseline | V2 |
| --- | --- | --- |
{chr(10).join(behavior_rows)}

The aligned baseline improved from the earlier **2/10 to 8/10** on an identical acceptance contract; row variables and assertions were checked against that earlier export. This is one before/after trial, not a repeated-trial causal estimate. See [baseline-before-after-acceptance.json](baseline-before-after-acceptance.json).

Remaining acceptance failures: baseline V205 unnecessarily asks which capex period instead of answering both, and V207 refuses the requested total revenue while giving a different metric and prose. V2 V206 asks permission to perform a fully specified comparison, and V210 incorrectly reports the Apple margin operands as unavailable.

This suite tests bounded earnings/profit/margin alternatives, quarterly/annual interpretations, comparative-year evidence and exact output formats. It was run after the full suite, on both providers in one evaluation; previous baseline-only or v2-only trials are not substituted for these results. See [behavior.json](behavior.json).

## What baseline alignment changed

Only `agents/baseline/prompts/templates.py` changed in the baseline implementation:

- Bounded company/year profit, earnings and margins requests receive labeled alternatives. Explicit quarterly/annual alternatives are answered directly. Identical fiscal/calendar periods are combined only with supporting evidence.
- Genuinely missing intent gets one specific clarification: broad results/performance, unknown company, unspecified growth/baseline or spending measure/period. The Alphabet 2026 results example asks for quarter and metric.
- Known company/filing/period gaps stay in domain and finish as `answered` after discovery: `needs_clarification=false`, empty unsupported retrieval companies, and a concrete gap. The Uber example demonstrates the intended response. Supported portions of mixed requests remain retrievable.
- Short factual answers, hypothetical few shots, exact-format citation exceptions, explicit units/signs/precision, and no external-search/upload offers. Retrieved citation provenance remains in the result even for bare-number output.
- Chart/table panel, series, period and accounting-basis checks remain evidence-bound; no ETL or vision change was made.

The two-stage baseline domain/discovery planner, single-model setup, schema, retrieval-refinement loop and trace instrumentation were retained. Before/after prompt snapshots are [before-baseline-prompts.py](before-baseline-prompts.py) and [aligned-baseline-prompts.py](aligned-baseline-prompts.py).

## Errors and limits

{error_text}

The baseline validation guard correctly prevents retrieval without verified period discovery, but a rejected model plan still fails the user's invocation. These are planning/discovery failures rather than a database outage. They were not silently retried or removed.

All failed cases, including assertion failures:

{chr(10).join(assertions)}

Financial failures can still arise from missing retrieved operands, chart/quarter selection, units or rounding. LLM answer-quality scores are judge assessments, not independent citation-entailment proofs. One trial per case and grader/model variability limit claims about small score differences; v2 code was unchanged from its earlier 98/114 run; differences illustrate variation between runs, including model and grader effects.

## Performance interpretation and reproducibility

Baseline uses GPT-5 mini for all model stages, with the existing temperature=0 configuration and reasoning left at the provider default. V2 uses Jev screening, nano planning/sufficiency and mini answers with low reasoning. Both use eight retrieved chunks per company per round, at most three retrieval rounds, the same pgvector store and no Promptfoo response cache. The whole-agent timing/cost difference therefore includes model choices, reasoning settings, planning/discovery structure, assessment scheduling and answer length. It must not be attributed entirely to Jev.

The separate [domain-only benchmark](../agent-v2-refinement-2026-11-03/report.md#jev-versus-standalone-domain-only-classifiers) measured Jev's mean HTTP RTT at 177.5ms versus 1.71s for mini using low reasoning, with 16 questions repeated twice. That addresses the screening component; this report addresses the complete configured assistants.

In this fresh run the ten unrelated-request refusal paths averaged **{baseline['out_of_distribution_path']['mean_latency_ms']/1000:.3f}s baseline versus {v2['out_of_distribution_path']['mean_latency_ms']/1000:.3f}s v2**. Each provider used {baseline['out_of_distribution_path']['model_calls']} and {v2['out_of_distribution_path']['model_calls']} model calls respectively across those ten cases, and neither used retrieval. This measures the full refusal path, rather than isolated network RTT.

Costs use actual exported tokens, including cached input and reasoning output without double counting, at the rates documented in the [preceding pricing record](../agent-v2-refinement-2026-11-03/report.md#jev-versus-standalone-domain-only-classifiers): mini $0.25/$0.025/$2.00 and nano $0.05/$0.005/$0.40 per million input/cached/output tokens, Jev $0.042 input with free output, embeddings $0.02 per million input. Pricing sources: [OpenAI mini](https://developers.openai.com/api/docs/models/gpt-5-mini), [OpenAI nano](https://developers.openai.com/api/docs/models/gpt-5-nano), [TypeSafe](https://docs.typesafe.ai/models). These rates were verified on 3 November 2026 during the preceding run.

Frozen source/config/dataset hashes and effective non-secret settings are in [run-manifest.json](run-manifest.json). Corpus verification confirms 100 document paths/checksums from the manifest and 20,274 chunks, with no ETL, sourcing or re-embedding. LangSmith tracing stayed enabled; synchronous trace create/update preflight succeeded. Remote readback of every stored trace is not claimed. See [preflight.json](preflight.json).

Independent tests were written first and initially failed as expected. **854 pytest tests passed, 19 skipped** (opt-in PostgreSQL integration tests were not enabled). Ruff and diff checks passed. See [pytest.xml](pytest.xml).

Full evaluation: `{full['paired']['evaluation_id']}`; acceptance evaluation: `{behavior['paired']['evaluation_id']}`. Both providers were paired within each suite, four-invocation global concurrency; suites ran sequentially. Rerun from `evals/`:

```sh
PYTHONPATH=.. PROMPTFOO_PYTHON=/Users/ivansmirnov/work/focused/.venv/bin/python \\
  ./node_modules/.bin/promptfoo eval -c promptfooconfig.aligned_comparison.yaml --env-file ../.env \\
  --no-cache --no-share --max-concurrency 4 --no-table --no-progress-bar -o ../reports/next-aligned-full.json
PYTHONPATH=.. PROMPTFOO_PYTHON=/Users/ivansmirnov/work/focused/.venv/bin/python \\
  ./node_modules/.bin/promptfoo eval -c promptfooconfig.agent_v2_behavior.yaml --env-file ../.env \\
  --no-cache --no-share --max-concurrency 4 --no-table --no-progress-bar -o ../reports/next-aligned-behavior.json
```

From repository root, regenerate metrics/report using `python3 reports/agent-v2-aligned-comparison-2026-11-03/summarize.py` and `python3 reports/agent-v2-aligned-comparison-2026-11-03/render_report.py`.
'''
    (OUT / 'report.md').write_text(text)
    print('Wrote', OUT / 'report.md')


if __name__ == '__main__':
    main()
