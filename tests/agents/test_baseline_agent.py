"""Behavioral contract for the baseline financial-report agent workflow."""

from collections import defaultdict
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda

from agents.baseline.baseline_agent import BaselineAgent, RetrievalRequest, RetrievedChunk


def analysis(
    *,
    out_of_domain: bool = False,
    needs_clarification: bool = False,
    clarification_question: str | None = None,
    required_facts: list[str] | None = None,
    retrieval_query: str = "",
) -> dict[str, Any]:
    return {
        "out_of_domain": out_of_domain,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "required_facts": required_facts or [],
        "retrieval_query": retrieval_query,
    }


def assessment(is_sufficient: bool, refined_query: str | None = None) -> dict[str, Any]:
    return {"is_sufficient": is_sufficient, "refined_query": refined_query}


def answer(text: str) -> dict[str, str]:
    return {"answer": text}


def prompt_text(value: object) -> str:
    to_string = getattr(value, "to_string", None)
    return to_string() if callable(to_string) else str(value)


class FakeModel(Runnable[object, object]):
    """Deterministic stand-in supporting LangChain structured and text calls."""

    def __init__(self, *, analyses=(), assessments=(), answers=()):
        self.responses = {
            "analysis": list(analyses),
            "assessment": list(assessments),
            "answer": list(answers),
        }
        self.prompts: dict[str, list[str]] = defaultdict(list)

    def _next(self, kind: str, value: object) -> Any:
        self.prompts[kind].append(prompt_text(value))
        if not self.responses[kind]:
            raise AssertionError(f"Unexpected {kind} model call")
        response = self.responses[kind].pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def invoke(self, input: object, config=None, **kwargs) -> AIMessage:
        response = self._next("answer", input)
        return AIMessage(content=response["answer"])

    def with_structured_output(self, schema, **kwargs):
        fields = set(schema.model_fields)
        if {"out_of_domain", "needs_clarification", "retrieval_query"} <= fields:
            kind = "analysis"
        elif {"is_sufficient", "refined_query"} <= fields:
            kind = "assessment"
        elif "answer" in fields:
            kind = "answer"
        else:
            raise AssertionError(f"Unexpected structured-output schema: {sorted(fields)}")

        def invoke(value):
            return schema.model_validate(self._next(kind, value))

        return RunnableLambda(invoke)


class FakeRetriever:
    """Captures the temporary retrieval boundary without a database."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[RetrievalRequest] = []

    def __call__(self, request: RetrievalRequest) -> list[RetrievedChunk]:
        assert isinstance(request, RetrievalRequest)
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("Unexpected retrieval call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def invoke(self, request: RetrievalRequest) -> list[RetrievedChunk]:
        return self(request)


class StructuredContentModel(FakeModel):
    """Return an answer using LangChain's structured content-block form."""

    def invoke(self, input: object, config=None, **kwargs) -> AIMessage:
        response = self._next("answer", input)
        return AIMessage(content=response["content"])


def chunk(text: str, source: str, **metadata) -> RetrievedChunk:
    return RetrievedChunk(text=text, source=source, metadata=metadata)


def test_answers_in_domain_question_with_sufficient_context_and_citations():
    model = FakeModel(
        analyses=[
            analysis(
                required_facts=["Apple FY2025 net sales"],
                retrieval_query="Apple FY2025 net sales annual report",
            )
        ],
        assessments=[assessment(True)],
        answers=[answer("Apple reported $416.2 billion in net sales [Apple FY2025 10-K p. 29].")],
    )
    evidence = chunk(
        "Total net sales were $416.161 billion in 2025.",
        "Apple FY2025 10-K p. 29",
        company="Apple",
        fiscal_year=2025,
        page=29,
    )
    retriever = FakeRetriever([evidence])

    result = BaselineAgent(model, retriever=retriever).invoke("What were Apple's net sales in FY2025?")

    assert result.status == "answered"
    assert result.answer == "Apple reported $416.2 billion in net sales [Apple FY2025 10-K p. 29]."
    assert list(result.citations) == ["Apple FY2025 10-K p. 29"]
    assert result.retrieval_attempts == 1
    assert retriever.requests == [
        RetrievalRequest(
            query="Apple FY2025 net sales annual report",
            required_facts=("Apple FY2025 net sales",),
            attempt=1,
        )
    ]
    final_prompt = model.prompts["answer"][0]
    assert evidence.text in final_prompt
    assert evidence.source in final_prompt


def test_extracts_text_from_structured_ai_message_content_blocks():
    expected = "Apple reported $416.2 billion in net sales [Apple FY2025 10-K p. 29]."
    model = StructuredContentModel(
        analyses=[
            analysis(
                required_facts=["Apple FY2025 net sales"],
                retrieval_query="Apple FY2025 net sales annual report",
            )
        ],
        assessments=[assessment(True)],
        answers=[{"content": [{"type": "text", "text": expected}]}],
    )
    retriever = FakeRetriever([chunk("Net sales were $416.161 billion.", "Apple FY2025 10-K p. 29")])

    result = BaselineAgent(model, retriever=retriever).invoke("What were Apple's FY2025 net sales?")

    assert result.answer == expected


def test_out_of_domain_question_returns_without_retrieval_or_answer_generation():
    model = FakeModel(analyses=[analysis(out_of_domain=True)])
    retriever = FakeRetriever()

    result = BaselineAgent(model, retriever=retriever).invoke("How do I make sourdough bread?")

    assert result.status == "out_of_domain"
    assert "financial report" in result.answer.lower()
    assert result.retrieval_attempts == 0
    assert list(result.citations) == []
    assert retriever.requests == []
    assert model.prompts["assessment"] == []
    assert model.prompts["answer"] == []


