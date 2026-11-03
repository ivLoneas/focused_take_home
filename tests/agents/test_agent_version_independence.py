"""Agent versions share contracts without depending on the v1 implementation."""

from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from agents.agent_v2 import AgentV2, AgentV2Config
from agents.baseline import BaselineAgent, BaselineResult
from agents.tools.models import RetrievedChunk


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(lambda _: schema.model_validate(next(self.responses)))

    def invoke(self, value, **kwargs):
        return AIMessage(content=next(self.responses))


@pytest.fixture
def isolated_v2(monkeypatch):
    def fail_v1(*args, **kwargs):
        raise AssertionError("AgentV2 called the v1 implementation")

    # A change to v1 initialization or policy must never change v2 execution.
    for name in (
        "__init__", "invoke", "_build_tracer", "_build_graph", "_route_question",
        "_return_out_of_domain", "_ask_specific_details", "_retrieve_context",
        "_route_after_assessment", "_analyze_question", "_check_available_data",
        "_assess_context", "_formulate_answer",
    ):
        monkeypatch.setattr(BaselineAgent, name, fail_v1, raising=False)

    def build(*, plans=(), answers=(), allowed=True, retriever=None, **kwargs):
        gate = Mock(invoke=Mock(return_value=allowed))
        agent = AgentV2(
            ScriptedModel(answers), routing_model=ScriptedModel(plans), domain_gate=gate,
            retriever=retriever if retriever is not None else Mock(return_value=[]),
            config=AgentV2Config(_env_file=None, langsmith_tracing=False), **kwargs,
        )
        return agent, gate

    return build


def test_v2_is_not_a_specialization_of_v1():
    assert not issubclass(AgentV2, BaselineAgent)


@pytest.mark.parametrize("attempts", [1, 2])
def test_v2_retrieves_and_answers_independently_of_v1(isolated_v2, attempts):
    evidence = RetrievedChunk("Apple revenue was 10.", "Apple FY2025 p. 1")
    retriever = Mock(return_value=[evidence])
    plans = [{"needs_clarification": False, "companies": ["Apple"], "required_facts": ["revenue"]}]
    plans += [{"is_sufficient": False, "refined_query": "Apple annual revenue"}] * (attempts - 1)
    agent, gate = isolated_v2(
        plans=plans, answers=["10"], retriever=retriever, max_retrieval_attempts=attempts,
    )

    result = agent.invoke("Apple FY2025 revenue?")

    assert isinstance(result, BaselineResult)
    assert result.status == "answered" and result.answer == "10"
    assert result.citations == (evidence.source,) and result.retrieval_attempts == attempts
    assert [call.args[0].attempt for call in retriever.call_args_list] == list(range(1, attempts + 1))
    gate.invoke.assert_called_once_with("Apple FY2025 revenue?")


def test_v2_domain_refusal_is_independent_of_v1(isolated_v2):
    agent, _ = isolated_v2(allowed=False)

    result = agent.invoke("Write a cake recipe")

    assert result.status == "out_of_domain"
    assert result.retrieval_attempts == 0 and result.citations == ()


def test_v2_clarification_is_independent_of_v1(isolated_v2):
    agent, _ = isolated_v2(plans=[{
        "needs_clarification": True, "clarification_question": "Which company do you mean?",
    }])

    result = agent.invoke("How much did it earn in 2025?")

    assert result.status == "needs_clarification" and result.answer == "Which company do you mean?"
    assert result.retrieval_attempts == 0


@pytest.mark.parametrize("question,error", [("", ValueError), (" \n", ValueError), (None, TypeError)])
def test_v2_validates_questions_without_v1(isolated_v2, question, error):
    agent, gate = isolated_v2()

    with pytest.raises(error, match="question"):
        agent.invoke(question)

    gate.invoke.assert_not_called()


@pytest.mark.parametrize("limit,error", [(0, ValueError), (-1, ValueError), (True, TypeError), (1.5, TypeError)])
def test_v2_validates_retry_limits_without_v1(isolated_v2, limit, error):
    with pytest.raises(error, match="max_retrieval_attempts"):
        isolated_v2(max_retrieval_attempts=limit)


def test_v2_propagates_retrieval_errors_without_v1(isolated_v2):
    failure = RuntimeError("retrieval unavailable")
    agent, _ = isolated_v2(
        plans=[{"needs_clarification": False, "companies": ["Apple"]}],
        retriever=Mock(side_effect=failure),
    )

    with pytest.raises(RuntimeError, match="retrieval unavailable") as raised:
        agent.invoke("Apple FY2025 revenue?")

    assert raised.value is failure
