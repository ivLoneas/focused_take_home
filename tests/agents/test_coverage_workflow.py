"""Scope decisions must use actual discovery tool results before retrieval."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool

from agents.baseline import BaselineAgent
from agents.baseline.models import BaselineResult, QuestionAnalysis
from agents.settings import AgentConfig
from agents.tools.models import RetrievedChunk


class ScopeModel:
    def __init__(self, analyses, *, answer="Supported answer [Apple p. 1]."):
        self.analyses = iter(analyses)
        self.analysis_prompts = []
        self.assessment_prompts = []
        self.answer_prompts = []
        self.answer = answer

    def with_structured_output(self, schema, **kwargs):
        def invoke(prompt):
            if schema is QuestionAnalysis:
                self.analysis_prompts.append(prompt.to_messages())
                return schema.model_validate(next(self.analyses))
            self.assessment_prompts.append(prompt.to_string())
            return schema.model_validate({"is_sufficient": True})
        return RunnableLambda(invoke)

    def invoke(self, prompt, **kwargs):
        self.answer_prompts.append(prompt.to_string())
        return AIMessage(content=self.answer)


def plan(**values):
    return {"out_of_domain": False, "needs_clarification": False, "companies": ["Apple"], **values}


def discovery(companies=("Apple",), periods=None):
    calls = []

    def listed_companies():
        calls.append(("listed_companies", {}))
        return list(companies)

    def company_periods(company: str):
        calls.append(("company_periods", {"company": company}))
        return {"company": company, "intervals": ["Q3FY2025-Q2FY2026"], "annual_reports": ["FY2025"]}

    return SimpleNamespace(
        listed_companies=StructuredTool.from_function(listed_companies, description="List database companies"),
        company_periods=StructuredTool.from_function(company_periods, description="List company periods"),
    ), calls


def test_question_analysis_accepts_unknown_company_names_for_discovery_without_pinned_enum():
    result = QuestionAnalysis.model_validate(plan(companies=["Tesla", "Future Issuer"]))
    assert result.companies == ["Tesla", "Future Issuer"]
    assert result.coverage_requested is False
    assert "enum" not in str(QuestionAnalysis.model_json_schema()["properties"]["companies"])


@pytest.mark.parametrize("selected_companies", [[], ["Apple", "Tesla"]])
def test_scope_listing_checks_all_current_companies_and_periods_before_answering(selected_companies):
    coverage, calls = discovery(companies=("Apple", "Tesla"))
    response = "Apple and Tesla: Q3FY2025-Q2FY2026."
    model = ScopeModel([
        plan(companies=[], coverage_requested=True),
        plan(companies=selected_companies, coverage_requested=True),
    ], answer=response)
    retriever = Mock()

    result = BaselineAgent(model, coverage=coverage, retriever=retriever, config=AgentConfig(langsmith_tracing=False)).invoke(
        "Which companies and periods do you have?"
    )

    assert result.answer == response
    assert result.retrieval_attempts == 0
    assert result.citations == ()
    assert calls == [
        ("listed_companies", {}), ("company_periods", {"company": "Apple"}),
        ("company_periods", {"company": "Tesla"}),
    ]
    assert list(result.tool_calls) == [{"name": name, "arguments": arguments} for name, arguments in calls]
    second_human = "\n".join(str(message.content) for message in model.analysis_prompts[1] if message.type == "human")
    assert "Tesla" in second_human and "Q3FY2025-Q2FY2026" in second_human
    assert "FY2025" in second_human
    retriever.assert_not_called()
    assert len(model.answer_prompts) == 1
    assert "Tesla" in model.answer_prompts[0] and "Q3FY2025-Q2FY2026" in model.answer_prompts[0]
    assert model.assessment_prompts == []


def test_financial_request_checks_selected_periods_and_passes_coverage_to_final_answer():
    coverage, calls = discovery(companies=("Apple", "Tesla"))
    model = ScopeModel([plan(companies=["Apple", "Apple"]), plan(required_facts=["FY2025 net sales"])])
    retriever = Mock(return_value=[RetrievedChunk(text="Net sales were $10.", source="Apple p. 1")])

    result = BaselineAgent(model, coverage=coverage, retriever=retriever, config=AgentConfig(langsmith_tracing=False)).invoke(
        "What were Apple's FY2025 net sales?"
    )

    assert calls == [("listed_companies", {}), ("company_periods", {"company": "Apple"})]
    assert retriever.call_count == 1
    assert result.retrieval_attempts == 1
    assert "Q3FY2025-Q2FY2026" in model.answer_prompts[0]


def test_absent_company_is_checked_against_database_before_coverage_gap_answer():
    coverage, calls = discovery()
    model = ScopeModel([
        plan(companies=["Walmart"]),
        plan(companies=[], required_facts=["Walmart FY2025 revenue"]),
    ], answer="Walmart has no reports in this database.")
    retriever = Mock()

    result = BaselineAgent(model, coverage=coverage, retriever=retriever, config=AgentConfig(langsmith_tracing=False)).invoke(
        "What was Walmart's FY2025 revenue?"
    )

    assert "Walmart" in result.answer
    assert calls == [("listed_companies", {})]
    retriever.assert_not_called()
    assert result.status == "answered"
    assert result.retrieval_attempts == 0
    assert result.citations == ()
    assert len(model.answer_prompts) == 1
    assert '"companies": ["Apple"]' in model.answer_prompts[0]
    assert model.assessment_prompts == []


def test_empty_database_coverage_listing_reaches_answer_without_retrieval():
    coverage, calls = discovery(companies=())
    model = ScopeModel([
        plan(companies=[], coverage_requested=True),
        plan(companies=[], coverage_requested=True),
    ], answer="No company reports are currently available.")
    retriever = Mock()

    result = BaselineAgent(model, coverage=coverage, retriever=retriever, config=AgentConfig(langsmith_tracing=False)).invoke(
        "Which companies do you cover?"
    )

    assert result.answer == "No company reports are currently available."
    assert result.retrieval_attempts == 0
    assert result.citations == ()
    assert calls == [("listed_companies", {})]
    assert '"companies": []' in model.answer_prompts[0]
    assert model.assessment_prompts == []
    retriever.assert_not_called()


def test_unsupported_period_uses_verified_period_results_in_answer_without_retrieval():
    coverage, calls = discovery()
    model = ScopeModel([
        plan(required_facts=["Apple FY2030 revenue"]),
        plan(companies=[], required_facts=["Apple FY2030 revenue is outside verified coverage"]),
    ], answer="Apple FY2030 is outside the available periods.")
    retriever = Mock()

    result = BaselineAgent(model, coverage=coverage, retriever=retriever, config=AgentConfig(langsmith_tracing=False)).invoke(
        "What was Apple's FY2030 revenue?"
    )

    assert result.answer == "Apple FY2030 is outside the available periods."
    assert calls == [("listed_companies", {}), ("company_periods", {"company": "Apple"})]
    assert result.retrieval_attempts == 0
    assert result.citations == ()
    assert "Q3FY2025-Q2FY2026" in model.answer_prompts[0]
    assert model.assessment_prompts == []
    retriever.assert_not_called()


def test_mixed_coverage_and_factual_request_still_retrieves_financial_evidence():
    coverage, _ = discovery()
    model = ScopeModel([
        plan(coverage_requested=True, required_facts=["FY2025 net sales"]),
        plan(coverage_requested=True, required_facts=["FY2025 net sales"]),
    ])
    retriever = Mock(return_value=[RetrievedChunk(text="Net sales were $10.", source="Apple p. 1")])

    result = BaselineAgent(model, coverage=coverage, retriever=retriever, config=AgentConfig(langsmith_tracing=False)).invoke(
        "Which periods are available for Apple, and what were its FY2025 net sales?"
    )

    assert retriever.call_count == 1
    assert result.retrieval_attempts == 1
    assert result.citations == ("Apple p. 1",)
    assert len(model.assessment_prompts) == 1
    assert "Net sales were $10." in model.answer_prompts[0]


def test_coverage_answer_generation_errors_propagate():
    coverage, _ = discovery()
    model = ScopeModel([
        plan(companies=[], coverage_requested=True),
        plan(companies=[], coverage_requested=True),
    ])
    error = RuntimeError("answer model unavailable")
    model.invoke = Mock(side_effect=error)
    retriever = Mock()

    with pytest.raises(RuntimeError, match="answer model unavailable") as raised:
        BaselineAgent(model, coverage=coverage, retriever=retriever, config=AgentConfig(langsmith_tracing=False)).invoke(
            "Which companies and periods are available?"
        )

    assert raised.value is error
    assert model.assessment_prompts == []
    retriever.assert_not_called()


def test_unrelated_request_skips_database_discovery():
    coverage, calls = discovery()
    model = ScopeModel([plan(out_of_domain=True, companies=[])])
    result = BaselineAgent(model, coverage=coverage, config=AgentConfig(langsmith_tracing=False)).invoke("Give me a recipe")
    assert result.status == "out_of_domain"
    assert calls == []
    assert result.tool_calls == ()


def test_discovery_failure_propagates_instead_of_using_remembered_coverage():
    coverage, _ = discovery()
    error = RuntimeError("coverage database unavailable")
    coverage.listed_companies = StructuredTool.from_function(
        lambda: (_ for _ in ()).throw(error), name="listed_companies", description="List companies",
    )
    model = ScopeModel([plan()])
    retriever = Mock()

    with pytest.raises(RuntimeError, match="coverage database unavailable") as raised:
        BaselineAgent(model, coverage=coverage, retriever=retriever, config=AgentConfig(langsmith_tracing=False)).invoke(
            "What were Apple's FY2025 net sales?"
        )
    assert raised.value is error
    retriever.assert_not_called()
    assert len(model.analysis_prompts) == 1


def test_baseline_result_default_trajectory_is_empty_for_existing_callers():
    result = BaselineResult(status="answered", answer="Answer", citations=(), retrieval_attempts=0)
    assert result.tool_calls == ()


def test_discovery_tools_are_nested_under_the_complete_agent_invocation_trace():
    class Events(BaseCallbackHandler):
        def __init__(self):
            self.parents = {}
            self.root = None
            self.tools = []

        def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
            self.parents[run_id] = parent_run_id
            if kwargs.get("name") == "baseline-agent":
                self.root = run_id

        def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
            self.parents[run_id] = parent_run_id
            self.tools.append((serialized["name"], run_id))

    coverage, _ = discovery()
    model = ScopeModel([
        plan(companies=[], coverage_requested=True),
        plan(companies=[], coverage_requested=True),
    ])
    agent = BaselineAgent(model, coverage=coverage, config=AgentConfig(langsmith_tracing=False))
    events = Events()
    agent.tracer = events

    agent.invoke("Which companies and periods are available?")

    assert events.root is not None
    assert [name for name, _ in events.tools] == ["listed_companies", "company_periods"]
    for _, run_id in events.tools:
        ancestors = []
        parent = events.parents[run_id]
        while parent is not None:
            ancestors.append(parent)
            parent = events.parents[parent]
        assert events.root in ancestors
