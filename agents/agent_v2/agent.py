"""Jev scope screening with cheaper planning and evidence-bound final answers."""

import json
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph

from agents.agent_v2.models import QuestionPlan
from agents.agent_v2.prompts import ANSWER_PROMPT, CONTEXT_ASSESSMENT_PROMPT, QUESTION_ANALYSIS_PROMPT
from agents.agent_v2.settings import AgentV2Config
from agents.baseline.baseline_agent import BaselineAgent, ChatModel
from agents.baseline.models import BaselineResult, ContextAssessment, QuestionAnalysis, WorkflowState
from agents.tools import DatabaseCoverage, placeholder_retriever
from agents.tools.models import Retriever
from utils import format_bullets, format_evidence, require_nonblank_string


class AgentV2(BaselineAgent):
    """Reuse the baseline's retrieval contracts and tracer, preserving its standalone workflow."""

    def __init__(
        self,
        answer_model: ChatModel,
        *,
        routing_model: ChatModel,
        domain_gate: Any,
        retriever: Retriever = placeholder_retriever,
        coverage: DatabaseCoverage | None = None,
        max_retrieval_attempts: int = 3,
        config: AgentV2Config | None = None,
    ) -> None:
        self.routing_model = routing_model
        self.domain_gate = domain_gate
        super().__init__(
            answer_model, retriever=retriever, coverage=coverage,
            max_retrieval_attempts=max_retrieval_attempts, config=config or AgentV2Config(),
        )

    def invoke(self, question: str) -> BaselineResult:
        question = require_nonblank_string(question, field_name="question")
        config: dict[str, Any] = {
            "recursion_limit": 2 * self.max_retrieval_attempts + 12,
            "run_name": "agent-v2",
            "tags": ["agent-v2", "financial-report-rag"],
            "metadata": {
                "component": "agent-v2", "model": self.config.model,
                "routing_model": self.config.routing_model, "typesafe_model": self.config.typesafe_model,
                "max_retrieval_attempts": self.max_retrieval_attempts,
            },
        }
        if self.tracer is not None:
            config["callbacks"] = [self.tracer]
        state = self.graph.invoke({"question": question, "context": [], "retrieval_attempts": 0}, config)
        return BaselineResult(
            status=state["status"], answer=state["answer"],
            citations=tuple(dict.fromkeys(chunk.source for chunk in state.get("context", []))),
            retrieval_attempts=state.get("retrieval_attempts", 0), tool_calls=tuple(state.get("tool_calls", [])),
        )

    def _build_graph(self):
        graph = StateGraph(WorkflowState)  # ty: ignore[invalid-argument-type]
        graph.add_node("screen_domain", self._screen_domain)
        for name in (
            "analyze_question", "check_available_data", "return_out_of_domain", "ask_specific_details",
            "retrieve_context", "assess_context", "formulate_answer",
        ):
            graph.add_node(name, getattr(self, f"_{name}"))
        graph.add_edge(START, "screen_domain")
        graph.add_conditional_edges("screen_domain", lambda state: self._route_question(state), {
            "out_of_domain": "return_out_of_domain", "retrieve": "check_available_data",
        })
        routes = {
            "needs_clarification": "ask_specific_details", "answer": "formulate_answer",
            "retrieve": "retrieve_context",
        }
        graph.add_edge("check_available_data", "analyze_question")
        graph.add_conditional_edges("analyze_question", self._route_question, routes)
        graph.add_conditional_edges("retrieve_context", lambda state: (
            "answer" if state["retrieval_attempts"] >= self.max_retrieval_attempts else "assess"
        ), {"answer": "formulate_answer", "assess": "assess_context"})
        graph.add_conditional_edges("assess_context", self._route_after_assessment, {
            "retrieve": "retrieve_context", "answer": "formulate_answer",
        })
        for name in ("return_out_of_domain", "ask_specific_details", "formulate_answer"):
            graph.add_edge(name, END)
        return graph.compile()

    def _screen_domain(self, state: WorkflowState) -> dict[str, Any]:
        allowed = self.domain_gate.invoke(state["question"])
        if not isinstance(allowed, bool):
            raise TypeError("domain_gate must return a boolean")
        return {"analysis": QuestionAnalysis(out_of_domain=not allowed, needs_clarification=False)}

    def _analyze_question(self, state: WorkflowState) -> dict[str, Any]:
        values = {
            "question": state["question"],
            "analysis_stage": "Select the final route using completed discovery results.",
            "available_data": json.dumps(state.get("available_data", {}), ensure_ascii=False),
        }
        prompt = QUESTION_ANALYSIS_PROMPT.invoke(values)
        analysis = self.routing_model.with_structured_output(QuestionPlan).invoke(prompt)
        analysis = analysis.model_copy(update={"out_of_domain": False})
        if self.coverage is not None and self._route_question({**state, "analysis": analysis}) == "retrieve":
            for company in analysis.companies:
                if company not in state["available_data"]["periods"]:
                    raise ValueError(f"Company {company!r} has no verified company_periods result")
        return {"analysis": analysis, "retrieval_query": analysis.retrieval_query.strip() or state["question"]}

    def _check_available_data(self, state: WorkflowState) -> dict[str, Any]:
        if self.coverage is None:
            return {}
        companies = self.coverage.listed_companies.invoke({})
        calls = [{"name": "listed_companies", "arguments": {}}]
        periods = {}
        for company in companies:
            if company in periods:
                continue
            arguments = {"company": company}
            periods[company] = self.coverage.company_periods.invoke(arguments)
            calls.append({"name": "company_periods", "arguments": arguments})
        return {
            "available_data": {"companies": companies, "periods": periods}, "tool_calls": calls,
        }

    def _retrieve_context(self, state: WorkflowState) -> dict[str, Any]:
        update = super()._retrieve_context(state)
        unique = []
        for chunk in update["context"]:
            if chunk not in unique:
                unique.append(chunk)
        return {**update, "context": unique, "context_is_sufficient": False}

    def _assess_context(self, state: WorkflowState) -> dict[str, Any]:
        prompt = CONTEXT_ASSESSMENT_PROMPT.invoke({
            "question": state["question"], "required_facts": format_bullets(state["analysis"].required_facts),
            "current_query": state["retrieval_query"], "context": format_evidence(state.get("context", [])),
            "available_data": json.dumps(state.get("available_data", {}), ensure_ascii=False),
        })
        assessment = self.routing_model.with_structured_output(ContextAssessment).invoke(prompt)
        return {
            "context_is_sufficient": assessment.is_sufficient,
            "retrieval_query": (assessment.refined_query or "").strip() or state["retrieval_query"],
        }

    def _formulate_answer(self, state: WorkflowState) -> dict[str, Any]:
        prompt = ANSWER_PROMPT.invoke({
            "question": state["question"], "required_facts": format_bullets(state["analysis"].required_facts),
            "context": format_evidence(state.get("context", [])),
            "context_is_sufficient": state.get("context_is_sufficient", False),
            "available_data": json.dumps(state.get("available_data", {}), ensure_ascii=False),
        })
        response = self.model.invoke(prompt)
        return {"status": "answered", "answer": response.text if isinstance(response, BaseMessage) else response}
