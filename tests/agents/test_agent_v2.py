"""Independent behavioral contract for the optimized financial-report workflow."""

from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool

from agents.agent_v2.agent import AgentV2
from agents.agent_v2.settings import AgentV2Config
from agents.baseline.models import BaselineResult
from agents.tools.models import RetrievedChunk


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch):
    for key in (
        "AGENT_MODEL", "AGENT_V2_ROUTING_MODEL", "TYPESAFE_MODEL", "TYPESAFE_API_KEY",
        "TYPESAFE_TIMEOUT_SECONDS", "LANGSMITH_TRACING", "LANGSMITH_API_KEY",
        "LANGSMITH_AGENT_ID", "LANGSMITH_AGENT_ENVIRONMENT",
    ):
        monkeypatch.delenv(key, raising=False)


def plan(**changes):
    result = {
        "out_of_domain": False, "needs_clarification": False, "clarification_question": None,
        "required_facts": ["Apple FY2025 revenue"], "coverage_requested": False,
        "companies": ["Apple"], "retrieval_query": "Apple FY2025 revenue annual report",
    }
    result.update(changes)
    return result


class Model:
    def __init__(self, plans=(), assessments=(), answers=()):
        self.responses = {"plan": list(plans), "assessment": list(assessments), "answer": list(answers)}
        self.prompts = defaultdict(list)

    def take(self, kind, value):
        self.prompts[kind].append(value.to_string())
        response = self.responses[kind].pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def with_structured_output(self, schema, **kwargs):
        kind = "assessment" if "is_sufficient" in schema.model_fields else "plan"
        return RunnableLambda(lambda value: schema.model_validate(self.take(kind, value)))

    def invoke(self, value, **kwargs):
        return AIMessage(content=self.take("answer", value))


class Gate:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.questions = []

    def invoke(self, question, **kwargs):
        self.questions.append(question)
        if isinstance(self.allowed, Exception):
            raise self.allowed
        return self.allowed


def coverage(companies=("Apple",), periods=None):
    calls = []
    periods = periods or {company: {"company": company, "intervals": ["Q1FY2025-Q4FY2025"],
                                    "annual_reports": ["FY2025"]} for company in companies}

    def listed():
        calls.append(("listed_companies", {}))
        return list(companies)

    def company_periods(company: str):
        calls.append(("company_periods", {"company": company}))
        return periods[company]

    return SimpleNamespace(
        listed_companies=StructuredTool.from_function(listed, name="listed_companies", description="List companies"),
        company_periods=StructuredTool.from_function(company_periods, description="List periods"),
    ), calls


def make_agent(*, plans=(), assessments=(), answers=(), gate=None, retriever=None, **kwargs):
    routing = Model(plans=plans, assessments=assessments)
    answering = Model(answers=answers)
    gate = gate or Gate()
    retriever = retriever if retriever is not None else Mock(return_value=[])
    agent = AgentV2(
        answering, routing_model=routing, domain_gate=gate, retriever=retriever,
        config=AgentV2Config(_env_file=None), **kwargs,
    )
    return agent, routing, answering, gate, retriever


def test_jev_rejection_returns_without_any_openai_database_or_retrieval_call():
    database, calls = coverage()
    agent, routing, answering, gate, retriever = make_agent(gate=Gate(False), coverage=database)

    result = agent.invoke("Give me a cake recipe")

    assert isinstance(result, BaselineResult)
    assert result.status == "out_of_domain"
    assert "financial report" in result.answer.lower()
    assert result.citations == () and result.retrieval_attempts == 0 and result.tool_calls == ()
    assert gate.questions == ["Give me a cake recipe"]
    assert not routing.prompts and not answering.prompts and not calls
    retriever.assert_not_called()


