"""Contracts for tools extracted from the agent workflow into a standalone package."""

from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest

from agents.baseline import RetrievalRequest as PublicRetrievalRequest
from agents.baseline import RetrievedChunk as PublicRetrievedChunk
from agents.baseline.baseline_agent import BaselineAgent
from agents.baseline.models import RetrievalRequest as BaselineRetrievalRequest
from agents.baseline.models import RetrievedChunk as BaselineRetrievedChunk
from agents.tools import BaselineRetrieverAdapter, PgVectorRetriever, invoke_retriever, placeholder_retriever
from agents.tools.models import RetrievalRequest, RetrievedChunk


@pytest.fixture
def retrieval_request():
    return RetrievalRequest(company="Apple", query="Apple FY2025 revenue", required_facts=("net sales",), attempt=2)


def test_tools_package_owns_retrieval_implementations_and_contracts():
    """The package is the canonical inspection point while established baseline type imports stay valid."""
    assert PgVectorRetriever.__module__ == "agents.tools.retrieval"
    assert BaselineRetrieverAdapter.__module__ == "agents.tools.retrieval"
    assert RetrievalRequest.__module__ == "agents.tools.models"
    assert RetrievedChunk.__module__ == "agents.tools.models"
    assert PublicRetrievalRequest is BaselineRetrievalRequest is RetrievalRequest
    assert PublicRetrievedChunk is BaselineRetrievedChunk is RetrievedChunk
    assert not hasattr(BaselineAgent, "_invoke_retriever")


def test_tool_contracts_preserve_frozen_request_and_independent_chunk_metadata(retrieval_request):
    assert retrieval_request.attempt == 2
    with pytest.raises(FrozenInstanceError):
        retrieval_request.query = "different"

    first = RetrievedChunk(text="Evidence", source="Report p. 1")
    second = RetrievedChunk(text="Other evidence", source="Report p. 2")
    assert first.metadata == second.metadata == {}
    assert first.metadata is not second.metadata


def test_invoke_retriever_passes_complete_request_to_callable_and_materializes_generator(retrieval_request):
    chunks = [RetrievedChunk(text="Revenue", source="Apple report p. 7")]
    tool = Mock(return_value=(chunk for chunk in chunks))

    result = invoke_retriever(tool, retrieval_request)

    assert isinstance(result, list)
    assert result == chunks
    assert result[0] is chunks[0]
    tool.assert_called_once_with(retrieval_request)


def test_invoke_retriever_accepts_invoke_object_and_materializes_sequence(retrieval_request):
    chunks = (RetrievedChunk(text="Revenue", source="Apple report p. 7"),)

    class Tool:
        def invoke(self, received):
            assert received is retrieval_request
            return chunks

    result = invoke_retriever(Tool(), retrieval_request)

    assert isinstance(result, list)
    assert result == list(chunks)


def test_invoke_retriever_prefers_callable_when_both_interfaces_exist(retrieval_request):
    class Tool:
        def __call__(self, received):
            assert received is retrieval_request
            return []

        def invoke(self, received):
            raise AssertionError("Callable interface must retain priority")

    assert invoke_retriever(Tool(), retrieval_request) == []


@pytest.mark.parametrize("tool", [None, object(), 1, "retriever", type("Tool", (), {"invoke": None})()])
def test_invoke_retriever_rejects_objects_without_supported_interface(tool, retrieval_request):
    with pytest.raises(TypeError, match=r"retriever must be callable or provide invoke\(request\)"):
        invoke_retriever(tool, retrieval_request)


@pytest.mark.parametrize("use_invoke", [False, True])
def test_invoke_retriever_propagates_tool_errors_without_wrapping(retrieval_request, use_invoke):
    error = RuntimeError("retrieval failed")

    def fail(received):
        assert received is retrieval_request
        raise error

    tool = type("Tool", (), {"invoke": staticmethod(fail)})() if use_invoke else fail

    with pytest.raises(RuntimeError, match="retrieval failed") as raised:
        invoke_retriever(tool, retrieval_request)

    assert raised.value is error


def test_invoke_retriever_propagates_failure_while_consuming_generator(retrieval_request):
    error = RuntimeError("stream failed")

    def stream(received):
        assert received is retrieval_request
        yield RetrievedChunk(text="Partial", source="Report p. 1")
        raise error

    with pytest.raises(RuntimeError, match="stream failed") as raised:
        invoke_retriever(stream, retrieval_request)

    assert raised.value is error


def test_placeholder_returns_empty_evidence_without_reusing_a_mutable_result(retrieval_request):
    first = placeholder_retriever(retrieval_request)
    second = placeholder_retriever(retrieval_request)
    assert first == second == []
    assert first is not second
