"""Shared mechanics for independent financial-report agent versions."""

from abc import ABC, abstractmethod
from typing import Any, Literal
from urllib.parse import urlsplit

from langchain_core.tracers import LangChainTracer
from langsmith import Client, agent_address

from agents.models import AgentResult, ChatModel, WorkflowState
from agents.settings import AgentConfig
from agents.tools import DatabaseCoverage, invoke_retriever, placeholder_retriever
from agents.tools.models import RetrievalRequest, Retriever


class FinancialReportAgent(ABC):
    """Share tracing, validation and retrieval while versions own their graphs and prompts."""

    def __init__(
        self,
        model: ChatModel,
        *,
        retriever: Retriever = placeholder_retriever,
        coverage: DatabaseCoverage | None = None,
        max_retrieval_attempts: int = 3,
        config: AgentConfig | None = None,
    ) -> None:
        if isinstance(max_retrieval_attempts, bool) or not isinstance(max_retrieval_attempts, int):
            raise TypeError("max_retrieval_attempts must be an integer")
        if max_retrieval_attempts < 1:
            raise ValueError("max_retrieval_attempts must be at least 1")

        self.model = model
        self.retriever = retriever
        self.coverage = coverage
        self.max_retrieval_attempts = max_retrieval_attempts
        self.config = config or AgentConfig()
        self.tracer = self._build_tracer()
        self.graph = self._build_graph()

    def _build_tracer(self) -> LangChainTracer | None:
        if not self.config.langsmith_tracing:
            return None

        api_key = self.config.langsmith_api_key
        if api_key is None:
            raise ValueError("LANGSMITH_API_KEY is required when LANGSMITH_TRACING is enabled")
        client = Client(
            api_key=api_key.get_secret_value(),
            api_url=self.config.langsmith_endpoint,
        )
        if self.config.langsmith_agent_id and self.config.langsmith_agent_environment:
            return LangChainTracer(
                address=agent_address(self.config.langsmith_agent_id, self.config.langsmith_agent_environment),
                client=client,
            )
        return LangChainTracer(project_name=self.config.langsmith_project, client=client)

    @staticmethod
    def _route_question(
        state: WorkflowState,
    ) -> Literal["out_of_domain", "needs_clarification", "answer", "retrieve"]:
        analysis = state["analysis"]
        if analysis.out_of_domain:
            return "out_of_domain"
        if analysis.needs_clarification:
            return "needs_clarification"
        if "available_data" in state and (
            not analysis.companies or (analysis.coverage_requested and not analysis.required_facts)
        ):
            return "answer"
        return "retrieve"

    @staticmethod
    def _return_out_of_domain(state: WorkflowState) -> dict[str, Any]:
        return {
            "status": "out_of_domain",
            "answer": "I can only answer questions grounded in the available company financial reports.",
        }

    @staticmethod
    def _ask_specific_details(state: WorkflowState) -> dict[str, Any]:
        question = state["analysis"].clarification_question
        return {
            "status": "needs_clarification",
            "answer": question or "Which company, fiscal period, and financial metric should I use?",
        }

    def _retrieve_context(self, state: WorkflowState) -> dict[str, Any]:
        attempt = state.get("retrieval_attempts", 0) + 1
        companies = list(dict.fromkeys(state["analysis"].companies))
        if not companies:
            raise ValueError("Factual retrieval requires at least one company in QuestionAnalysis.companies")
        chunks = []
        for company in companies:
            request = RetrievalRequest(
                company=company,
                query=state["retrieval_query"],
                required_facts=tuple(state["analysis"].required_facts),
                attempt=attempt,
            )
            chunks.extend(invoke_retriever(self.retriever, request))
        return {
            "context": [*state.get("context", []), *chunks],
            "retrieval_attempts": attempt,
        }

    def _route_after_assessment(self, state: WorkflowState) -> Literal["retrieve", "answer"]:
        if state["context_is_sufficient"] or state["retrieval_attempts"] >= self.max_retrieval_attempts:
            return "answer"
        return "retrieve"

    @staticmethod
    def _result(state: WorkflowState) -> AgentResult:
        chunks = state.get("context", [])
        source_urls = {}
        for chunk in chunks:
            url = chunk.metadata.get("url")
            if not isinstance(url, str) or any(ord(character) < 32 for character in url):
                continue
            url = url.strip()
            try:
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    continue
            except ValueError:
                continue
            source_urls.setdefault(chunk.source, url)
        return AgentResult(
            status=state["status"], answer=state["answer"],
            citations=tuple(dict.fromkeys(chunk.source for chunk in chunks)),
            retrieval_attempts=state.get("retrieval_attempts", 0),
            tool_calls=tuple(state.get("tool_calls", [])), source_urls=source_urls,
        )

    @abstractmethod
    def _build_graph(self):
        """Compile the version's workflow."""
