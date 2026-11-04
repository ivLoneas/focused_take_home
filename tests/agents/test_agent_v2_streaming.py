"""Independent acceptance contract for v2's optional answer stream."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from agents.agent_v2 import AgentV2, AgentV2Config
from agents.models import AgentResult
from agents.tools.models import RetrievedChunk


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    for name in ("AGENT_V2_STREAMING", "LANGSMITH_TRACING", "LANGSMITH_AGENT_ID", "LANGSMITH_AGENT_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)


def make_agent(*, streaming=True, allowed=True, clarification=False, answer_model=None):
    plan = {
        "needs_clarification": clarification, "clarification_question": "Which company?",
        "required_facts": ["revenue"], "companies": ["Apple"], "retrieval_query": "revenue",
    }
    planner = SimpleNamespace(with_structured_output=lambda schema: RunnableLambda(lambda _: schema(**plan)))
    gate = Mock(invoke=Mock(return_value=allowed))
    model = answer_model or Mock(invoke=Mock(return_value=AIMessage(content="Revenue £10.")))
    if answer_model is None:
        model.stream.return_value = iter([
            AIMessageChunk(content=""), AIMessageChunk(content="Revenue "),
            AIMessageChunk(content=[{"type": "reasoning", "reasoning": "private planning"}]),
            AIMessageChunk(content="£10."),
        ])
    retriever = Mock(return_value=[RetrievedChunk("Revenue 10", "Report p. 1"),
                                 RetrievedChunk("Revenue 10", "Report p. 1")])
    agent = AgentV2(
        model, routing_model=planner, domain_gate=gate, retriever=retriever,
        max_retrieval_attempts=1, config=AgentV2Config(streaming=streaming, _env_file=None),
    )
    return agent, model, gate, retriever


def test_streaming_defaults_off_and_can_be_enabled_by_environment(monkeypatch):
    assert AgentV2Config(_env_file=None).streaming is False
    monkeypatch.setenv("AGENT_V2_STREAMING", "true")
    assert AgentV2Config(_env_file=None).streaming is True
    assert AgentV2Config(streaming=False, _env_file=None).streaming is False


def test_invalid_streaming_environment_is_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_V2_STREAMING", "perhaps")
    with pytest.raises(ValidationError):
        AgentV2Config(_env_file=None)


def test_stream_yields_only_answer_text_before_complete_result():
    agent, model, _, retriever = make_agent()
    events = iter(agent.stream("Apple revenue?"))
    assert next(events) == {"type": "token", "text": "Revenue "}
    assert next(events) == {"type": "token", "text": "£10."}
    terminal = next(events)
    assert terminal["type"] == "result"
    result = terminal["result"]
    assert isinstance(result, AgentResult)
    assert result.answer == "Revenue £10."
    assert result.status == "answered"
    assert result.citations == ("Report p. 1",)
    assert result.retrieval_attempts == 1
    assert list(events) == []
    model.invoke.assert_not_called()
    model.stream.assert_called_once()
    assert retriever.call_count == 1


def test_disabled_stream_uses_regular_invoke_and_returns_only_final_result():
    agent, model, _, _ = make_agent(streaming=False)
    events = list(agent.stream("Apple revenue?"))
    assert len(events) == 1 and events[0]["type"] == "result"
    assert events[0]["result"].answer == "Revenue £10."
    model.invoke.assert_called_once()
    model.stream.assert_not_called()


@pytest.mark.parametrize("allowed,clarification,status", [
    (False, False, "out_of_domain"), (True, True, "needs_clarification"),
])
def test_static_outcomes_have_one_complete_result_without_model_tokens(allowed, clarification, status):
    agent, model, _, retriever = make_agent(allowed=allowed, clarification=clarification)
    events = list(agent.stream("Question?"))
    assert len(events) == 1
    assert events[0]["result"].status == status
    assert events[0]["result"].retrieval_attempts == 0
    assert events[0]["result"].citations == ()
    model.stream.assert_not_called()
    model.invoke.assert_not_called()
    retriever.assert_not_called()


@pytest.mark.parametrize("question,error", [("", ValueError), (" \n", ValueError), (None, TypeError), (42, TypeError)])
def test_stream_rejects_invalid_question_before_dependencies(question, error):
    agent, model, gate, retriever = make_agent()
    with pytest.raises(error, match="question"):
        list(agent.stream(question))
    gate.invoke.assert_not_called()
    retriever.assert_not_called()
    model.stream.assert_not_called()


def test_failure_after_partial_answer_propagates_without_success_result():
    failure = RuntimeError("answer stream failed")

    def broken_stream(_):
        yield AIMessageChunk(content="Partial")
        raise failure

    model = Mock(stream=broken_stream)
    agent, _, _, _ = make_agent(answer_model=model)
    events = iter(agent.stream("Apple revenue?"))
    assert next(events) == {"type": "token", "text": "Partial"}
    with pytest.raises(RuntimeError, match="answer stream failed") as raised:
        list(events)
    assert raised.value is failure


def test_successive_streams_do_not_share_answer_or_evidence():
    model = FakeListChatModel(responses=["First", "Second"])
    agent, _, _, retriever = make_agent(answer_model=model)
    retriever.side_effect = [[RetrievedChunk("one", "First report")], [RetrievedChunk("two", "Second report")]]
    first = list(agent.stream("First question"))
    second = list(agent.stream("Second question"))
    assert first[-1]["result"].answer == "First"
    assert second[-1]["result"].answer == "Second"
    assert second[-1]["result"].citations == ("Second report",)
    assert second[-1]["result"].retrieval_attempts == 1


def test_streaming_answer_model_is_nested_in_complete_graph_trace():
    class Events(BaseCallbackHandler):
        def __init__(self):
            self.parents = {}
            self.roots = []
            self.models = []
            self.tokens = []
            self.root_inputs = None

        def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
            self.parents[run_id] = parent_run_id
            if parent_run_id is None:
                self.roots.append((run_id, kwargs.get("name")))
                self.root_inputs = inputs

        def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
            self.parents[run_id] = parent_run_id
            self.models.append(run_id)

        def on_llm_new_token(self, token, **kwargs):
            self.tokens.append(token)

    agent, _, _, _ = make_agent(answer_model=FakeListChatModel(responses=["10"]))
    callbacks = Events()
    agent.tracer = callbacks
    result = list(agent.stream("Apple revenue?"))[-1]["result"]
    assert result.answer == "10"
    assert len(callbacks.roots) == 1 and "v2" in callbacks.roots[0][1]
    assert callbacks.models and callbacks.tokens
    assert callbacks.root_inputs == {"question": "Apple revenue?", "context": [], "retrieval_attempts": 0}
    for run_id in callbacks.models:
        while callbacks.parents[run_id] is not None:
            run_id = callbacks.parents[run_id]
        assert run_id == callbacks.roots[0][0]
