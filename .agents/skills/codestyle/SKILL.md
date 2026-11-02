---
name: codestyle
description: Apply this repository's Python development standards when implementing or modifying application code. Use for feature work, bug fixes, refactoring, and review work that includes code changes; do not invoke for read-only analysis or documentation-only changes.
---

# Project Codestyle

Use this workflow for implementation work in this repository.

## Development workflow

1. Formalize the functional requirements before writing tests or implementation. Record the observable behavior, inputs and outputs, constraints, acceptance criteria, and expected failure behavior relevant to the change. Resolve material ambiguity before proceeding.
2. Before implementation, delegate the requirements to an independent subagent. Ask it to analyze the requirements and author the test set without seeing or relying on implementation details. Do not implement concurrently with this test-design pass. If subagent delegation is unavailable, pause implementation and report the limitation.
3. Review the independent tests for alignment with the formalized requirements. The suite must cover happy paths, boundary and edge cases, invalid inputs, and error handling.
4. Follow red-green-refactor: confirm the new tests fail for the expected reason, write the smallest implementation that makes them pass, then simplify without changing behavior. Run focused tests first and the relevant broader checks afterward.

## Design and organization

- Prefer the simplest design that satisfies the requirements and tests. Avoid speculative abstractions, unnecessary indirection or design patterns, and overly elaborate data structures.
- Before adding a helper, search `utils/utils.py` and existing feature modules for equivalent behavior. If two or more
  project subdirectories share the same generic functionality, they must import one implementation from
  `utils/utils.py`; do not keep parallel copies or add forwarding wrappers unless a public compatibility contract
  requires one.
- Keep `utils/utils.py` limited to infrastructure-neutral operations such as serialization, hashing, atomic file I/O,
  generic validation, ordering, and reusable formatting. Keep domain decisions and business rules in their owning
  `agents/`, `etl/`, `evals/`, or other feature module; shared utilities are not a dumping ground.
- Keep business logic out of models and dataclasses. Put data containers for each project section in that section's `models.py`, such as `agent/models.py`, `view/models.py`, or `etl/models.py`. Do not create an empty `models.py` when a section has no data structures.
- Keep comments and docstrings concise and informative. Document contracts, intent, invariants, and non-obvious decisions; do not narrate self-explanatory code.

## Python conventions

- Target Python 3.14 and use modern typing syntax, including built-in generics such as `list[str]`, union syntax such as `str | None`, and `type` statements for type aliases when appropriate.
- Define application configuration and secrets with `pydantic-settings`. Do not use `python-dotenv`, call `load_dotenv`, or read application settings directly with `os.getenv` or `os.environ`. Direct environment access is acceptable only when integrating with a dependency that itself requires process-environment manipulation.
- Do not add `from __future__ import annotations`.
- Do not add compatibility code for older Python versions unless a requirement explicitly calls for it.
