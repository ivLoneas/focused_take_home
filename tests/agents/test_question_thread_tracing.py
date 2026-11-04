"""Logical question threads group root and child traces without leaking request context."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import Context
from uuid import uuid4

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda

from agents.agent_v2 import AgentV2, AgentV2Config
from agents.baseline import BaselineAgent
from agents.settings import AgentConfig
from agents.tools import BaselineRetrieverAdapter


class Events(BaseCallbackHandler):
    def __init__(self):
        self.events = []

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        self.events.append(("chain", run_id, parent_run_id, metadata or {}))

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        self.events.append(("model", run_id, parent_run_id, metadata or {}))

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        self.events.append(("tool", run_id, parent_run_id, metadata or {}))

    def on_retriever_start(self, serialized, query, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        self.events.append(("retriever", run_id, parent_run_id, metadata or {}))


class Model(FakeListChatModel):
    def with_structured_output(self, schema, **kwargs):
        decision = {"out_of_domain": False, "needs_clarification": False, "companies": ["Apple"],
                    "required_facts": ["revenue"], "retrieval_query": "revenue", "is_sufficient": True}
        return RunnableLambda(lambda _: schema.model_validate(decision))


class Retriever(BaseRetriever):
    def _get_relevant_documents(self, query, *, run_manager):
        return [Document(page_content="Revenue 10", metadata={"title": "Report", "pages": [1]})]


def make_agent(variant):
    model = Model(responses=["10"])
    retriever = BaselineRetrieverAdapter(retrievers={"Apple": Retriever()})
    if variant == "baseline":
        agent = BaselineAgent(model, retriever=retriever, config=AgentConfig(langsmith_tracing=False, _env_file=None))
    else:
        agent = AgentV2(model, routing_model=model, domain_gate=RunnableLambda(lambda _: True),
                        retriever=retriever, config=AgentV2Config(streaming=variant == "stream", langsmith_tracing=False, _env_file=None))
    agent.tracer = Events()
    return agent


@pytest.fixture(autouse=True)
def clear_address(monkeypatch):
    monkeypatch.delenv("LANGSMITH_AGENT_ID", raising=False)
    monkeypatch.delenv("LANGSMITH_AGENT_ENVIRONMENT", raising=False)


@pytest.mark.parametrize("variant", ["baseline", "v2", "stream"])
def test_question_thread_metadata_reaches_root_and_nested_traces(variant):
    from agents.tracing import question_thread

    agent = make_agent(variant)
    identifier = str(uuid4())
    with question_thread(identifier):
        if variant == "stream":
            assert list(agent.stream("Apple revenue?"))[-1]["result"].answer == "10"
        else:
            assert agent.invoke("Apple revenue?").answer == "10"
    events = agent.tracer.events
    roots = [event for event in events if event[2] is None]
    assert len(roots) == 1 and roots[0][3]["session_id"] == identifier
    assert any(event[0] == "model" for event in events)
    assert any(event[0] == "tool" for event in events)
    assert any(event[0] == "retriever" for event in events)
    assert all(event[3].get("session_id") == identifier for event in events)
    parents = {event[1]: event[2] for event in events}
    for _, run_id, parent, _ in events:
        while parent is not None:
            run_id = parent
            parent = parents[run_id]
        assert run_id == roots[0][1]


@pytest.mark.parametrize("variant", ["baseline", "v2", "stream"])
def test_one_shot_invocations_outside_thread_context_keep_existing_metadata(variant):
    agent = make_agent(variant)
    if variant == "stream":
        list(agent.stream("Apple revenue?"))
    else:
        agent.invoke("Apple revenue?")
    assert all("session_id" not in event[3] for event in agent.tracer.events)


def test_thread_context_restores_parent_and_clears_after_errors_and_separate_contexts():
    from agents.tracing import question_thread, thread_metadata

    first, second = str(uuid4()), str(uuid4())
    assert thread_metadata() == {}
    with question_thread(first):
        assert thread_metadata() == {"session_id": first}
        with pytest.raises(RuntimeError), question_thread(second):
            assert thread_metadata() == {"session_id": second}
            raise RuntimeError("failed call")
        assert thread_metadata() == {"session_id": first}
        assert Context().run(thread_metadata) == {}
    assert thread_metadata() == {}

    def record(identifier):
        with question_thread(identifier):
            observed = thread_metadata()
        return observed, thread_metadata()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(record, [first, second]))
    assert results == [({"session_id": first}, {}), ({"session_id": second}, {})]
