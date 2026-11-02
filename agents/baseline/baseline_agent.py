"""Baseline LangGraph workflow for financial-report questions."""

from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol, cast

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from langchain_core.tracers import LangChainTracer
from langgraph.graph import END, START, StateGraph
from langsmith import Client
from pydantic import BaseModel

from agents.baseline.models import (
    BaselineResult,
    ContextAssessment,
    QuestionAnalysis,
    RetrievalRequest,
    RetrievedChunk,
    WorkflowState,
)
from agents.baseline.prompts import ANSWER_PROMPT, CONTEXT_ASSESSMENT_PROMPT, QUESTION_ANALYSIS_PROMPT
from agents.settings import AgentConfig
from utils import format_bullets, format_evidence, require_nonblank_string


class ChatModel(Protocol):
    def invoke(self, input: object, **kwargs: Any) -> BaseMessage | str: ...

    def with_structured_output[OutputT: BaseModel](
        self,
        schema: type[OutputT],
        **kwargs: Any,
    ) -> Runnable[object, OutputT]: ...


class InvokableRetriever(Protocol):
    def invoke(self, request: RetrievalRequest) -> Sequence[RetrievedChunk]: ...


type Retriever = Callable[[RetrievalRequest], Sequence[RetrievedChunk]] | InvokableRetriever


def placeholder_retriever(_: RetrievalRequest) -> list[RetrievedChunk]:
    return []


class BaselineAgent:
    """Route a question, refine retrieval to its limit, then answer from accumulated evidence."""

    def __init__(
        self,
        model: ChatModel,
        *,
        retriever: Retriever = placeholder_retriever,
        max_retrieval_attempts: int = 3,
        config: AgentConfig | None = None,
    ) -> None:
        if isinstance(max_retrieval_attempts, bool) or not isinstance(max_retrieval_attempts, int):
            raise TypeError("max_retrieval_attempts must be an integer")
        if max_retrieval_attempts < 1:
            raise ValueError("max_retrieval_attempts must be at least 1")

        self.model = model
        self.retriever = retriever
        self.max_retrieval_attempts = max_retrieval_attempts
        self.config = config or AgentConfig()
        self.tracer = self._build_tracer()
        self.graph = self._build_graph()

    def invoke(self, question: str) -> BaselineResult:
        """Run one stateless question and return deduplicated evidence labels as citations."""

        question = require_nonblank_string(question, field_name="question")

        config: dict[str, Any] = {
            "recursion_limit": 2 * self.max_retrieval_attempts + 8,
            "run_name": "baseline-agent",
            "tags": ["baseline", "financial-report-rag"],
            "metadata": {
                "component": "baseline-agent",
                "workflow": "financial-report-rag",
                "model": self.config.model,
                "max_retrieval_attempts": self.max_retrieval_attempts,
            },
        }
        if self.tracer is not None:
            config["callbacks"] = [self.tracer]

        state = self.graph.invoke(
            {"question": question, "context": [], "retrieval_attempts": 0},
            config,
        )
        citations = tuple(dict.fromkeys(chunk.source for chunk in state.get("context", [])))
        return BaselineResult(
            status=state["status"],
            answer=state["answer"],
            citations=citations,
            retrieval_attempts=state.get("retrieval_attempts", 0),
        )

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
        return LangChainTracer(project_name=self.config.langsmith_project, client=client)

    def _build_graph(self):
        """Compile the routing branches and bounded retrieval-refinement loop."""

        # TypedDict is valid graph state, but ty does not yet accept it on Python 3.14.
        graph = StateGraph(WorkflowState)  # ty: ignore[invalid-argument-type]
        graph.add_node("analyze_question", self._analyze_question)
        graph.add_node("return_out_of_domain", self._return_out_of_domain)
        graph.add_node("ask_specific_details", self._ask_specific_details)
        graph.add_node("retrieve_context", self._retrieve_context)
        graph.add_node("assess_context", self._assess_context)
        graph.add_node("formulate_answer", self._formulate_answer)

        graph.add_edge(START, "analyze_question")
        graph.add_conditional_edges(
            "analyze_question",
            self._route_question,
            {
                "out_of_domain": "return_out_of_domain",
                "needs_clarification": "ask_specific_details",
                "retrieve": "retrieve_context",
            },
        )
        graph.add_edge("return_out_of_domain", END)
        graph.add_edge("ask_specific_details", END)
        graph.add_edge("retrieve_context", "assess_context")
        graph.add_conditional_edges(
            "assess_context",
            self._route_after_assessment,
            {"retrieve": "retrieve_context", "answer": "formulate_answer"},
        )
        graph.add_edge("formulate_answer", END)
        return graph.compile()

    def _analyze_question(self, state: WorkflowState) -> dict[str, Any]:
        prompt = QUESTION_ANALYSIS_PROMPT.invoke({"question": state["question"]})
        analysis = self.model.with_structured_output(QuestionAnalysis).invoke(prompt)
        query = analysis.retrieval_query.strip() or state["question"]
        return {"analysis": analysis, "retrieval_query": query}

    @staticmethod
    def _route_question(state: WorkflowState) -> Literal["out_of_domain", "needs_clarification", "retrieve"]:
        analysis = state["analysis"]
        if analysis.out_of_domain:
            return "out_of_domain"
        if analysis.needs_clarification:
            return "needs_clarification"
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
        request = RetrievalRequest(
            query=state["retrieval_query"],
            required_facts=tuple(state["analysis"].required_facts),
            attempt=attempt,
        )
        chunks = self._invoke_retriever(request)
        return {
            "context": [*state.get("context", []), *chunks],
            "retrieval_attempts": attempt,
        }

    def _invoke_retriever(self, request: RetrievalRequest) -> list[RetrievedChunk]:
        if callable(self.retriever):
            retrieve = cast(Callable[[RetrievalRequest], Sequence[RetrievedChunk]], self.retriever)
            return list(retrieve(request))
        invoke = getattr(self.retriever, "invoke", None)
        if callable(invoke):
            return list(invoke(request))
        raise TypeError("retriever must be callable or provide invoke(request)")

    def _assess_context(self, state: WorkflowState) -> dict[str, Any]:
        analysis = state["analysis"]
        prompt = CONTEXT_ASSESSMENT_PROMPT.invoke(
            {
                "question": state["question"],
                "required_facts": format_bullets(analysis.required_facts),
                "current_query": state["retrieval_query"],
                "context": format_evidence(state.get("context", [])),
            }
        )
        assessment = self.model.with_structured_output(ContextAssessment).invoke(prompt)
        query = (assessment.refined_query or "").strip() or state["retrieval_query"]
        return {"context_is_sufficient": assessment.is_sufficient, "retrieval_query": query}

    def _route_after_assessment(self, state: WorkflowState) -> Literal["retrieve", "answer"]:
        if state["context_is_sufficient"] or state["retrieval_attempts"] >= self.max_retrieval_attempts:
            return "answer"
        return "retrieve"

    def _formulate_answer(self, state: WorkflowState) -> dict[str, Any]:
        prompt = ANSWER_PROMPT.invoke(
            {
                "question": state["question"],
                "required_facts": format_bullets(state["analysis"].required_facts),
                "context": format_evidence(state.get("context", [])),
                "context_is_sufficient": state["context_is_sufficient"],
            }
        )
        response = self.model.invoke(prompt)
        answer = response.text if isinstance(response, BaseMessage) else response
        return {"status": "answered", "answer": answer}
