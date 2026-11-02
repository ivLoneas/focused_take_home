# Baseline agent implementation plan

## Workflow

Implement `baseline.png` as a small LangGraph state machine:

1. Analyze the question for domain fit, missing details, required facts, and an initial retrieval query.
2. Return a deterministic out-of-domain response when the question is not about the provided financial reports.
3. Return one specific clarification question when material details are missing.
4. Call an injected retriever and accumulate evidence with source metadata.
5. Ask the model whether the context is sufficient; when it is not, refine the query and retry retrieval.
6. Stop after at most three retrieval attempts and formulate an evidence-bound answer.

## Public API

- `BaselineAgent(model, retriever=placeholder_retriever, max_retrieval_attempts=3)` builds the graph once.
- `BaselineAgent.invoke(question)` validates input, invokes the graph, and returns a typed result.
- `RetrievalRequest` and `RetrievedChunk` form the temporary boundary to the unfinished retrieval layer.

## Design constraints

- Use LangChain prompt templates and structured model outputs for decisions.
- Make graph nodes and routing methods explicit so the workflow reads like the architecture diagram.
- Keep the retriever synchronous and injectable; the default placeholder returns no chunks.
- Preserve citation metadata in retrieved chunks and require source labels in generated answers.
- Propagate model and retriever failures rather than hiding incomplete runs.

## Test-first coverage

- Answer an in-domain question with sufficient context.
- Reject an out-of-domain question without retrieval.
- Request missing details without retrieval.
- Retry with a refined query and accumulate context.
- Stop at the configured retrieval cap when evidence remains insufficient.
- Reject blank questions and invalid retry limits.
