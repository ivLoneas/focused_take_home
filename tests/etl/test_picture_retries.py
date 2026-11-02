"""Output truncation retries preserve measured usage and never cache partial prose."""

from itertools import pairwise
from types import SimpleNamespace

import pytest

from etl.pictures import cached_description


def response(status, text, input_tokens, output_tokens, reason=None):
    return SimpleNamespace(
        status=status,
        output_text=text,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )


@pytest.mark.parametrize("partial_text", ["", "Revenue is an unfinished claim"])
def test_truncated_response_retries_and_caches_final_text_with_all_attempt_usage(
    picture_client, picture_png, tmp_path, partial_text
):
    incomplete = response("incomplete", partial_text, 1000, 300, "max_output_tokens")
    completed = response("completed", "The figure shows revenue rising from $10m to $12m.", 1100, 450)
    picture_client.responses.create.side_effect = [incomplete, completed]

    description, usage = cached_description(picture_client, picture_png, tmp_path)

    assert description == completed.output_text
    calls = picture_client.responses.create.call_args_list
    assert len(calls) == 2
    first, retry = [call.kwargs for call in calls]
    assert 0 < first["max_output_tokens"] < retry["max_output_tokens"] <= 2048
    assert {key: value for key, value in first.items() if key != "max_output_tokens"} == {
        key: value for key, value in retry.items() if key != "max_output_tokens"
    }
    assert usage == {
        "input_tokens": 2100,
        "output_tokens": 750,
        "total_tokens": 2850,
        "api_calls": 2,
        "cost_usd": pytest.approx((2100 * 0.10 + 750 * 0.50) / 1_000_000),
    }
    persisted = "\n".join(path.read_text() for path in tmp_path.rglob("*.json"))
    assert completed.output_text in persisted
    if partial_text:
        assert partial_text not in persisted
    picture_client.responses.create.reset_mock()
    assert cached_description(picture_client, picture_png, tmp_path) == (description, usage)
    picture_client.responses.create.assert_not_called()


def test_persistent_output_truncation_stops_within_cap_and_does_not_publish_cache(
    picture_client, picture_png, tmp_path
):
    picture_client.responses.create.return_value = response(
        "incomplete", "Unfinished financial claim", 1000, 300, "max_output_tokens"
    )
    with pytest.raises((ValueError, RuntimeError)):
        cached_description(picture_client, picture_png, tmp_path)

    caps = [call.kwargs["max_output_tokens"] for call in picture_client.responses.create.call_args_list]
    assert len(caps) >= 2, "Output-token truncation requires at least one larger-budget retry"
    assert all(0 < cap <= 2048 for cap in caps)
    assert all(left < right for left, right in pairwise(caps))
    assert not list(tmp_path.rglob("*.json")), "Persistent truncation must not publish a picture cache entry"
    picture_client.responses.create.return_value = response("completed", "Verified final description.", 100, 20)
    picture_client.responses.create.reset_mock()
    assert cached_description(picture_client, picture_png, tmp_path)[0] == "Verified final description."
    picture_client.responses.create.assert_called_once()


def test_failed_response_never_publishes_valid_cache(picture_client, picture_png, tmp_path):
    picture_client.responses.create.return_value = response("failed", "Unusable failed output", 100, 20)
    with pytest.raises((ValueError, RuntimeError)):
        cached_description(picture_client, picture_png, tmp_path)
    assert not list(tmp_path.rglob("*.json"))
    picture_client.responses.create.return_value = response("completed", "Recovered description.", 100, 20)
    picture_client.responses.create.reset_mock()
    assert cached_description(picture_client, picture_png, tmp_path)[0] == "Recovered description."
    picture_client.responses.create.assert_called_once()


def test_empty_completed_retry_cannot_turn_partial_text_into_valid_description(picture_client, picture_png, tmp_path):
    picture_client.responses.create.side_effect = [
        response("incomplete", "Partial text must not become the answer", 1000, 300, "max_output_tokens"),
        response("completed", "  ", 1000, 20),
    ]
    with pytest.raises((ValueError, RuntimeError)):
        cached_description(picture_client, picture_png, tmp_path)
    assert picture_client.responses.create.call_count == 2
    assert not list(tmp_path.rglob("*.json"))