def test_missing_material_details_returns_specific_question_without_retrieval():
    model = FakeModel(
        analyses=[
            analysis(
                needs_clarification=True,
                clarification_question="Which company and fiscal year should I use?",
            )
        ]
    )
    retriever = FakeRetriever()

    result = BaselineAgent(model, retriever=retriever).invoke("What was revenue?")

    assert result.status == "needs_clarification"
    assert result.answer == "Which company and fiscal year should I use?"
    assert result.retrieval_attempts == 0
    assert list(result.citations) == []
    assert retriever.requests == []
    assert model.prompts["assessment"] == []
    assert model.prompts["answer"] == []


def test_refines_query_retries_and_accumulates_context_for_the_answer():
    first = chunk(
        "Revenue was $100 billion.",
        "ExampleCo FY2025 10-K p. 40",
        page=40,
    )
    second = chunk(
        "Revenue was $90 billion in the prior year.",
        "ExampleCo FY2025 10-K p. 41",
        page=41,
    )
    model = FakeModel(
        analyses=[
            analysis(
                required_facts=["FY2025 revenue", "FY2024 revenue"],
                retrieval_query="ExampleCo FY2025 and FY2024 revenue",
            )
        ],
        assessments=[
            assessment(False, "ExampleCo FY2025 annual report prior-year revenue comparison"),
            assessment(True),
        ],
        answers=[answer("Revenue increased from $90 billion to $100 billion [p. 40; p. 41].")],
    )
    retriever = FakeRetriever([first], [second])

    result = BaselineAgent(model, retriever=retriever).invoke("How did ExampleCo revenue change in FY2025?")

    assert [request.query for request in retriever.requests] == [
        "ExampleCo FY2025 and FY2024 revenue",
        "ExampleCo FY2025 annual report prior-year revenue comparison",
    ]
    assert [request.attempt for request in retriever.requests] == [1, 2]
    assert all(request.required_facts == ("FY2025 revenue", "FY2024 revenue") for request in retriever.requests)
    assert result.status == "answered"
    assert result.retrieval_attempts == 2
    assert list(result.citations) == [first.source, second.source]
    final_prompt = model.prompts["answer"][0]
    for item in (first, second):
        assert item.text in final_prompt
        assert item.source in final_prompt


def test_default_cap_stops_after_three_attempts_when_context_stays_insufficient():
    chunks = [chunk(f"Partial fact {index}", f"Report p. {index}") for index in range(1, 4)]
    model = FakeModel(
        analyses=[analysis(required_facts=["complete fact"], retrieval_query="initial query")],
        assessments=[
            assessment(False, "refined query 1"),
            assessment(False, "refined query 2"),
            assessment(False, "unused query after cap"),
        ],
        answers=[answer("The available reports do not contain enough evidence for a definitive answer.")],
    )
    retriever = FakeRetriever(*([item] for item in chunks))

    result = BaselineAgent(model, retriever=retriever).invoke("What is the complete fact?")

    assert [request.query for request in retriever.requests] == [
        "initial query",
        "refined query 1",
        "refined query 2",
    ]
    assert result.retrieval_attempts == 3
    assert result.status == "answered"
    assert list(result.citations) == [item.source for item in chunks]
    assert "not contain enough evidence" in result.answer
    assert "unused query after cap" not in [request.query for request in retriever.requests]


def test_configured_retrieval_cap_is_honored():
    model = FakeModel(
        analyses=[analysis(required_facts=["fact"], retrieval_query="query 1")],
        assessments=[
            assessment(False, "query 2"),
            assessment(False, "query 3 must not run"),
        ],
        answers=[answer("Evidence remains insufficient.")],
    )
    retriever = FakeRetriever(
        [chunk("Partial one", "Report p. 1")],
        [chunk("Partial two", "Report p. 2")],
    )

    result = BaselineAgent(model, retriever=retriever, max_retrieval_attempts=2).invoke("Find fact")

    assert [request.attempt for request in retriever.requests] == [1, 2]
    assert [request.query for request in retriever.requests] == ["query 1", "query 2"]
    assert result.retrieval_attempts == 2


@pytest.mark.parametrize("question", ["", " ", "\n\t"])
def test_blank_questions_are_rejected_before_model_or_retrieval(question):
    model = FakeModel()
    retriever = FakeRetriever()

    with pytest.raises(ValueError, match="question"):
        BaselineAgent(model, retriever=retriever).invoke(question)

    assert dict(model.prompts) == {}
    assert retriever.requests == []


@pytest.mark.parametrize("question", [None, 123, object()])
def test_non_string_questions_are_rejected(question):
    with pytest.raises(TypeError, match="question"):
        BaselineAgent(FakeModel(), retriever=FakeRetriever()).invoke(question)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "3"])
def test_invalid_retrieval_limits_are_rejected(limit):
    with pytest.raises((TypeError, ValueError), match="retrieval|attempt"):
        BaselineAgent(FakeModel(), retriever=FakeRetriever(), max_retrieval_attempts=limit)


def test_retriever_failures_propagate_instead_of_producing_an_unsupported_answer():
    model = FakeModel(analyses=[analysis(required_facts=["fact"], retrieval_query="query")])
    retriever = FakeRetriever(RuntimeError("vector store unavailable"))

    with pytest.raises(RuntimeError, match="vector store unavailable"):
        BaselineAgent(model, retriever=retriever).invoke("Find the fact")

    assert len(retriever.requests) == 1
    assert model.prompts["answer"] == []
