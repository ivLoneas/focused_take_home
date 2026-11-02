"""HTTP contract for the stateless agent-facing FastAPI service."""

from collections.abc import Callable
from dataclasses import dataclass

import pytest
from backend.app import SERVICE_UNAVAILABLE_DETAIL, create_app
from backend.config import Settings
from fastapi.testclient import TestClient

from agents.baseline.models import BaselineResult


@dataclass
class FakeAgent:
    """Small deterministic agent double that records only current questions."""

    result_for: Callable[[str], BaselineResult]

    def __post_init__(self) -> None:
        self.questions: list[str] = []

    def invoke(self, question: str) -> BaselineResult:
        self.questions.append(question)
        return self.result_for(question)


def answered(question: str) -> BaselineResult:
    return BaselineResult(
        status="answered",
        answer=f"Answer for: {question}",
        citations=("Apple FY2025 10-K | p. 29",),
        retrieval_attempts=2,
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://rag:rag@localhost:5432/rag",
        chat_model="gpt-test",
        embedding_model="embedding-test",
        retrieval_limit=5,
        max_question_length=80,
        cors_origins=["http://localhost:5173"],
        _env_file=None,
    )


@pytest.fixture
def agent() -> FakeAgent:
    return FakeAgent(answered)


@pytest.fixture
def client(settings: Settings, agent: FakeAgent) -> TestClient:
    app = create_app(settings=settings, agent_factory=lambda: agent)
    return TestClient(app)


def test_health_endpoint_is_small_and_does_not_construct_agent(settings: Settings):
    factory_calls = 0

    def agent_factory():
        nonlocal factory_calls
        factory_calls += 1
        return FakeAgent(answered)

    app = create_app(settings=settings, agent_factory=agent_factory)
    assert factory_calls == 0

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert factory_calls == 0


def test_agent_catalog_contains_only_the_baseline_agent(client: TestClient):
    response = client.get("/api/agents")

    assert response.status_code == 200
    agents = response.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["id"] == "baseline"
    assert agents[0]["name"]
    assert "financial" in agents[0]["description"].lower()


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            BaselineResult("answered", "Revenue was $10bn.", ("Report p. 4",), 1),
            {
                "status": "answered",
                "answer": "Revenue was $10bn.",
                "citations": ["Report p. 4"],
                "retrieval_attempts": 1,
            },
        ),
        (
            BaselineResult("needs_clarification", "Which fiscal year?", (), 0),
            {
                "status": "needs_clarification",
                "answer": "Which fiscal year?",
                "citations": [],
                "retrieval_attempts": 0,
            },
        ),
        (
            BaselineResult("out_of_domain", "Ask about a financial report.", (), 0),
            {
                "status": "out_of_domain",
                "answer": "Ask about a financial report.",
                "citations": [],
                "retrieval_attempts": 0,
            },
        ),
    ],
)
def test_run_serializes_every_baseline_outcome(settings: Settings, result: BaselineResult, expected: dict):
    agent = FakeAgent(lambda _: result)
    app = create_app(settings=settings, agent_factory=lambda: agent)

    response = TestClient(app).post(
        "/api/run",
        json={"agent_id": "baseline", "question": "What was Apple revenue?"},
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert agent.questions == ["What was Apple revenue?"]


def test_each_run_passes_only_that_request_question_to_the_stateless_agent(
    client: TestClient,
    agent: FakeAgent,
):
    first = client.post("/api/run", json={"agent_id": "baseline", "question": "Question one"})
    second = client.post("/api/run", json={"agent_id": "baseline", "question": "Question two"})

    assert first.json()["answer"] == "Answer for: Question one"
    assert second.json()["answer"] == "Answer for: Question two"
    assert agent.questions == ["Question one", "Question two"]


def test_unknown_agent_is_rejected_without_constructing_an_agent(settings: Settings):
    factory_calls = 0

    def agent_factory():
        nonlocal factory_calls
        factory_calls += 1
        return FakeAgent(answered)

    app = create_app(settings=settings, agent_factory=agent_factory)
    response = TestClient(app).post(
        "/api/run",
        json={"agent_id": "future-agent", "question": "What was revenue?"},
    )

    assert response.status_code == 404
    assert "agent" in response.json()["detail"].lower()
    assert factory_calls == 0


@pytest.mark.parametrize("question", ["", " ", "\t\n"])
def test_blank_question_is_rejected(client: TestClient, agent: FakeAgent, question: str):
    response = client.post("/api/run", json={"agent_id": "baseline", "question": question})

    assert response.status_code == 422
    assert "question" in response.text.lower()
    assert agent.questions == []


def test_question_at_configured_limit_is_accepted(client: TestClient, agent: FakeAgent):
    question = "x" * 80

    response = client.post("/api/run", json={"agent_id": "baseline", "question": question})

    assert response.status_code == 200
    assert agent.questions == [question]


def test_question_beyond_configured_limit_is_rejected(client: TestClient, agent: FakeAgent):
    response = client.post(
        "/api/run",
        json={"agent_id": "baseline", "question": "x" * 81},
    )

    assert response.status_code == 422
    assert "question" in response.text.lower()
    assert agent.questions == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"agent_id": "baseline"},
        {"question": "What was revenue?"},
        {"agent_id": "baseline", "question": 42},
        {"agent_id": "baseline", "question": "Revenue?", "history": ["secret prior turn"]},
    ],
)
def test_malformed_or_stateful_request_payload_is_rejected(client: TestClient, payload: dict):
    response = client.post("/api/run", json=payload)

    assert response.status_code == 422


def test_agent_failure_returns_stable_non_secret_503(settings: Settings):
    secret = "postgresql://admin:super-secret@database/internal"

    def fail(_: str) -> BaselineResult:
        raise RuntimeError(f"connection failed: {secret}")

    app = create_app(settings=settings, agent_factory=lambda: FakeAgent(fail))
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/run",
        json={"agent_id": "baseline", "question": "What was revenue?"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": SERVICE_UNAVAILABLE_DETAIL}
    assert secret not in response.text
    assert "connection failed" not in response.text


def test_agent_construction_failure_returns_the_same_stable_503(settings: Settings):
    def fail_to_construct():
        raise RuntimeError("OPENAI_API_KEY=do-not-leak")

    app = create_app(settings=settings, agent_factory=fail_to_construct)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/run",
        json={"agent_id": "baseline", "question": "What was revenue?"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": SERVICE_UNAVAILABLE_DETAIL}
    assert "do-not-leak" not in response.text


def test_cors_allows_only_the_configured_frontend_origin(client: TestClient):
    allowed = client.options(
        "/api/run",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    denied = client.options(
        "/api/run",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert denied.headers.get("access-control-allow-origin") is None
    assert allowed.headers.get("access-control-allow-credentials") != "true"
