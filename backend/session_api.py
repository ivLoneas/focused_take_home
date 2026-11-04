"""Cookie-scoped thread endpoints; conversation history stays on the server."""

import json
import logging
import re
import secrets
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import partial
from threading import Lock
from time import perf_counter
from uuid import uuid4

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agents.tracing import question_thread
from backend.clarifications import prepare_question
from backend.config import Settings
from backend.models import (
    ActiveThreadRequest,
    QuestionThread,
    RunRequest,
    RunResponse,
    RunUsage,
    SessionRecord,
    SessionRunRequest,
    SessionState,
    ThreadTurn,
)
from backend.sessions import SessionStore
from utils import sha256_text

LOGGER = logging.getLogger(__name__)
COOKIE_NAME = "focused_session"
EXPIRED_DETAIL = "Your session expired. Choose New question to start a new session."
CONFLICT_DETAIL = "The session changed while this request was running. Refresh and retry."


def register_session_routes(
    app: FastAPI, settings: Settings, *, session_store_factory: Callable[[], SessionStore] | None,
    invoke: Callable[[RunRequest], RunResponse], stream: Callable[[RunRequest], Iterator[dict]],
    unavailable_detail: str,
) -> None:
    store = None
    store_lock = Lock()

    def access_store() -> SessionStore:
        nonlocal store
        with store_lock:
            if store is None:
                candidate = session_store_factory() if session_store_factory else SessionStore(
                    partial(psycopg.connect, settings.database_url),
                )
                candidate.initialize()
                store = candidate
        return store

    def db_call(operation: Callable):
        try:
            return operation(access_store())
        except Exception as error:  # noqa: BLE001 - session/database credentials must stay private.
            LOGGER.error("Web session operation failed (%s)", type(error).__name__)
            raise HTTPException(status_code=503, detail=unavailable_detail) from None

    def check_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        own_origin = f"{request.url.scheme}://{request.url.netloc}"
        if origin is not None and origin not in {*settings.cors_origins, own_origin}:
            raise HTTPException(status_code=403, detail="Origin is not allowed")

    def current_session(request: Request) -> tuple[str, SessionRecord]:
        check_origin(request)
        token = request.cookies.get(COOKIE_NAME, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise HTTPException(status_code=401, detail=EXPIRED_DETAIL)
        session_hash = sha256_text(token)
        record = db_call(lambda db: db.load(session_hash, settings.session_ttl_seconds))
        if record is None:
            raise HTTPException(status_code=401, detail=EXPIRED_DETAIL)
        return session_hash, record

    def state_response(state: SessionState) -> JSONResponse:
        return JSONResponse(state.model_dump(), headers={"Cache-Control": "no-store"})

    def save_state(session_hash: str, record: SessionRecord, state: SessionState) -> None:
        saved = db_call(lambda db: db.save(session_hash, state, record.version, settings.session_ttl_seconds))
        if not saved:
            raise HTTPException(status_code=409, detail=CONFLICT_DETAIL)

    @app.get("/api/session")
    def bootstrap(request: Request) -> JSONResponse:
        check_origin(request)
        token = request.cookies.get(COOKIE_NAME, "")
        record = None
        if re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            record = db_call(lambda db: db.load(sha256_text(token), settings.session_ttl_seconds))
        if record is not None:
            return state_response(record.state)
        token = secrets.token_urlsafe(32)
        record = db_call(lambda db: db.create(sha256_text(token), settings.session_ttl_seconds))
        response = state_response(record.state)
        response.set_cookie(COOKIE_NAME, token, httponly=True, secure=settings.session_cookie_secure,
                            samesite="lax", path="/api")
        return response

    @app.put("/api/session/active-thread")
    def activate(request: Request, selected: ActiveThreadRequest) -> JSONResponse:
        session_hash, record = current_session(request)
        if selected.thread_id is not None and not any(t.id == selected.thread_id for t in record.state.threads):
            raise HTTPException(status_code=404, detail="Unknown thread")
        state = record.state.model_copy(update={"active_thread_id": selected.thread_id}, deep=True)
        save_state(session_hash, record, state)
        return state_response(state)

    @app.delete("/api/session/threads")
    def clear(request: Request) -> JSONResponse:
        session_hash, record = current_session(request)
        state = SessionState()
        save_state(session_hash, record, state)
        return state_response(state)

    @app.delete("/api/session/threads/{thread_id}")
    def remove(request: Request, thread_id: str) -> JSONResponse:
        session_hash, record = current_session(request)
        if not any(t.id == thread_id for t in record.state.threads):
            raise HTTPException(status_code=404, detail="Unknown thread")
        state = record.state.model_copy(deep=True)
        state.threads = [thread for thread in state.threads if thread.id != thread_id]
        if state.active_thread_id == thread_id:
            state.active_thread_id = None
        save_state(session_hash, record, state)
        return state_response(state)

    @app.post("/api/session/import")
    def import_history(request: Request, state: SessionState) -> JSONResponse:
        session_hash, record = current_session(request)
        if record.state.threads:
            raise HTTPException(status_code=409, detail="This session already contains threads")
        ids = [thread.id for thread in state.threads]
        if len(ids) != len(set(ids)) or (state.active_thread_id is not None and state.active_thread_id not in ids):
            raise HTTPException(status_code=422, detail="Invalid thread identifiers")
        try:
            for thread in state.threads:
                datetime.fromisoformat(thread.created_at)
                datetime.fromisoformat(thread.updated_at)
                for turn in thread.turns:
                    datetime.fromisoformat(turn.created_at)
                    prepare_question(RunRequest(agent_id=thread.agent_id, question=turn.question), settings.max_question_length)
                if any(t.status != "needs_clarification" or len(t.answer) > 2000 for t in thread.turns[:-1]):
                    raise ValueError("Only clarification replies may continue a question")
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        state = state.model_copy(deep=True)
        state.threads.sort(key=lambda thread: thread.updated_at, reverse=True)
        save_state(session_hash, record, state)
        return state_response(state)

    def prepare_run(payload: SessionRunRequest, state: SessionState) -> RunRequest:
        history = []
        if payload.thread_id is not None:
            thread = next((t for t in state.threads if t.id == payload.thread_id), None)
            if thread is None:
                raise HTTPException(status_code=404, detail="Unknown thread")
            if thread.agent_id != payload.agent_id or thread.turns[-1].status != "needs_clarification":
                raise HTTPException(status_code=409, detail="Start a new question for this request")
            if len(thread.turns) > 5:
                raise HTTPException(status_code=409, detail="Clarification limit reached. Start a new question.")
            history = [{"question": turn.question, "clarification": turn.answer} for turn in thread.turns]
        return RunRequest(agent_id=payload.agent_id, question=payload.question, clarification_history=history)

    def complete(
        session_hash: str, record: SessionRecord, payload: SessionRunRequest, result: RunResponse,
        thread_id: str, started: float, first_token_ms: float | None,
    ) -> SessionState:
        result.metrics = result.metrics or RunUsage(total_tokens=None, cost_usd=None)
        result.metrics.response_ms = (perf_counter() - started) * 1000
        result.metrics.first_token_ms = first_token_ms
        now = datetime.now(UTC).isoformat()
        turn = ThreadTurn(**result.model_dump(), question=payload.question, created_at=now)
        state = record.state.model_copy(deep=True)
        if payload.thread_id is None:
            thread = QuestionThread(id=thread_id, agent_id=payload.agent_id, created_at=now, updated_at=now, turns=[turn])
        else:
            thread = next(t for t in state.threads if t.id == payload.thread_id)
            thread.turns.append(turn)
            thread.updated_at = now
        state.threads = [thread, *(t for t in state.threads if t.id != thread.id)][:20]
        state.active_thread_id = thread.id
        save_state(session_hash, record, state)
        return state

    @app.post("/api/session/run")
    def run(request: Request, payload: SessionRunRequest) -> JSONResponse:
        session_hash, record = current_session(request)
        run_request = prepare_run(payload, record.state)
        thread_id = payload.thread_id or str(uuid4())
        started = perf_counter()
        with question_thread(thread_id):
            result = invoke(run_request)
        state = complete(session_hash, record, payload, result, thread_id, started, None)
        return JSONResponse({"result": result.model_dump(exclude_defaults=True), "state": state.model_dump()},
                            headers={"Cache-Control": "no-store"})

    @app.post("/api/session/run/stream")
    def run_stream(request: Request, payload: SessionRunRequest) -> StreamingResponse:
        session_hash, record = current_session(request)
        run_request = prepare_run(payload, record.state)
        thread_id = payload.thread_id or str(uuid4())
        started = perf_counter()
        with question_thread(thread_id):
            events = iter(stream(run_request))

        def encoded() -> Iterator[str]:
            first_token_ms = None
            try:
                while True:
                    try:
                        # AnyIO can advance each step in a different worker context.
                        with question_thread(thread_id):
                            event = next(events)
                    except StopIteration:
                        break
                    if event["type"] == "token":
                        if first_token_ms is None and event["text"]:
                            first_token_ms = (perf_counter() - started) * 1000
                        yield json.dumps(event) + "\n"
                    elif event["type"] == "result":
                        result = event["result"]
                        state = complete(session_hash, record, payload, result, thread_id, started, first_token_ms)
                        yield json.dumps({"type": "result", "result": result.model_dump(exclude_defaults=True),
                                          "state": state.model_dump()}) + "\n"
            except HTTPException as error:
                yield json.dumps({"type": "error", "detail": error.detail, "status": error.status_code}) + "\n"
            except Exception as error:  # noqa: BLE001 - streaming HTTP boundary.
                LOGGER.error("Session stream failed (%s)", type(error).__name__)
                yield json.dumps({"type": "error", "detail": unavailable_detail, "status": 503}) + "\n"

        return StreamingResponse(encoded(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
