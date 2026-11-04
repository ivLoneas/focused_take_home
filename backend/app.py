"""FastAPI application for financial-report runs and cookie-scoped sessions."""

import json
import logging
from collections.abc import Callable, Iterator
from functools import lru_cache, partial
from typing import Protocol

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agents.baseline.models import BaselineResult
from agents.telemetry import ModelMetrics
from backend.clarifications import prepare_question
from backend.config import Settings
from backend.dependencies import build_agent_v2, build_baseline_agent
from backend.models import (
    AgentCatalogResponse,
    AgentDescriptor,
    HealthResponse,
    RunRequest,
    RunResponse,
    RunUsage,
)
from backend.session_api import register_session_routes
from backend.sessions import SessionStore
from backend.usage import summarize_usage

LOGGER = logging.getLogger(__name__)
SERVICE_UNAVAILABLE_DETAIL = "The selected agent is temporarily unavailable. Please try again."

BASELINE_DESCRIPTOR = AgentDescriptor(
    id="baseline",
    name="Baseline",
    description="Answers focused questions using evidence from public company financial reports.",
)

V2_DESCRIPTOR = AgentDescriptor(
    id="agent_v2",
    name="Agent v2",
    description="Streams evidence-grounded financial-report answers with domain screening and retrieval planning.",
)


class Agent(Protocol):
    """Agent operation required by the HTTP layer."""

    def invoke(self, question: str) -> BaselineResult: ...


class StreamingAgent(Agent, Protocol):
    def stream(self, question: str) -> Iterator[dict]: ...


def create_app(
    *,
    settings: Settings | None = None,
    agent_factory: Callable[[], Agent] | None = None,
    v2_agent_factory: Callable[[], StreamingAgent] | None = None,
    session_store_factory: Callable[[], SessionStore] | None = None,
) -> FastAPI:
    """Create one-shot agent endpoints and lazily initialized browser sessions."""

    configured = settings or Settings()
    factory = agent_factory or partial(build_baseline_agent, configured)
    get_agent = lru_cache(maxsize=1)(factory)
    get_v2_agent = lru_cache(maxsize=1)(v2_agent_factory or partial(build_agent_v2, configured))

    app = FastAPI(
        title="Financial Report Agents API",
        description="Evidence-grounded financial-report agents with cookie-scoped question threads.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/api/agents", response_model=AgentCatalogResponse)
    def list_agents() -> AgentCatalogResponse:
        return AgentCatalogResponse(agents=[BASELINE_DESCRIPTOR, V2_DESCRIPTOR])

    def validate_request(request: RunRequest) -> str:
        if request.agent_id not in {BASELINE_DESCRIPTOR.id, V2_DESCRIPTOR.id}:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {request.agent_id}")

        try:
            return prepare_question(request, configured.max_question_length)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    def run_response(result: BaselineResult, metrics: ModelMetrics) -> RunResponse:
        response = RunResponse.model_validate(result, from_attributes=True)
        telemetry = metrics.metadata()
        if telemetry["model_calls"] or telemetry["embedding_calls"]:
            response.metrics = RunUsage(**summarize_usage(telemetry, configured.embedding_model))
        return response

    @app.post("/api/run", response_model=RunResponse, response_model_exclude_defaults=True)
    def run_agent(request: RunRequest) -> RunResponse:
        question = validate_request(request)
        try:
            agent = get_v2_agent() if request.agent_id == V2_DESCRIPTOR.id else get_agent()
            with ModelMetrics() as metrics:
                result = agent.invoke(question)
        except Exception as error:  # noqa: BLE001 - HTTP boundary must sanitize dependency failures.
            LOGGER.error("Agent run failed (%s)", type(error).__name__)
            raise HTTPException(status_code=503, detail=SERVICE_UNAVAILABLE_DETAIL) from None

        return run_response(result, metrics)

    def stream_events(request: RunRequest) -> Iterator[dict]:
        question = validate_request(request)
        if request.agent_id != V2_DESCRIPTOR.id:
            raise HTTPException(status_code=400, detail="Streaming is available for agent_v2")
        try:
            agent = get_v2_agent()
        except Exception as error:  # noqa: BLE001 - sanitize dependency failures.
            LOGGER.error("Agent construction failed (%s)", type(error).__name__)
            raise HTTPException(status_code=503, detail=SERVICE_UNAVAILABLE_DETAIL) from None

        def events() -> Iterator[dict]:
            metrics = ModelMetrics()
            with metrics:
                stream = iter(agent.stream(question))
            while True:
                try:
                    # Each HTTP iterator step may run in a different worker context.
                    with metrics:
                        event = next(stream)
                except StopIteration:
                    break
                if event["type"] == "result":
                    yield {"type": "result", "result": run_response(event["result"], metrics)}
                elif event["type"] == "token":
                    yield {"type": "token", "text": event["text"]}
        return events()

    @app.post("/api/run/stream", response_class=StreamingResponse)
    def stream_agent(request: RunRequest) -> StreamingResponse:
        events = stream_events(request)

        def encoded() -> Iterator[str]:
            try:
                for event in events:
                    if event["type"] == "result":
                        event = {"type": "result", "result": event["result"].model_dump(exclude_defaults=True)}
                    yield json.dumps(event) + "\n"
            except Exception as error:  # noqa: BLE001 - response headers have already been sent.
                LOGGER.error("Agent stream failed (%s)", type(error).__name__)
                yield json.dumps({"type": "error", "detail": SERVICE_UNAVAILABLE_DETAIL}) + "\n"

        return StreamingResponse(
            encoded(), media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    register_session_routes(
        app, configured, session_store_factory=session_store_factory, invoke=run_agent,
        stream=stream_events, unavailable_detail=SERVICE_UNAVAILABLE_DETAIL,
    )
    return app


app = create_app()
