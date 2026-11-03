"""Summarize paired exports without new inference or grading."""

import json
import runpy
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
helpers = runpy.run_path(str(ROOT / 'reports/agent-v2-refinement-2026-11-03/summarize.py'))


def paired(path):
    data = json.loads(path.read_text())
    groups = {}
    for row in data['results']['results']:
        groups.setdefault(row['provider']['label'], {})[row['testCase']['vars']['id']] = row
    base_label = next(label for label in groups if 'baseline' in label.lower())
    v2_label = next(label for label in groups if 'v2' in label.lower())
    base, v2 = groups[base_label], groups[v2_label]
    assert base.keys() == v2.keys()
    cells = {'both_pass': [], 'baseline_only_pass': [], 'v2_only_pass': [], 'both_fail': []}
    latencies = []
    for cid in base:
        a, b = base[cid], v2[cid]
        assert a['testCase']['vars'] == b['testCase']['vars'], cid
        assert a['testCase']['assert'] == b['testCase']['assert'], cid
        key = ('both_pass' if a['success'] and b['success'] else
               'baseline_only_pass' if a['success'] else 'v2_only_pass' if b['success'] else 'both_fail')
        cells[key].append(cid)
        am = (a.get('response') or {}).get('metadata', {})
        bm = (b.get('response') or {}).get('metadata', {})
        if am.get('answer_latency_ms') is not None and bm.get('answer_latency_ms') is not None:
            latencies.append(am['answer_latency_ms'] - bm['answer_latency_ms'])
    return {'evaluation_id': data['evalId'], 'paired_cases': len(base),
            'test_vars_and_assertions_identical': True, 'outcomes': cells,
            'mean_paired_latency_saved_by_v2_ms': statistics.mean(latencies),
            'median_paired_latency_saved_by_v2_ms': statistics.median(latencies)}


def main():
    result = {}
    for name in ['full.json', 'behavior.json']:
        providers = helpers['summarize'](OUT / name)
        raw = json.loads((OUT / name).read_text())
        for label, group in providers.items():
            rows = [r for r in raw['results']['results'] if r['provider']['label'] == label]
            valid = [r for r in rows if (r.get('response') or {}).get('metadata', {}).get('status')]
            group['completed_provider_responses'] = len(valid)
            assertion_counts = {}
            for row in rows:
                for component in (row.get('gradingResult') or {}).get('componentResults', []):
                    metric = component.get('assertion', {}).get('metric')
                    if metric:
                        assertion_counts[metric] = assertion_counts.get(metric, 0) + 1
            group['assertion_counts'] = assertion_counts
            group['mean_provider_latency_ms_all_invocations'] = statistics.mean(r['latencyMs'] for r in rows)
            group['usage_missing_cases'] = [r['testCase']['vars']['id'] for r in rows
                                            if not (r.get('response') or {}).get('metadata', {}).get('telemetry')]
            group['provider_error_cases'] = [
                {'id': r['testCase']['vars']['id'], 'error': r.get('error'),
                 'failure_reason': r.get('failureReason')}
                for r in rows if r not in valid
            ]
            words = [len(r['response']['output'].split()) for r in valid]
            group['mean_completed_answer_words'] = statistics.mean(words)
            group['median_completed_answer_words'] = statistics.median(words)
            group['cost_limitation'] = 'Reported usage only; provider exceptions can omit incurred model usage.'
            ood = [r for r in valid if r['testCase']['vars']['topic'] == 'out_of_distribution']
            if ood:
                group['out_of_distribution_path'] = {
                    'cases': len(ood),
                    'mean_latency_ms': statistics.mean(r['response']['metadata']['answer_latency_ms'] for r in ood),
                    'model_calls': sum(r['response']['metadata']['telemetry']['model_calls'] for r in ood),
                    'retrieval_attempts': sum(r['response']['metadata']['retrieval_attempts'] for r in ood),
                }
        result[name] = {'providers': providers, 'paired': paired(OUT / name),
                        'promptfoo_stats': raw['results']['stats']}
    (OUT / 'summary.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    for name, value in result.items():
        print(name)
        for label, group in value['providers'].items():
            runtime = group['estimated_models_usd'] + group['estimated_embeddings_usd']
            print(label, group['strict_passes'], '/', group['cases'],
                  'mean latency seconds', round(group['mean_answer_latency_ms'] / 1000, 2),
                  'runtime estimate USD', round(runtime, 6),
                  'with grading USD', round(group['estimated_total_usd'], 6))
        print('paired', {k: len(v) for k, v in value['paired']['outcomes'].items()})


if __name__ == '__main__':
    main()
