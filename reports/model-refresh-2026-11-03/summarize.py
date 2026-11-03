"""Summarize fresh paired Promptfoo exports without additional grading."""

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent


def summarize(path):
    raw = json.loads(path.read_text())
    groups = defaultdict(dict)
    for row in raw['results']['results']:
        groups[row['provider']['label']][row['testCase']['vars']['id']] = row
    providers = {}
    for label, cases in groups.items():
        checks = defaultdict(Counter)
        topics = defaultdict(Counter)
        errors = []
        failures = []
        latencies = []
        tokens = Counter()
        by_model = defaultdict(Counter)
        for cid, row in cases.items():
            topic = row['testCase']['vars']['topic']
            topics[topic]['cases'] += 1
            topics[topic]['passed'] += bool(row['success'])
            response = row.get('response') or {}
            metadata = response.get('metadata') or {}
            if metadata.get('answer_latency_ms') is not None:
                latencies.append(metadata['answer_latency_ms'] / 1000)
            if not metadata.get('status'):
                errors.append({'id': cid, 'error': row.get('error') or response.get('error')})
            if not row['success']:
                failures.append({'id': cid, 'reason': row.get('error') or (row.get('gradingResult') or {}).get('reason')})
            for check in (row.get('gradingResult') or {}).get('componentResults', []):
                name = (check.get('assertion') or {}).get('metric', 'unlabelled')
                checks[name]['checks'] += 1
                checks[name]['passed'] += bool(check['pass'])
            telemetry = metadata.get('telemetry') or {}
            tokens.update({k: v for k, v in telemetry.items() if isinstance(v, (int, float))})
            for model, usage in telemetry.get('by_model', {}).items():
                by_model[model].update(usage)
        providers[label] = {
            'cases': len(cases), 'strict_passes': sum(bool(r['success']) for r in cases.values()),
            'provider_errors': errors, 'failures': failures,
            'mean_answer_seconds': statistics.mean(latencies) if latencies else None,
            'median_answer_seconds': statistics.median(latencies) if latencies else None,
            'p95_answer_seconds': sorted(latencies)[int((len(latencies)-1)*.95)] if latencies else None,
            'completed_responses': len(latencies), 'checks': dict(checks), 'topics': dict(topics),
            'telemetry_totals': dict(tokens), 'by_model': dict(by_model),
            'usage_limit': 'Provider exceptions may omit incurred usage. No dollar estimates use historical model rates.',
        }
    labels = list(groups)
    assert len(labels) == 2
    baseline = next(label for label in labels if 'baseline' in label.lower())
    v2 = next(label for label in labels if 'v2' in label.lower())
    assert groups[baseline].keys() == groups[v2].keys()
    outcomes = defaultdict(list)
    for cid, a in groups[baseline].items():
        b = groups[v2][cid]
        assert a['testCase']['vars'] == b['testCase']['vars'], cid
        assert a['testCase']['assert'] == b['testCase']['assert'], cid
        name = ('both_pass' if a['success'] and b['success'] else 'baseline_only_pass' if a['success']
                else 'v2_only_pass' if b['success'] else 'both_fail')
        outcomes[name].append(cid)
    return {'eval_id': raw['evalId'], 'providers': providers, 'paired_vars_assertions_match': True,
            'paired_outcomes': dict(outcomes), 'stats': raw['results']['stats']}


if __name__ == '__main__':
    summary = {name: summarize(OUT / name) for name in ['full.json', 'behavior.json']}
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    for name, suite in summary.items():
        print(name, suite['eval_id'])
        for label, result in suite['providers'].items():
            print(label, result['strict_passes'], '/', result['cases'],
                  'provider errors', len(result['provider_errors']),
                  'mean answer seconds', result['mean_answer_seconds'])
