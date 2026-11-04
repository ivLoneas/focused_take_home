"""Request-local conversation metadata for complete agent traces."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_question_thread: ContextVar[str | None] = ContextVar("focused_question_thread", default=None)


@contextmanager
def question_thread(thread_id: str) -> Iterator[None]:
    """Scope tracing to a logical question without exposing browser credentials."""
    token = _question_thread.set(thread_id)
    try:
        yield
    finally:
        _question_thread.reset(token)


def thread_metadata() -> dict[str, str]:
    thread_id = _question_thread.get()
    return {"session_id": thread_id} if thread_id is not None else {}