@pytest.mark.parametrize("planning_options", [{}, {"planning_model": None}], ids=["omitted", "explicit-none"])
def test_routing_model_plans_and_assesses_while_answer_model_only_answers(planning_options):
    database, calls = coverage()
    evidence = RetrievedChunk("Revenue was $10 million.", "Apple FY2025 p. 1", {"page": 1})
    agent, routing, answering, _gate, retriever = make_agent(
        plans=[plan()], assessments=[{"is_sufficient": True}], answers=["10"],
        retriever=Mock(return_value=[evidence]), coverage=database, **planning_options,
    )

    result = agent.invoke("Apple FY2025 revenue in millions. Return only the number, no citations.")

    assert result.answer == "10"
    assert result.citations == (evidence.source,)
    assert result.retrieval_attempts == 1
    assert len(routing.prompts["plan"]) == 1 and len(routing.prompts["assessment"]) == 1
    assert not routing.prompts["answer"]
    assert len(answering.prompts["answer"]) == 1 and not answering.prompts["plan"]
    assert calls == [("listed_companies", {}), ("company_periods", {"company": "Apple"})]
    assert list(result.tool_calls) == [{"name": name, "arguments": args} for name, args in calls]
    assert retriever.call_args.args[0].company == "Apple"


def test_last_allowed_round_skips_separate_assessment_and_keeps_evidence_unverified():
    evidence = RetrievedChunk("Only a partial fact.", "Apple report p. 3")
    agent, routing, answering, _, _ = make_agent(
        plans=[plan()], answers=["The available report does not establish all requested facts."],
        retriever=Mock(return_value=[evidence]), max_retrieval_attempts=1,
    )

    result = agent.invoke("Apple FY2025 revenue?")

    assert result.retrieval_attempts == 1
    assert not routing.prompts["assessment"]
    prompt = answering.prompts["answer"][0].lower()
    assert evidence.text.lower() in prompt
    assert "false" in prompt


def test_refinement_accumulates_evidence_but_deduplicates_only_identical_chunks():
    first = RetrievedChunk("Revenue was 10.", "Report p. 1", {"page": 1})
    duplicate = RetrievedChunk(first.text, first.source, {"page": 1})
    changed_text = RetrievedChunk("Prior revenue was 9.", first.source, {"page": 1})
    changed_metadata = RetrievedChunk(first.text, first.source, {"page": 2})
    different_source = RetrievedChunk(first.text, "Other report p. 1", {"page": 1})
    retriever = Mock(side_effect=[[first], [duplicate, changed_text, changed_metadata, different_source]])
    agent, routing, answering, _, _ = make_agent(
        plans=[plan()], assessments=[{"is_sufficient": False, "refined_query": "Apple FY2025 revenue prior year"}],
        answers=["Partial answer"], retriever=retriever, max_retrieval_attempts=2,
    )

    result = agent.invoke("Compare Apple FY2025 revenue with FY2024")

    assert result.retrieval_attempts == 2
    assert [call.args[0].attempt for call in retriever.call_args_list] == [1, 2]
    assert retriever.call_args_list[1].args[0].query == "Apple FY2025 revenue prior year"
    assert len(routing.prompts["assessment"]) == 1
    prompt = answering.prompts["answer"][0]
    assert prompt.count("Revenue was 10.") == 3
    assert "Prior revenue was 9." in prompt
    assert result.citations == (first.source, different_source.source)


def test_coverage_only_request_discovers_every_company_without_report_search():
    database, calls = coverage(("Apple", "Meta"))
    listing = plan(companies=[], required_facts=[], retrieval_query="", coverage_requested=True)
    agent, routing, _, _, retriever = make_agent(
        plans=[listing], answers=["Apple and Meta, FY2025."], coverage=database,
    )

    result = agent.invoke("Which companies and periods are available?")

    assert result.status == "answered" and result.retrieval_attempts == 0 and not result.citations
    assert calls == [("listed_companies", {}), ("company_periods", {"company": "Apple"}),
                     ("company_periods", {"company": "Meta"})]
    assert not routing.prompts["assessment"]
    retriever.assert_not_called()


