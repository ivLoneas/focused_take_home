"""Verify complete paired runs, frozen inputs, model usage and artifact hygiene."""

import hashlib
import json
import re
import tarfile
from pathlib import Path

from agents.agent_v2.settings import AgentV2Config
from evals.provider import ProviderSettings

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
manifest = json.loads((OUT / 'run-manifest.json').read_text())
snapshot = Path(manifest['snapshot_directory'])
assert all(hashlib.sha256((snapshot / name).read_bytes()).hexdigest() == digest
           for name, digest in manifest['files'].items())
assert hashlib.sha256((ROOT / 'data/active_manifest.csv').read_bytes()).hexdigest() == manifest['active_manifest_sha256']
results = {}
for name, expected in [('full.json', 114), ('behavior.json', 10)]:
    raw = json.loads((OUT / name).read_text())
    rows = raw['results']['results']
    assert len(rows) == expected * 2
    groups = {}
    for row in rows:
        groups.setdefault(row['provider']['label'], []).append(row)
    assert len(groups) == 2
    for label, provider_rows in groups.items():
        assert len(provider_rows) == expected
        assert len({r['testCase']['vars']['id'] for r in provider_rows}) == expected
        if 'v2' in label.lower():
            models = {model for row in provider_rows
                      for model in (row.get('response') or {}).get('metadata', {}).get('telemetry', {}).get('by_model', {})}
            assert {'gpt-6.1-terra', 'gpt-6-luna'} <= models
            assert all(model.startswith(('gpt-6.1-terra', 'gpt-6-luna', 'jev-')) for model in models)
    grader = raw['config']['defaultTest']['options']['provider']
    assert grader == 'openai:gpt-6.1-terra'
    results[name] = {'invocations': len(rows), 'cases_per_provider': expected, 'grader': grader}
old = re.compile(r'gpt[-:](?:[345](?:\.\d+)?(?:[-\w.]*)|6-terra)\b')
stale = []
for folder in ['agents', 'backend', 'etl', 'evals', 'tests', 'utils']:
    for path in (ROOT / folder).rglob('*'):
        if path.is_file() and path.suffix in {'.py', '.md', '.yaml', '.yml', '.json', '.toml'}:
            if any(part in {'node_modules', '__pycache__'} for part in path.parts):
                continue
            if old.search(path.read_text()):
                stale.append(str(path.relative_to(ROOT)))
assert not stale, stale
settings = ProviderSettings()
config = AgentV2Config()
secrets = [settings.openai_api_key.get_secret_value(), config.typesafe_api_key.get_secret_value(),
           config.langsmith_api_key.get_secret_value()]
leaked = []
for path in OUT.iterdir():
    if path.is_file() and path.suffix in {'.json', '.log', '.md', '.py'}:
        content = path.read_text()
        if any(secret and secret in content for secret in secrets):
            leaked.append(path.name)
with tarfile.open(OUT / 'source-snapshot.tar.gz') as archive:
    for member in archive.getmembers():
        if member.isfile():
            content = archive.extractfile(member).read()
            if any(secret and secret.encode() in content for secret in secrets):
                leaked.append('source-snapshot.tar.gz:' + member.name)
assert not leaked, leaked
result = {'frozen_source_hashes_match': True, 'active_manifest_unchanged': True,
          'paired_runs_complete': results, 'no_active_legacy_gpt_ids': True,
          'v2_actual_usage_uses_requested_models': True, 'configured_secrets_absent_from_artifacts': True}
(OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
