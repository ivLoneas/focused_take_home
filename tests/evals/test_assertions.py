"""Deterministic Promptfoo assertion contracts."""

from typing import Any

import pytest
from evals.assertions import assert_non_empty_output, assert_trajectory


def context(topic: str, case_id: str, metadata: object) -> dict[str, Any]:
    return {
        "vars": {"id": case_id, "topic": topic},
        "providerResponse": {"metadata": metadata},
    }


def assert_passes(result: dict[str, object]) -> None:
    assert result["pass"] is True
    assert result["score"] == 1
    assert isinstance(result["reason"], str)
    assert result["reason"]


def assert_fails(result: dict[str, object], *reason_fragments: str) -> None:
    assert result["pass"] is False
    assert result["score"] == 0
    reason = result["reason"]
    assert isinstance(reason, str)
    for fragment in reason_fragments:
        assert fragment.lower() in reason.lower()


@pytest.mark.parametrize("output", ["answer", "  answer with padding  "])
def test_non_empty_output_passes(output: str) -> None:
    assert_passes(assert_non_empty_output(output, {}))


@pytest.mark.parametrize("output", [None, 123, b"answer", "", " \t\n"])
def test_non_empty_output_rejects_missing_non_string_or_blank_output(output: object) -> None:
    assert_fails(assert_non_empty_output(output, {}), "output")


@pytest.mark.parametrize(
    ("topic", "case_id", "metadata"),
    [
        (
            "out_of_distribution",
            "OOD01",
            {"status": "out_of_domain", "citations": [], "retrieval_attempts": 0},
        ),
        (
            "ambiguous_questions",
            "AMB01",
            {"status": "needs_clarification", "citations": [], "retrieval_attempts": 0},
        ),
        (
            "tool_usage",
            "TOOL10",
            {"status": "answered", "citations": [], "retrieval_attempts": 0},
        ),
        (
            "in_domain_no_data",
            "NODATA01",
            {"status": "answered", "citations": [], "retrieval_attempts": 1},
        ),
    ],
)
def test_special_trajectory_categories_pass_for_the_expected_route(
    topic: str,
    case_id: str,
    metadata: dict[str, object],
) -> None:
    assert_passes(assert_trajectory("answer", context(topic, case_id, metadata)))


@pytest.mark.parametrize(
    "topic",
    [
        "tool_usage",
        "deterministic_accuracy",
        "multiple_companies",
        "conditional_reasoning",
        "extra_calculation",
        "image_questions",
        "table_questions",
    ],
)
def test_grounded_positive_categories_require_retrieval_and_citations(topic: str) -> None:
    result = assert_trajectory(
        "grounded answer",
        context(
            topic,
            "TOOL01" if topic == "tool_usage" else "CASE01",
            {"status": "answered", "citations": ["Report p. 1"], "retrieval_attempts": 1},
        ),
    )

    assert_passes(result)


@pytest.mark.parametrize(
    ("topic", "case_id", "metadata", "reason"),
    [
        (
            "out_of_distribution",
            "OOD01",
            {"status": "answered", "citations": [], "retrieval_attempts": 0},
            "out_of_domain",
        ),
        (
            "out_of_distribution",
            "OOD01",
            {"status": "out_of_domain", "citations": ["fabricated"], "retrieval_attempts": 0},
            "citation",
        ),
        (
            "out_of_distribution",
            "OOD01",
            {"status": "out_of_domain", "citations": [], "retrieval_attempts": 1},
            "retrieval",
        ),
        (
            "ambiguous_questions",
            "AMB01",
            {"status": "answered", "citations": [], "retrieval_attempts": 0},
            "needs_clarification",
        ),
        (
            "ambiguous_questions",
            "AMB01",
            {"status": "needs_clarification", "citations": ["fabricated"], "retrieval_attempts": 0},
            "citation",
        ),
        (
            "ambiguous_questions",
            "AMB01",
            {"status": "needs_clarification", "citations": [], "retrieval_attempts": 1},
            "retrieval",
        ),
        (
            "tool_usage",
            "TOOL10",
            {"status": "answered", "citations": [], "retrieval_attempts": 1},
            "zero retrieval",
        ),
        (
            "deterministic_accuracy",
            "ACC01",
            {"status": "answered", "citations": ["Report p. 1"], "retrieval_attempts": 0},
            "retrieval",
        ),
        (
            "deterministic_accuracy",
            "ACC01",
            {"status": "answered", "citations": [], "retrieval_attempts": 1},
            "citation",
        ),
        (
            "in_domain_no_data",
            "NODATA01",
            {"status": "answered", "citations": [], "retrieval_attempts": 0},
            "retrieval",
        ),
    ],
)
def test_trajectory_rule_violations_return_a_diagnostic_failure(
    topic: str,
    case_id: str,
    metadata: dict[str, object],
    reason: str,
) -> None:
    assert_fails(assert_trajectory("answer", context(topic, case_id, metadata)), reason)


@pytest.mark.parametrize(
    ("broken_context", "reason"),
    [
        ({}, "metadata"),
        ({"vars": {"id": "ACC01", "topic": "deterministic_accuracy"}}, "metadata"),
        (
            {"vars": {"id": "ACC01", "topic": "deterministic_accuracy"}, "providerResponse": {}},
            "metadata",
        ),
        (
            context("deterministic_accuracy", "ACC01", {"citations": [], "retrieval_attempts": 1}),
            "status",
        ),
        (
            context(
                "deterministic_accuracy",
                "ACC01",
                {"status": "answered", "retrieval_attempts": 1},
            ),
            "citations",
        ),
        (
            context(
                "deterministic_accuracy",
                "ACC01",
                {"status": "answered", "citations": [], "retrieval_attempts": "one"},
            ),
            "retrieval_attempts",
        ),
        (
            context(
                "deterministic_accuracy",
                "ACC01",
                {"status": "answered", "citations": "Report p. 1", "retrieval_attempts": 1},
            ),
            "citations",
        ),
        (
            context(
                "unknown_topic",
                "UNKNOWN01",
                {"status": "answered", "citations": [], "retrieval_attempts": 0},
            ),
            "unknown_topic",
        ),
    ],
)
def test_malformed_or_unknown_metadata_fails_without_raising(
    broken_context: dict[str, object],
    reason: str,
) -> None:
    assert_fails(assert_trajectory("answer", broken_context), reason)
