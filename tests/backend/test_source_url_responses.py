"""Both response transports retain evidence URL mappings without changing empty responses."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings


@pytest.mark.parametrize("endpoint", ["/api/run", "/api/run/stream"])
@pytest.mark.parametrize("source_urls", [{}, {"Report p. 1": "https://example.com/report.pdf"}])
def test_optional_source_urls_are_serialized_consistently(endpoint, source_urls):
    result = SimpleNamespace(status="answered", answer="10", citations=("Report p. 1",),
                             retrieval_attempts=1, source_urls=source_urls)
    agent = SimpleNamespace(invoke=lambda _: result,
                            stream=lambda _: iter([{"type": "result", "result": result}]))
    client = TestClient(create_app(settings=Settings(_env_file=None), v2_agent_factory=lambda: agent))
    response = client.post(endpoint, json={"agent_id": "agent_v2", "question": "Revenue?"})
    assert response.status_code == 200
    payload = response.json() if endpoint == "/api/run" else json.loads(response.text)["result"]
    if source_urls:
        assert payload["source_urls"] == source_urls
    else:
        assert "source_urls" not in payload
    assert payload["citations"] == ["Report p. 1"]