def test_unavailable_company_is_in_domain_and_answered_using_verified_coverage():
    database, calls = coverage()
    agent, _, _, _, retriever = make_agent(
        plans=[plan(companies=[], required_facts=["Walmart unavailable"])],
        answers=["Walmart reports are unavailable."], coverage=database,
    )

    result = agent.invoke("Walmart FY2025 revenue?")

    assert result.status == "answered" and result.retrieval_attempts == 0
    assert calls == [("listed_companies", {}), ("company_periods", {"company": "Apple"})]
    retriever.assert_not_called()


def test_mixed_coverage_searches_supported_company_and_preserves_gap_for_answer():
    database, _calls = coverage()
    agent, _, answering, _, retriever = make_agent(
        plans=[plan(required_facts=["Apple revenue", "Walmart unavailable"])],
        assessments=[{"is_sufficient": True}], answers=["Apple revenue is 10; Walmart is unavailable."],
        coverage=database, retriever=Mock(return_value=[RetrievedChunk("Revenue 10", "Apple p. 1")]),
    )

    result = agent.invoke("Compare Apple and Walmart FY2025 revenue")

    assert result.status == "answered"
    assert retriever.call_count == 1 and retriever.call_args.args[0].company == "Apple"
    assert "Walmart unavailable" in answering.prompts["answer"][0]


def test_multiple_company_requests_retrieve_each_verified_company_once():
    database, _ = coverage(("Apple", "Meta"))
    analysis = plan(companies=["Apple", "Meta", "Apple"])
    retriever = Mock(side_effect=[[RetrievedChunk("Apple 10", "Apple p. 1")],
                                 [RetrievedChunk("Meta 9", "Meta p. 2")]])
    agent, _, _, _, _ = make_agent(
        plans=[analysis], assessments=[{"is_sufficient": True}], answers=["Apple is larger."],
        coverage=database, retriever=retriever,
    )

    result = agent.invoke("Compare Apple and Meta FY2025 revenue")

    assert [call.args[0].company for call in retriever.call_args_list] == ["Apple", "Meta"]
    assert result.retrieval_attempts == 1 and result.citations == ("Apple p. 1", "Meta p. 2")


def test_unidentified_company_can_still_require_one_specific_clarification():
    database, calls = coverage(("Apple", "Meta"))
    agent, _routing, answering, _, retriever = make_agent(coverage=database, plans=[plan(
        companies=[], needs_clarification=True, clarification_question="Which company do you mean?",
    )])

    result = agent.invoke("How much did it earn in 2025?")

    assert result.status == "needs_clarification" and result.answer == "Which company do you mean?"
    assert calls == [("listed_companies", {}), ("company_periods", {"company": "Apple"}),
                     ("company_periods", {"company": "Meta"})]
    assert not answering.prompts
    retriever.assert_not_called()


@pytest.mark.parametrize("question,exception", [("", ValueError), (" \n", ValueError), (None, TypeError), (4, TypeError)])
def test_invalid_question_rejected_before_gate(question, exception):
    agent, _, _, gate, _ = make_agent()
    with pytest.raises(exception, match="question"):
        agent.invoke(question)
    assert not gate.questions


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "3"])
def test_invalid_retry_limit_rejected(limit):
    with pytest.raises((TypeError, ValueError), match="retrieval|attempt"):
        make_agent(max_retrieval_attempts=limit)


