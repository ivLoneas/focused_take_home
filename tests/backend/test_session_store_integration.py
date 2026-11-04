"""Opt-in PostgreSQL session durability, expiry, and optimistic concurrency checks."""

import os
import secrets
from functools import partial
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from backend.models import SessionState
from backend.sessions import SessionStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("WEB_SESSION_TEST_DATABASE_URL"),
    reason="Set WEB_SESSION_TEST_DATABASE_URL to run isolated PostgreSQL session-store checks",
)


@pytest.fixture
def session_database():
    database_url = os.environ["WEB_SESSION_TEST_DATABASE_URL"]
    schema = "web_sessions_test_" + uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            yield partial(psycopg.connect, database_url, options=f"-csearch_path={schema}")
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_production_store_persists_across_instances_and_enforces_cas_and_expiry(session_database):
    token = secrets.token_urlsafe(32)
    session_hash = sha256(token.encode()).hexdigest()
    store = SessionStore(session_database)
    store.initialize()
    initial = store.create(session_hash, 1800)
    assert initial.version == 0 and initial.state == SessionState()

    state = SessionState.model_validate({"active_thread_id": "thread-one", "threads": [{
        "id": "thread-one", "agent_id": "agent_v2", "created_at": "2026-11-04T10:00:00Z",
        "updated_at": "2026-11-04T10:00:00Z", "turns": [{
            "question": "Revenue?", "status": "needs_clarification", "answer": "Which company?",
            "citations": [], "retrieval_attempts": 0, "created_at": "2026-11-04T10:00:00Z",
            "metrics": {"total_tokens": 12, "cost_usd": .000001, "response_ms": 25, "first_token_ms": None},
        }],
    }]})
    assert store.save(session_hash, state, expected_version=initial.version, ttl_seconds=1800)

    restored_store = SessionStore(session_database)
    restored_store.initialize()
    restored = restored_store.load(session_hash, 1800)
    assert restored is not None and restored.version == 1 and restored.state == state
    assert not restored_store.save(session_hash, SessionState(), expected_version=0, ttl_seconds=1800)
    unchanged = store.load(session_hash, 1800)
    assert unchanged is not None and unchanged.version == 1 and unchanged.state == state

    with session_database() as connection:
        row = connection.execute("SELECT session_hash, state, version FROM web_sessions").fetchone()
        assert row is not None and row[0] == session_hash and token not in repr(row)
        connection.execute(
            "UPDATE web_sessions SET expires_at = CURRENT_TIMESTAMP + interval '1 second' WHERE session_hash = %s",
            (session_hash,),
        )
    assert restored_store.load(session_hash, 1800) is not None
    with session_database() as connection:
        assert connection.execute(
            "SELECT expires_at > CURRENT_TIMESTAMP + interval '1700 seconds' FROM web_sessions WHERE session_hash = %s",
            (session_hash,),
        ).fetchone() == (True,)
        connection.execute(
            "UPDATE web_sessions SET expires_at = CURRENT_TIMESTAMP - interval '1 second' WHERE session_hash = %s",
            (session_hash,),
        )
    assert restored_store.load(session_hash, 1800) is None
    assert not store.save(session_hash, state, expected_version=1, ttl_seconds=1800)
    assert restored_store.load("0" * 64, 1800) is None
