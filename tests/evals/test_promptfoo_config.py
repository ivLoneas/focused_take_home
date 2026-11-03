"""Small wiring contract for the repository-root Promptfoo invocation."""

import re
from pathlib import Path

import pytest

CONFIG_PATH = Path("evals/promptfooconfig.yaml")


@pytest.mark.parametrize("config_path", sorted(Path("evals").glob("promptfooconfig*.yaml")), ids=lambda path: path.name)
def test_every_active_evaluation_uses_current_answer_model_for_grading(config_path: Path) -> None:
    """Baseline, v2, and paired comparisons must use the same current grader."""
    config = config_path.read_text(encoding="utf-8")

    graders = re.findall(r"(?m)^\s+provider:\s+(openai:[^\s#]+)", config)

    assert graders == ["openai:gpt-6.1-terra"]


def test_example_environment_documents_current_answer_and_routing_defaults() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")

    assert re.search(r"(?m)^AGENT_MODEL=gpt-6\.1-terra$", example)
    assert re.search(r"(?m)^CHAT_MODEL=gpt-6\.1-terra$", example)
    assert re.search(r"(?m)^AGENT_V2_ROUTING_MODEL=gpt-6-luna$", example)


def test_promptfoo_config_wires_prompt_provider_generator_grader_and_runtime_bounds() -> None:
    config = CONFIG_PATH.read_text(encoding="utf-8")

    assert re.search(r"(?m)^prompts:\s*$", config)
    assert "{{test}}" in config
    assert re.search(r"(?m)^providers:\s*$", config)
    assert "file://provider.py" in config
    assert re.search(r"(?m)^tests:\s*$", config)
    assert "file://generate_tests.py:generate_tests" in config
    assert re.search(r"(?m)^\s+provider:\s+openai:[^\s#]+", config)

    concurrency = re.search(r"(?m)^\s+maxConcurrency:\s+(\d+)\s*(?:#.*)?$", config)
    timeout = re.search(r"(?m)^\s+timeoutMs:\s+(\d+)\s*(?:#.*)?$", config)
    assert concurrency is not None
    assert 1 <= int(concurrency.group(1)) <= 10
    assert timeout is not None
    assert 1_000 <= int(timeout.group(1)) <= 600_000
