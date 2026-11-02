"""Deterministic Promptfoo checks for response shape and agent trajectory."""

from collections.abc import Mapping
from typing import Any

type GradingResult = dict[str, bool | float | str]

_GROUNDED_TOPICS = frozenset(
    {
        "conditional_reasoning",
        "deterministic_accuracy",
        "extra_calculation",
        "image_questions",
        "multiple_companies",
        "table_questions",
        "tool_usage",
    }
)
_SPECIAL_TOPICS = frozenset({"ambiguous_questions", "in_domain_no_data", "out_of_distribution"})


def assert_non_empty_output(output: object, context: Mapping[str, Any]) -> GradingResult:
    del context
    if not isinstance(output, str) or not output.strip():
        return _failure("Provider output must be a nonblank string")
    return _success("Provider returned a nonblank response")


def assert_trajectory(output: object, context: Mapping[str, Any]) -> GradingResult:
    """Apply topic-specific routing, retrieval, and citation expectations."""

    del output
    values = context.get("vars")
    if not isinstance(values, Mapping):
        return _failure("Test vars metadata is missing or malformed")

    topic = values.get("topic")
    case_id = values.get("id")
    if not isinstance(topic, str) or not topic:
        return _failure("Test topic metadata is missing or malformed")
    if not isinstance(case_id, str) or not case_id:
        return _failure("Test id metadata is missing or malformed")
    if topic not in _GROUNDED_TOPICS | _SPECIAL_TOPICS:
        return _failure(f"Unsupported evaluation topic {topic}")

    metadata = _provider_metadata(context)
    if not isinstance(metadata, Mapping):
        return _failure("Provider response metadata is missing or malformed")

    status = metadata.get("status")
    citations = metadata.get("citations")
    attempts = metadata.get("retrieval_attempts")
    if not isinstance(status, str) or not status:
        return _failure("Provider metadata status is missing or malformed")
    if not isinstance(citations, list) or any(not isinstance(citation, str) for citation in citations):
        return _failure("Provider metadata citations must be a list of strings")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
        return _failure("Provider metadata retrieval_attempts must be a non-negative integer")

    if topic == "out_of_distribution":
        return _expect_no_retrieval(
            case_id=case_id,
            status=status,
            expected_status="out_of_domain",
            citations=citations,
            attempts=attempts,
        )
    if topic == "ambiguous_questions":
        return _expect_no_retrieval(
            case_id=case_id,
            status=status,
            expected_status="needs_clarification",
            citations=citations,
            attempts=attempts,
        )
    if topic == "tool_usage" and case_id == "TOOL10":
        if status != "answered":
            return _failure(f"{case_id} must finish with status answered, got {status}")
        if attempts != 0:
            return _failure(f"{case_id} requires zero retrieval attempts, got {attempts}")
        if citations:
            return _failure(f"{case_id} must not return report citations when no retrieval is needed")
        return _success(f"{case_id} answered without retrieval")
    if topic == "in_domain_no_data":
        if status != "answered":
            return _failure(f"{case_id} must finish with status answered, got {status}")
        if attempts < 1:
            return _failure(f"{case_id} must attempt retrieval before reporting unavailable evidence")
        return _success(f"{case_id} attempted retrieval before reporting unavailable evidence")

    if status != "answered":
        return _failure(f"{case_id} must finish with status answered, got {status}")
    if attempts < 1:
        return _failure(f"{case_id} must perform at least one retrieval attempt")
    if not citations:
        return _failure(f"{case_id} must return at least one citation for a grounded answer")
    return _success(f"{case_id} used retrieval and returned cited evidence")


def _provider_metadata(context: Mapping[str, Any]) -> object:
    metadata = context.get("metadata")
    if metadata is not None:
        return metadata
    response = context.get("providerResponse")
    if not isinstance(response, Mapping):
        return None
    return response.get("metadata")


def _expect_no_retrieval(
    *,
    case_id: str,
    status: str,
    expected_status: str,
    citations: list[str],
    attempts: int,
) -> GradingResult:
    if status != expected_status:
        return _failure(f"{case_id} must finish with status {expected_status}, got {status}")
    if citations:
        return _failure(f"{case_id} must not return a citation for this route")
    if attempts != 0:
        return _failure(f"{case_id} must not perform retrieval; got {attempts} attempt(s)")
    return _success(f"{case_id} followed the {expected_status} route without retrieval")


def _success(reason: str) -> GradingResult:
    return {"pass": True, "score": 1.0, "reason": reason}


def _failure(reason: str) -> GradingResult:
    return {"pass": False, "score": 0.0, "reason": reason}
