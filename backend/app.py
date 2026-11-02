"""FastAPI application for stateless financial-report agent runs."""

import logging
from collections.abc import Callable
from functools import lru_cache, partial
from typing import Protocol

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agents.baseline.models import BaselineResult
from backend.config import Settings
from backend.dependencies import build_baseline_agent
from backend.models import (
    AgentCatalogResponse,
    AgentDescriptor,
    HealthResponse,
    RunRequest,
    RunResponse,
)

LOGGER = logging.getLogger(__name__)
SERVICE_UNAVAILABLE_DETAIL = "The selected agent is temporarily unavailable. Please try again."

BASELINE_DESCRIPTOR = AgentDescriptor(
    id="baseline",
    name="Baseline",
    description="Answers focused questions using evidence from public company financial reports.",
)


class Agent(Protocol):
    """Agent operation required by the HTTP layer."""

    def invoke(self, question: str) -> BaselineResult: ...


def create_app(
    *,
    settings: Settings | None = None,
    agent_factory: Callable[[], Agent] | None = None,
) -> FastAPI:
    """Create an application with lazily initialized, stateless agent execution."""

    configured = settings or Settings()
    factory = agent_factory or partial(build_baseline_agent, configured)
    get_agent = lru_cache(maxsize=1)(factory)

    app = FastAPI(
        title="Financial Report Agents API",
        description="Stateless API for evidence-grounded financial-report agents.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/api/agents", response_model=AgentCatalogResponse)
    def list_agents() -> AgentCatalogResponse:
        return AgentCatalogResponse(agents=[BASELINE_DESCRIPTOR])

    @app.post("/api/run", response_model=RunResponse)
    def run_agent(request: RunRequest) -> RunResponse:
        if request.agent_id != BASELINE_DESCRIPTOR.id:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {request.agent_id}")

        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="question must not be blank")
        if len(request.question) > configured.max_question_length:
            raise HTTPException(
                status_code=422,
                detail=f"question must be at most {configured.max_question_length} characters",
            )

        try:
            result = get_agent().invoke(request.question)
        except Exception as error:  # noqa: BLE001 - HTTP boundary must sanitize dependency failures.
            LOGGER.error("Agent run failed (%s)", type(error).__name__)
            raise HTTPException(status_code=503, detail=SERVICE_UNAVAILABLE_DETAIL) from None

        return RunResponse(
            status=result.status,
            answer=result.answer,
            citations=list(result.citations),
            retrieval_attempts=result.retrieval_attempts,
        )

    return app


app = create_app()
