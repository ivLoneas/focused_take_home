"""PostgreSQL-backed browser sessions with optimistic concurrency control."""

from collections.abc import Callable
from pathlib import Path

from backend.models import SessionRecord, SessionState


class SessionStore:
    def __init__(self, connection_factory: Callable) -> None:
        self.connection_factory = connection_factory

    def initialize(self) -> None:
        with self.connection_factory() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(1980527116)")
            conn.execute(Path(__file__).with_name("session_schema.sql").read_text())

    def create(self, session_hash: str, ttl_seconds: int) -> SessionRecord:
        state = SessionState()
        with self.connection_factory() as conn:
            conn.execute("DELETE FROM web_sessions WHERE expires_at <= CURRENT_TIMESTAMP")
            conn.execute(
                "INSERT INTO web_sessions (session_hash, state, expires_at) "
                "VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP + %s * interval '1 second')",
                (session_hash, state.model_dump_json(), ttl_seconds),
            )
        return SessionRecord(state=state, version=0)

    def load(self, session_hash: str, ttl_seconds: int) -> SessionRecord | None:
        with self.connection_factory() as conn:
            row = conn.execute(
                "UPDATE web_sessions SET expires_at = CURRENT_TIMESTAMP + %s * interval '1 second' "
                "WHERE session_hash = %s AND expires_at > CURRENT_TIMESTAMP RETURNING state, version",
                (ttl_seconds, session_hash),
            ).fetchone()
        return None if row is None else SessionRecord(state=SessionState.model_validate(row[0]), version=row[1])

    def save(self, session_hash: str, state: SessionState, expected_version: int, ttl_seconds: int) -> bool:
        with self.connection_factory() as conn:
            row = conn.execute(
                "UPDATE web_sessions SET state = %s::jsonb, version = version + 1, "
                "expires_at = CURRENT_TIMESTAMP + %s * interval '1 second' "
                "WHERE session_hash = %s AND version = %s AND expires_at > CURRENT_TIMESTAMP RETURNING version",
                (state.model_dump_json(), ttl_seconds, session_hash, expected_version),
            ).fetchone()
        return row is not None
