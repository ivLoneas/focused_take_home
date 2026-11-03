"""Render the measured results and migration audit as Markdown."""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
summary = json.loads((OUT / 'summary.json').read_text())
manifest = json.loads((OUT / 'run-manifest.json').read_text())


def select(suite, text):
    return next(value for label, value in suite['providers'].items() if text.lower() in label.lower())


full = summary['full.json']
behavior = summary['behavior.json']
baseline, v2 = select(full, 'baseline'), select(full, 'v2')
ba, va = select(behavior, 'baseline'), select(behavior, 'v2')
lines = [
    '# Model refresh: baseline and agent v2 — 3 November 2026',
    '',
    'Both agents were freshly evaluated on the same 114 questions and assertions. The separate ten-case behavior '
    'suite was then run for both agents. Cache and sharing were disabled; global concurrency was four. '
    'Each case/provider has one measured invocation per suite.',
    '',
    '| Measure | Baseline | Agent v2 |',
    '| --- | ---: | ---: |',
]
for label, key in [('Strict full-suite passes', 'strict_passes'), ('Provider runtime errors', 'provider_errors'),
                   ('Mean answer latency (seconds)', 'mean_answer_seconds'),
                   ('Median answer latency (seconds)', 'median_answer_seconds'),
                   ('p95 answer latency (seconds)', 'p95_answer_seconds')]:
    a, b = baseline[key], v2[key]
    if key == 'strict_passes':
        a, b = f'{a}/114 ({a/114:.1%})', f'{b}/114 ({b/114:.1%})'
    elif isinstance(a, list):
        a, b = len(a), len(b)
    elif isinstance(a, float):
        a, b = f'{a:.2f}', f'{b:.2f}'
    lines.append(f'| {label} | {a} | {b} |')
lines += [f"| Behavior-suite strict passes | {ba['strict_passes']}/10 | {va['strict_passes']}/10 |", '',
          'Strict passes require every applicable validity, workflow, quality and formatting check. Runtime failures '
          'remain in the 114-case denominator. Answer latency excludes grading and uses completed responses only. '
          'P95 uses sorted index floor((n−1)×0.95).', '',
          '## Model audit and compatibility', '',
          '- Baseline answering/planning, backend chat, evaluation chat and all four active Promptfoo graders use '
          '`gpt-6.1-terra`. V2 planning/sufficiency uses `gpt-6-luna`; Jev remains the domain gate.',
          '- The initially edited `gpt-6-terra` default had no official model page. The official catalog lists '
          '`gpt-6.1-terra`, matching the pre-existing local `.env`. API model retrieval verified both selected model IDs.',
          '- Baseline evaluation no longer sends `temperature=0`. Baseline keeps model-default reasoning, and v2 keeps '
          'low reasoning. The graph uses JSON-schema structured outputs; this change does not introduce model-bound '
          'function calls or migrate endpoints.',
          '- Active source/config/docs/tests contain no older GPT model IDs. Historical report exports and snapshots '
          'retain the model names actually used when they were produced. Explicit valid model overrides remain supported.',
          '',
          'Sources: [OpenAI model catalog](https://developers.openai.com/api/docs/models), '
          '[GPT-6.1 Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra), '
          '[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), '
          '[migration parameter rules](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra#migration-quickstart).',
          '', '## Check and topic results', '', '| Check | Baseline | Agent v2 |', '| --- | ---: | ---: |']
for name in sorted(set(baseline['checks']) | set(v2['checks'])):
    a, b = baseline['checks'].get(name, {}), v2['checks'].get(name, {})
    lines.append(f"| {name} | {a.get('passed',0)}/{a.get('checks',0)} | {b.get('passed',0)}/{b.get('checks',0)} |")
lines += ['', '| Topic | Baseline | Agent v2 |', '| --- | ---: | ---: |']
for name, a in baseline['topics'].items():
    b = v2['topics'][name]
    lines.append(f"| {name} | {a['passed']}/{a['cases']} | {b['passed']}/{b['cases']} |")
lines += ['', '## Remaining failures', '']
for suite_name, suite in summary.items():
    lines += [f'### {suite_name}', '']
    for label, provider in suite['providers'].items():
        lines += [f'**{label}:**', '']
        if not provider['failures']:
            lines += ['None.', '']
        else:
            for failure in provider['failures']:
                reason = ' '.join((failure.get('reason') or 'See raw grading result.').split())
                lines.append(f"- {failure['id']}: {reason}")
            lines += ['']
lines += ['## Comparison limits and reproducibility', '',
          'The previous aligned run reported baseline 103/114 and v2 101/114, with both at 8/10 on the behavior suite. '
          'Those runs used older answer/routing models and an older grader. The new scores therefore do not isolate '
          'answer-model improvement: grader changes, single-run variation and the concurrent agent independence '
          'refactor captured in this source snapshot also limit causal comparisons.', '',
          'The source was frozen before live evaluation to prevent concurrent workspace edits from changing an '
          'in-flight run. `source-snapshot.tar.gz` contains the exact source, tests and evaluation inputs used; '
          '`run-manifest.json` records their hashes, effective model choices and snapshot location. Labels containing '
          '“unchanged” are inherited Promptfoo labels, not a claim that models match historical runs.', '',
          'Preflight verified the exact 100 document paths/checksums and 20,274 chunks against `data/active_manifest.csv`. '
          'No source data, ETL or embeddings were changed. LangSmith tracing was enabled, synchronous trace '
          'create/update succeeded, and both live smoke responses completed with actual model usage. '
          'This does not claim remote readback of every stored span.', '',
          'Independent regression tests were written first and failed for the stale defaults and unsupported '
          'temperature setting. After the fix, the full suite passed: **881 passed, 19 opt-in tests skipped**. '
          'Ruff passed on the changed Python files and `git diff --check` passed.', '',
          'Recorded tokens and model-level v2 usage are in `summary.json`; raw responses, discovery/retrieval '
          'trajectories and grader explanations are in `full.json` and `behavior.json`. Provider exceptions can '
          'omit incurred token usage. No dollar estimate reuses historical model prices.', '',
          f"Full evaluation: `{full['eval_id']}`. Behavior evaluation: `{behavior['eval_id']}`.", '',
          'From `evals/`, rerun the current configuration:', '', '```sh',
          'PYTHONPATH=.. PROMPTFOO_PYTHON=../.venv/bin/python ./node_modules/.bin/promptfoo eval \\',
          '  -c promptfooconfig.aligned_comparison.yaml --env-file ../.env --no-cache --no-share \\',
          '  --max-concurrency 4 --no-table --no-progress-bar -o ../reports/next-model-full.json',
          'PYTHONPATH=.. PROMPTFOO_PYTHON=../.venv/bin/python ./node_modules/.bin/promptfoo eval \\',
          '  -c promptfooconfig.agent_v2_behavior.yaml --env-file ../.env --no-cache --no-share \\',
          '  --max-concurrency 4 --no-table --no-progress-bar -o ../reports/next-model-behavior.json',
          '```', '']
(OUT / 'report.md').write_text('\n'.join(lines))
print(OUT / 'report.md')
