"""Independent acceptance tests for v2's Promptfoo provider contract."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evals import agent_v2_provider as provider


def test_call_api_preserves_result_trajectory_and_reports_per_model_usage(monkeypatch):
    result = SimpleNamespace(status="answered", answer="10", citations=("Apple p. 1",), retrieval_attempts=1,
                             tool_calls=({"name": "listed_companies", "arguments": {}},))
    agent = Mock(invoke=Mock(return_value=result))
    monkeypatch.setattr(provider, "get_agent", Mock(return_value=agent))

    response = provider.call_api("Apple FY2025 revenue?", {}, {})

    agent.invoke.assert_called_once_with("Apple FY2025 revenue?")
    assert response["output"] == "10"
    metadata = response["metadata"]
    assert metadata["status"] == "answered"
    assert metadata["citations"] == ["Apple p. 1"]
    assert metadata["retrieval_attempts"] == 1
    assert metadata["tool_calls"] == [{"name": "listed_companies", "arguments": {}}]
    assert metadata["answer_latency_ms"] >= 0
    assert isinstance(metadata["telemetry"]["by_model"], dict)
    assert response["tokenUsage"]["total"] == metadata["telemetry"]["total_tokens"]


@pytest.mark.parametrize("prompt,exception", [("", ValueError), (" \n", ValueError), (None, TypeError), (4, TypeError)])
def test_invalid_prompt_is_rejected_before_loading_agent(monkeypatch, prompt, exception):
    get_agent = Mock()
    monkeypatch.setattr(provider, "get_agent", get_agent)
    with pytest.raises(exception, match="prompt"):
        provider.call_api(prompt, {}, {})
    get_agent.assert_not_called()


def test_per_model_usage_uses_resolved_names_and_aggregates_repeated_calls(monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    def message(name, inputs, outputs, cached=0, reasoning=0):
        return AIMessage(
            content="answer", response_metadata={"model_name": name},
            usage_metadata={"input_tokens": inputs, "output_tokens": outputs, "total_tokens": inputs + outputs,
                            "input_token_details": {"cache_read": cached},
                            "output_token_details": {"reasoning": reasoning}},
        )

    model = FakeMessagesListChatModel(responses=[
        message("jev-resolved", 10, 1), message("nano-resolved", 20, 2, cached=5),
        message("nano-resolved", 30, 3, reasoning=2), message("mini-resolved", 40, 4),
    ])

    def invoke(question):
        for _ in range(4):
            model.invoke(question)
        return SimpleNamespace(answer="answer", status="answered", citations=(), retrieval_attempts=0, tool_calls=())

    monkeypatch.setattr(provider, "get_agent", lambda: SimpleNamespace(invoke=invoke))

    response = provider.call_api("question", {}, {})

    telemetry = response["metadata"]["telemetry"]
    assert telemetry["model_calls"] == 4
    assert telemetry["input_tokens"] == 100 and telemetry["output_tokens"] == 10
    assert telemetry["by_model"] == {
        "jev-resolved": {"model_calls": 1, "input_tokens": 10, "output_tokens": 1, "total_tokens": 11,
                         "cached_input_tokens": 0, "reasoning_tokens": 0},
        "nano-resolved": {"model_calls": 2, "input_tokens": 50, "output_tokens": 5, "total_tokens": 55,
                          "cached_input_tokens": 5, "reasoning_tokens": 2},
        "mini-resolved": {"model_calls": 1, "input_tokens": 40, "output_tokens": 4, "total_tokens": 44,
                          "cached_input_tokens": 0, "reasoning_tokens": 0},
    }


def test_provider_keeps_dependency_errors_visible(monkeypatch):
    failure = RuntimeError("database unavailable")
    monkeypatch.setattr(provider, "get_agent", Mock(side_effect=failure))
    with pytest.raises(RuntimeError, match="database unavailable") as raised:
        provider.call_api("question", {}, {})
    assert raised.value is failure
