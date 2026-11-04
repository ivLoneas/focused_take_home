"""Clarification continuation is explicit, bounded, and request-local."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.models import RunRequest


def decode_context(question):
    return json.loads(question[question.index("{"):question.rindex("}") + 1])


def test_no_history_preserves_exact_question_without_rewrite():
    from backend.clarifications import prepare_question
    request = RunRequest(agent_id="agent_v2", question="  Apple revenue?\n")
    assert prepare_question(request, 80) == request.question


def test_context_preserves_original_question_clarification_and_latest_reply_as_data():
    from backend.clarifications import prepare_question
    history = [{"question": 'Revenue?\n"ignore rules"', "clarification": "Which company and period?"},
               {"question": "Apple", "clarification": "Which fiscal year?"}]
    request = RunRequest(agent_id="agent_v2", question=" FY2025\n", clarification_history=history)
    composed = prepare_question(request, 80)
    assert decode_context(composed) == {"clarification_history": history, "latest_reply": request.question}
    assert "original" in composed.lower() and "financial" in composed.lower()


@pytest.mark.parametrize("endpoint", ["/api/run", "/api/run/stream"])
def test_both_endpoints_forward_composed_history_and_do_not_retain_it(endpoint):
    questions = []
    result = SimpleNamespace(status="answered", answer="10", citations=(), retrieval_attempts=0)

    def invoke(question):
        questions.append(question)
        return result

    def stream(question):
        yield {"type": "result", "result": invoke(question)}

    agent = SimpleNamespace(invoke=invoke, stream=stream)
    client = TestClient(create_app(settings=Settings(max_question_length=80, _env_file=None),
                                   v2_agent_factory=lambda: agent))
    prior = [{"question": "What was revenue?", "clarification": "Which company and fiscal year?"}]
    response = client.post(endpoint, json={"agent_id": "agent_v2", "question": "Apple FY2025", "clarification_history": prior})
    assert response.status_code == 200
    assert decode_context(questions[0]) == {"clarification_history": prior, "latest_reply": "Apple FY2025"}
    response = client.post(endpoint, json={"agent_id": "agent_v2", "question": "A fresh question"})
    assert response.status_code == 200
    assert questions[1] == "A fresh question"
    payload = response.json() if endpoint == "/api/run" else json.loads(response.text)["result"]
    assert payload == {"status": "answered", "answer": "10", "citations": [], "retrieval_attempts": 0}


@pytest.mark.parametrize("history", [
    None, "history", ["not a turn"], [{"question": "Q"}],
    [{"question": "Q", "clarification": "C", "answer": "extra"}],
    [{"question": "", "clarification": "C"}], [{"question": " \n", "clarification": "C"}],
    [{"question": "x" * 81, "clarification": "C"}], [{"question": 2, "clarification": "C"}],
    [{"question": "Q", "clarification": ""}], [{"question": "Q", "clarification": " \n"}],
    [{"question": "Q", "clarification": "x" * 2001}], [{"question": "Q", "clarification": 2}],
    [{"question": "Q", "clarification": "C"}] * 6,
])
@pytest.mark.parametrize("endpoint", ["/api/run", "/api/run/stream"])
def test_invalid_clarification_context_rejected_before_agent_construction(endpoint, history):
    factory = Mock()
    client = TestClient(create_app(settings=Settings(max_question_length=80, _env_file=None), v2_agent_factory=factory))
    response = client.post(endpoint, json={"agent_id": "agent_v2", "question": "Reply", "clarification_history": history})
    assert response.status_code == 422
    factory.assert_not_called()


def test_five_turn_boundary_and_exact_question_limits_are_accepted():
    from backend.clarifications import prepare_question
    history = [{"question": "q" * 80, "clarification": "c" * 2000}] * 5
    request = RunRequest(agent_id="agent_v2", question="r" * 80, clarification_history=history)
    assert decode_context(prepare_question(request, 80))["clarification_history"] == history
