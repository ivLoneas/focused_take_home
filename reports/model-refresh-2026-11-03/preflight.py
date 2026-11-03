"""Verify the pinned database, selected API models and synchronous trace writes."""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from langsmith import Client
from openai import OpenAI

from agents.agent_v2.settings import AgentV2Config
from etl.companies import COMPANY_TABLES
from evals.provider import ProviderSettings

OUT = Path(__file__).resolve().parent
settings = ProviderSettings()
config = AgentV2Config(model=settings.chat_model)
assert config.langsmith_tracing, 'LangSmith tracing must be enabled for the evaluation'
assert config.typesafe_api_key, 'TYPESAFE_API_KEY is required for agent v2'
with Path('data/active_manifest.csv').open() as stream:
    manifest = {
        (row['path'], row['sha256'])
        for row in csv.DictReader(stream)
    }
with psycopg.connect(settings.database_url) as connection:
    rows = connection.execute('SELECT source_path, source_sha256 FROM etl_documents').fetchall()
    assert set(rows) == manifest, 'Database documents differ from the active manifest'
    chunks = {
        company: connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
        for company, table in COMPANY_TABLES.items()
    }
with OpenAI(api_key=settings.openai_api_key.get_secret_value(), timeout=30) as client:
    available = {
        model: client.models.retrieve(model).id
        for model in [settings.chat_model, config.routing_model, settings.embedding_model]
    }
trace_id = uuid4()
client = Client(api_url=config.langsmith_endpoint, api_key=config.langsmith_api_key.get_secret_value())
client.create_run(
    name='model-refresh-preflight', run_type='chain', id=trace_id,
    inputs={'purpose': 'Verify trace writes before paired evaluations'},
    project_name=config.langsmith_project,
)
client.update_run(trace_id, outputs={'verified': True}, end_time=datetime.now(UTC))
result = {
    'documents': len(rows), 'manifest_paths_and_checksums_match': True,
    'chunks': chunks, 'total_chunks': sum(chunks.values()),
    'available_models': available, 'trace_create_update_succeeded': True,
    'trace_run_id': str(trace_id), 'trace_endpoint': config.langsmith_endpoint,
    'tracing_enabled': config.langsmith_tracing, 'typesafe_model': config.typesafe_model,
    'embedding_dimensions': settings.embedding_dimensions,
    'retrieval_limit': settings.retrieval_limit,
    'max_retrieval_attempts': settings.max_retrieval_attempts,
}
(OUT / 'preflight.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