@pytest.mark.parametrize("stage", ["gate", "plan", "discovery", "retrieval", "assessment", "answer"])
def test_dependency_failures_propagate_without_becoming_refusals(stage):
    error = RuntimeError(f"{stage} unavailable")
    database, _ = coverage()
    options = {"plans": [plan()], "assessments": [{"is_sufficient": True}], "answers": ["10"],
               "coverage": database, "retriever": Mock(return_value=[RetrievedChunk("Revenue 10", "Apple p. 1")])}
    if stage == "gate":
        options["gate"] = Gate(error)
    elif stage == "plan":
        options["plans"] = [error]
    elif stage == "discovery":
        database.listed_companies = Mock(invoke=Mock(side_effect=error))
    elif stage == "retrieval":
        options["retriever"] = Mock(side_effect=error)
    elif stage == "assessment":
        options["assessments"] = [error]
    else:
        options["answers"] = [error]
    agent, _, _, _, _ = make_agent(**options)
    with pytest.raises(RuntimeError, match=f"{stage} unavailable") as raised:
        agent.invoke("Apple FY2025 revenue?")
    assert raised.value is error


def test_root_trace_contains_nested_planning_discovery_and_answer_without_secrets():
    class Events(BaseCallbackHandler):
        def __init__(self):
            self.parents = {}
            self.chains = []
            self.tools = []
            self.metadata = []

        def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
            self.parents[run_id] = parent_run_id
            self.chains.append((kwargs.get("name"), run_id, parent_run_id))
            self.metadata.append(kwargs.get("metadata"))

        def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
            self.parents[run_id] = parent_run_id
            self.tools.append((serialized["name"], run_id))

    database, _ = coverage()
    listing = plan(companies=[], required_facts=[], retrieval_query="", coverage_requested=True)
    agent, _, _, _, _ = make_agent(plans=[listing], answers=["Apple FY2025"], coverage=database)
    events = Events()
    agent.tracer = events

    agent.invoke("What reports are available?")

    root = next(run_id for _, run_id, parent in events.chains if parent is None)
    assert any("v2" in (name or "") for name, run_id, _ in events.chains if run_id == root)
    assert [name for name, _ in events.tools] == ["listed_companies", "company_periods"]
    for _, run_id in events.tools:
        ancestors = []
        parent = events.parents[run_id]
        while parent is not None:
            ancestors.append(parent)
            parent = events.parents[parent]
        assert root in ancestors
    assert "TYPESAFE_API_KEY" not in repr(events.metadata)


def test_every_company_period_is_verified_before_the_only_planning_call():
    database, calls = coverage(("Apple", "Meta", "Netflix"))
    expected_calls = [("listed_companies", {})] + [
        ("company_periods", {"company": company}) for company in ("Apple", "Meta", "Netflix")
    ]

    class VerifyDiscoveryModel(Model):
        def take(self, kind, value):
            if kind == "plan":
                assert calls == expected_calls
                prompt = value.to_string()
                assert all(company in prompt for company in ("Apple", "Meta", "Netflix"))
                assert "FY2025" in prompt
            return super().take(kind, value)

    routing = VerifyDiscoveryModel(plans=[plan(companies=["Apple", "Meta"])],
                                   assessments=[{"is_sufficient": True}])
    answering = Model(answers=["Apple 10; Meta 9."])
    retriever = Mock(side_effect=[[RetrievedChunk("Apple revenue 10", "Apple p. 1")],
                                 [RetrievedChunk("Meta revenue 9", "Meta p. 1")]])
    agent = AgentV2(answering, routing_model=routing, domain_gate=Gate(), retriever=retriever,
                    coverage=database, config=AgentV2Config(_env_file=None))

    result = agent.invoke("Compare Apple and Meta FY2025 revenue")

    assert result.status == "answered"
    assert len(routing.prompts["plan"]) == 1
    assert calls == expected_calls
    assert [call.args[0].company for call in retriever.call_args_list] == ["Apple", "Meta"]
    assert len(result.tool_calls) == 4


