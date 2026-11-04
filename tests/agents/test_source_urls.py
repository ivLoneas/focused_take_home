"""Public report links follow retrieved evidence through every agent result path."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables import RunnableLambda

from agents.agent_v2 import AgentV2, AgentV2Config
from agents.baseline import BaselineAgent
from agents.models import AgentResult
from agents.settings import AgentConfig
from agents.tools.models import RetrievedChunk


@pytest.fixture(autouse=True)
def tracing_off(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGSMITH_AGENT_ID", raising=False)
    monkeypatch.delenv("LANGSMITH_AGENT_ENVIRONMENT", raising=False)


@pytest.mark.parametrize("variant", ["baseline", "v2_invoke", "v2_stream"])
def test_agent_preserves_public_source_urls_with_original_citation_labels(variant):
    evidence = [
        RetrievedChunk("Revenue 10", "10-K | apple | FY2025 Q4 | pp. 30-33", {"url": "https://reports.example/apple.pdf?x=1"}),
        RetrievedChunk("Revenue 11", "Another page", {"url": "http://reports.example/other.pdf"}),
        RetrievedChunk("Revenue 12", "No URL", {}),
        RetrievedChunk("Revenue 13", "Unsafe URL", {"url": "javascript:alert(1)"}),
        RetrievedChunk("Revenue 14", "Credentialed URL", {"url": "https://user:secret@example.com/private.pdf"}),
    ]
    decisions = {"out_of_domain": False, "needs_clarification": False, "companies": ["Apple"],
                 "required_facts": ["revenue"], "retrieval_query": "revenue", "is_sufficient": True}
    model = SimpleNamespace(
        invoke=lambda _: AIMessage(content="Revenue 10"),
        stream=lambda _: iter([AIMessageChunk(content="Revenue 10")]),
        with_structured_output=lambda schema: RunnableLambda(lambda _: schema.model_validate(decisions)),
    )
    options = {"retriever": Mock(return_value=evidence), "max_retrieval_attempts": 1}
    if variant == "baseline":
        agent = BaselineAgent(model, config=AgentConfig(_env_file=None), **options)
    else:
        agent = AgentV2(model, routing_model=model, domain_gate=SimpleNamespace(invoke=lambda _: True),
                        config=AgentV2Config(streaming=variant == "v2_stream", _env_file=None), **options)
    result = list(agent.stream("Apple revenue?"))[-1]["result"] if variant == "v2_stream" else agent.invoke("Apple revenue?")
    assert result.source_urls == {evidence[0].source: evidence[0].metadata["url"],
                                  evidence[1].source: evidence[1].metadata["url"]}
    assert result.citations == tuple(chunk.source for chunk in evidence)
    assert result.answer == "Revenue 10" and result.retrieval_attempts == 1


def test_results_have_independent_empty_source_maps_by_default():
    first = AgentResult("out_of_domain", "Ask about reports.", (), 0)
    second = AgentResult("needs_clarification", "Which company?", (), 0)
    assert first.source_urls == second.source_urls == {}
    assert first.source_urls is not second.source_urls


@pytest.mark.parametrize("url", [None, "", 42, "data:text/html,x", "file:///tmp/report.pdf", "ftp://example.com/report", "https:///report"])
def test_result_assembly_omits_invalid_metadata_urls(url):
    from agents.workflow import FinancialReportAgent

    result = FinancialReportAgent._result({
        "status": "answered", "answer": "10", "context": [RetrievedChunk("Revenue", "Report p. 1", {"url": url})],
        "retrieval_attempts": 1,
    })
    assert result.source_urls == {}
    assert result.citations == ("Report p. 1",)
