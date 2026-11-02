"""Company selection is explicit at every retrieval boundary."""

from typing import get_args, get_type_hints
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from agents.baseline.models import QuestionAnalysis
from agents.baseline.prompts import QUESTION_ANALYSIS_PROMPT
from agents.tools import BaselineRetrieverAdapter, PgVectorRetriever
from agents.tools.models import RetrievalRequest
from etl import store

COMPANIES = ("Alphabet", "Amazon", "Apple", "Meta", "Netflix")


@pytest.mark.parametrize("company", COMPANIES)
def test_required_company_literal_routes_adapter_to_only_selected_retriever(company):
    retrievers = {
        name: Mock(invoke=Mock(return_value=[Document(page_content=name, metadata={"company": name})]))
        for name in COMPANIES
    }
    request = RetrievalRequest(company=company, query="FY2025 revenue", required_facts=("revenue",), attempt=1)

    chunks = BaselineRetrieverAdapter(retrievers=retrievers).invoke(request)

    assert [chunk.text for chunk in chunks] == [company]
    for name, retriever in retrievers.items():
        if name == company:
            retriever.invoke.assert_called_once_with("FY2025 revenue")
        else:
            retriever.invoke.assert_not_called()


def test_retrieval_request_is_bounded_but_analysis_discovers_arbitrary_company_names():
    annotation = get_type_hints(RetrievalRequest)["company"]
    assert set(get_args(annotation)) == set(COMPANIES)
    analysis = QuestionAnalysis.model_json_schema()
    item_schema = analysis["properties"]["companies"]["items"]
    assert item_schema == {"type": "string"}
    assert QuestionAnalysis(out_of_domain=False, needs_clarification=False, companies=["Future Issuer"]).companies == ["Future Issuer"]


def test_company_is_required_in_request_and_pgvector_constructor():
    with pytest.raises(TypeError):
        RetrievalRequest(query="revenue", required_facts=(), attempt=1)
    with pytest.raises((TypeError, ValidationError)):
        PgVectorRetriever(embeddings=Mock(), connection_factory=Mock())


@pytest.mark.parametrize("company", [None, "", " ", "Walmart", "apple", "Apple; DROP TABLE etl_documents;--", 42])
def test_invalid_company_request_cannot_reach_retrieval(company):
    retriever = Mock()
    with pytest.raises((ValueError, TypeError)):
        request = RetrievalRequest(company=company, query="revenue", required_facts=(), attempt=1)
        BaselineRetrieverAdapter(retrievers={"Apple": retriever}).invoke(request)
    retriever.invoke.assert_not_called()


@pytest.mark.parametrize("company", [None, "", "Walmart", "apple", "Apple; DROP TABLE etl_documents;--", 42])
def test_invalid_company_store_search_rejected_before_sql(company):
    connection = Mock()
    vector = [1.0] + [0.0] * 1535
    with pytest.raises((ValueError, TypeError)):
        store.search(connection, vector, company=company)
    connection.execute.assert_not_called()
    connection.cursor.assert_not_called()
    connection.transaction.assert_not_called()


def test_store_search_cannot_omit_company():
    connection = Mock()
    with pytest.raises(TypeError):
        store.search(connection, [1.0] + [0.0] * 1535)
    connection.execute.assert_not_called()


def test_missing_company_backend_does_not_fall_back_to_other_company():
    apple = Mock()
    adapter = BaselineRetrieverAdapter(retrievers={"Apple": apple})
    request = RetrievalRequest(company="Amazon", query="revenue", required_facts=(), attempt=1)
    with pytest.raises((ValueError, KeyError), match="Amazon"):
        adapter.invoke(request)
    apple.invoke.assert_not_called()


def test_retrieval_tool_requires_company_literal_and_describes_tables():
    apple = Mock(invoke=Mock(return_value=[]))
    tool = BaselineRetrieverAdapter(retrievers={"Apple": apple}).as_tool()
    schema = tool.get_input_schema().model_json_schema()
    assert {"company", "query"} <= set(schema["required"])
    assert set(schema["properties"]["company"]["enum"]) == set(COMPANIES)
    for company in COMPANIES:
        assert company in tool.description
        assert "etl_chunks_" + company.lower() in tool.description
    assert tool.invoke({"company": "Apple", "query": "FY2025 revenue"}) == []
    apple.invoke.assert_called_once_with("FY2025 revenue")


@pytest.mark.parametrize("arguments", [{"query": "revenue"}, {"company": "Walmart", "query": "revenue"}])
def test_retrieval_tool_invalid_company_arguments_fail_before_backend(arguments):
    apple = Mock()
    tool = BaselineRetrieverAdapter(retrievers={"Apple": apple}).as_tool()
    with pytest.raises(ValidationError):
        tool.invoke(arguments)
    apple.invoke.assert_not_called()


def test_analysis_prompt_explains_discovery_and_per_company_retrieval():
    prompt = QUESTION_ANALYSIS_PROMPT.invoke({"question": "Compare Apple and Amazon FY2025 revenue"}).to_string()
    assert "companies" in prompt
    assert "listed_companies" in prompt
    assert "company_periods" in prompt
    assert "etl_chunks_" not in prompt
    assert "separate" in prompt.lower() or "per company" in prompt.lower()


def test_adapter_rejects_company_backend_configuration_mismatch():
    backend = Mock(company="Amazon")
    with pytest.raises(ValueError, match="Apple.*Amazon"):
        BaselineRetrieverAdapter(retrievers={"Apple": backend})
    backend.invoke.assert_not_called()


@pytest.mark.parametrize("query", [None, 42, "", "   ", "\t\n"])
def test_company_tool_rejects_invalid_query_before_backend(query):
    backend = Mock()
    tool = BaselineRetrieverAdapter(retrievers={"Apple": backend}).as_tool()
    with pytest.raises((TypeError, ValueError)):
        tool.invoke({"company": "Apple", "query": query})
    backend.invoke.assert_not_called()


@pytest.mark.parametrize("company", ["Google", "Facebook", "Apple,Amazon"])
def test_company_tool_requires_canonical_literal_instead_of_aliases_or_multiple_companies(company):
    backend = Mock()
    tool = BaselineRetrieverAdapter(retrievers={"Apple": backend}).as_tool()
    with pytest.raises(ValidationError):
        tool.invoke({"company": company, "query": "FY2025 revenue"})
    backend.invoke.assert_not_called()
