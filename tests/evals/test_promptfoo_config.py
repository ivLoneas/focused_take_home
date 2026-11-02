"""Small wiring contract for the repository-root Promptfoo invocation."""

import re
from pathlib import Path

CONFIG_PATH = Path("evals/promptfooconfig.yaml")


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
