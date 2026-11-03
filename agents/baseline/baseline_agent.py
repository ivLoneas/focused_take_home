"""Baseline LangGraph workflow for financial-report questions."""

import json
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph

from agents.baseline.models import (
    BaselineResult,
    ContextAssessment,
    QuestionAnalysis,
    WorkflowState,
)
from agents.baseline.prompts import ANSWER_PROMPT, CONTEXT_ASSESSMENT_PROMPT, QUESTION_ANALYSIS_PROMPT
from agents.models import ChatModel
from agents.tools.models import RetrievalRequest, RetrievedChunk
from agents.workflow import FinancialReportAgent
from utils import format_bullets, format_evidence, require_nonblank_string

__all__ = ["BaselineAgent", "BaselineResult", "ChatModel", "RetrievalRequest", "RetrievedChunk"]


class BaselineAgent(FinancialReportAgent):
    """Route a question, refine retrieval to its limit, then answer from accumulated evidence."""

    def invoke(self, question: str) -> BaselineResult:
        """Run one stateless question and return deduplicated evidence labels as citations."""

        question = require_nonblank_string(question, field_name="question")

        config: dict[str, Any] = {
            "recursion_limit": 2 * self.max_retrieval_attempts + 10,
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
            tool_calls=tuple(state.get("tool_calls", [])),
        )

    def _build_graph(self):
        """Compile the routing branches and bounded retrieval-refinement loop."""

        # TypedDict is valid graph state, but ty does not yet accept it on Python 3.14.
        graph = StateGraph(WorkflowState)  # ty: ignore[invalid-argument-type]
        graph.add_node("analyze_question", self._analyze_question)
        graph.add_node("check_available_data", self._check_available_data)
        graph.add_node("return_out_of_domain", self._return_out_of_domain)
        graph.add_node("ask_specific_details", self._ask_specific_details)
        graph.add_node("retrieve_context", self._retrieve_context)
        graph.add_node("assess_context", self._assess_context)
        graph.add_node("formulate_answer", self._formulate_answer)

        graph.add_edge(START, "analyze_question")
        routes = {
            "out_of_domain": "return_out_of_domain",
            "answer": "formulate_answer",
            "needs_clarification": "ask_specific_details",
            "retrieve": "retrieve_context",
        }
        graph.add_conditional_edges(
            "analyze_question",
            lambda state: (
                "discover" if self.coverage is not None and not state["analysis"].out_of_domain
                else self._route_question(state)
            ),
            {**routes, "discover": "check_available_data"},
        )
        graph.add_conditional_edges(
            "check_available_data",
            self._route_question,
            routes,
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

    def _check_available_data(self, state: WorkflowState) -> dict[str, Any]:
        analysis = state["analysis"]
        companies = self.coverage.listed_companies.invoke({})
        calls = [{"name": "listed_companies", "arguments": {}}]
        by_name = {company.casefold(): company for company in companies}
        selected = companies if analysis.coverage_requested and not analysis.companies else analysis.companies
        periods = {}
        for requested in selected:
            company = by_name.get(requested.casefold())
            if company is None or company in periods:
                continue
            arguments = {"company": company}
            periods[company] = self.coverage.company_periods.invoke(arguments)
            calls.append({"name": "company_periods", "arguments": arguments})
        available_data = {"companies": companies, "periods": periods}
        prompt = QUESTION_ANALYSIS_PROMPT.invoke({
            "question": state["question"],
            "available_data": json.dumps(available_data, ensure_ascii=False),
            "analysis_stage": "Decide the final route using the completed discovery tool results below.",
        })
        verified = self.model.with_structured_output(QuestionAnalysis).invoke(prompt)
        if self._route_question({"analysis": verified, "available_data": available_data}) == "retrieve":
            for company in verified.companies:
                if company not in periods:
                    raise ValueError(f"Company {company!r} has no verified company_periods result")
        return {
            "analysis": verified,
            "retrieval_query": verified.retrieval_query.strip() or state["question"],
            "available_data": available_data,
            "tool_calls": calls,
        }

    def _assess_context(self, state: WorkflowState) -> dict[str, Any]:
        analysis = state["analysis"]
        prompt = CONTEXT_ASSESSMENT_PROMPT.invoke(
            {
                "question": state["question"],
                "required_facts": format_bullets(analysis.required_facts),
                "current_query": state["retrieval_query"],
                "context": format_evidence(state.get("context", [])),
                "available_data": json.dumps(state.get("available_data", {}), ensure_ascii=False),
            }
        )
        assessment = self.model.with_structured_output(ContextAssessment).invoke(prompt)
        query = (assessment.refined_query or "").strip() or state["retrieval_query"]
        return {"context_is_sufficient": assessment.is_sufficient, "retrieval_query": query}

    def _formulate_answer(self, state: WorkflowState) -> dict[str, Any]:
        prompt = ANSWER_PROMPT.invoke(
            {
                "question": state["question"],
                "required_facts": format_bullets(state["analysis"].required_facts),
                "context": format_evidence(state.get("context", [])),
                "context_is_sufficient": state.get("context_is_sufficient", False),
                "available_data": json.dumps(state.get("available_data", {}), ensure_ascii=False),
            }
        )
        response = self.model.invoke(prompt)
        answer = response.text if isinstance(response, BaseMessage) else response
        return {"status": "answered", "answer": answer}