def test_single_supported_request_still_discovers_unselected_companies_before_planning():
    database, calls = coverage(("Apple", "Meta"))
    agent, routing, _, _, retriever = make_agent(
        plans=[plan()], assessments=[{"is_sufficient": True}], answers=["10"],
        retriever=Mock(return_value=[RetrievedChunk("Apple revenue 10", "Apple p. 1")]), coverage=database,
    )

    agent.invoke("Apple FY2025 revenue?")

    assert calls == [("listed_companies", {}), ("company_periods", {"company": "Apple"}),
                     ("company_periods", {"company": "Meta"})]
    assert len(routing.prompts["plan"]) == 1
    assert retriever.call_count == 1 and retriever.call_args.args[0].company == "Apple"


def test_period_discovery_error_prevents_planning_and_answering():
    database, _ = coverage(("Apple", "Meta"))
    failure = RuntimeError("period discovery unavailable")
    database.company_periods = Mock(invoke=Mock(side_effect=failure))
    agent, routing, answering, _, retriever = make_agent(coverage=database)

    with pytest.raises(RuntimeError, match="period discovery unavailable") as raised:
        agent.invoke("Apple FY2025 revenue?")

    assert raised.value is failure
    assert not routing.prompts and not answering.prompts
    retriever.assert_not_called()


def test_optional_planning_model_owns_only_planning_while_router_assesses_and_answerer_answers():
    database, calls = coverage(("Apple", "Meta"))
    gate = Gate()

    class PlanningModel(Model):
        def take(self, kind, value):
            assert gate.questions == ["Apple FY2025 revenue?"]
            assert calls == [("listed_companies", {}), ("company_periods", {"company": "Apple"}),
                             ("company_periods", {"company": "Meta"})]
            assert all(company in value.to_string() for company in ("Apple", "Meta"))
            assert "FY2025" in value.to_string()
            return super().take(kind, value)

    planning = PlanningModel(plans=[plan()])
    routing = Model(assessments=[{"is_sufficient": True}])
    answering = Model(answers=["Apple revenue was 10 [Apple p. 1]."])
    agent = AgentV2(
        answering, planning_model=planning, routing_model=routing, domain_gate=gate, coverage=database,
        retriever=Mock(return_value=[RetrievedChunk("Apple revenue 10", "Apple p. 1")]),
        config=AgentV2Config(_env_file=None),
    )

    result = agent.invoke("Apple FY2025 revenue?")

    assert result.status == "answered"
    assert len(planning.prompts["plan"]) == 1
    assert not planning.prompts["assessment"] and not planning.prompts["answer"]
    assert len(routing.prompts["assessment"]) == 1
    assert not routing.prompts["plan"] and not routing.prompts["answer"]
    assert len(answering.prompts["answer"]) == 1
    assert not answering.prompts["plan"] and not answering.prompts["assessment"]


def test_optional_planning_model_is_not_called_when_jev_rejects_question():
    planning, routing, answering = Model(), Model(), Model()
    database, calls = coverage()
    retriever = Mock()
    agent = AgentV2(
        answering, planning_model=planning, routing_model=routing, domain_gate=Gate(False), coverage=database,
        retriever=retriever, config=AgentV2Config(_env_file=None),
    )

    result = agent.invoke("Give me a cake recipe")

    assert result.status == "out_of_domain"
    assert not planning.prompts and not routing.prompts and not answering.prompts
    assert not calls
    retriever.assert_not_called()


def test_optional_planning_model_errors_propagate_without_assessment_or_answer():
    failure = RuntimeError("planning model unavailable")
    planning, routing, answering = Model(plans=[failure]), Model(), Model()
    database, _ = coverage()
    retriever = Mock()
    agent = AgentV2(
        answering, planning_model=planning, routing_model=routing, domain_gate=Gate(), coverage=database,
        retriever=retriever, config=AgentV2Config(_env_file=None),
    )

    with pytest.raises(RuntimeError, match="planning model unavailable") as raised:
        agent.invoke("Apple FY2025 revenue?")

    assert raised.value is failure
    assert len(planning.prompts["plan"]) == 1
    assert not routing.prompts and not answering.prompts
    retriever.assert_not_called()
