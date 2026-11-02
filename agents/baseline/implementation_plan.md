# Baseline agent implementation plan

## Workflow

Implement `baseline.png` as a small LangGraph state machine:

1. Analyze the question for domain fit, missing details, required facts, explicit supported companies, and an initial retrieval query.
2. Discover companies and relevant period intervals with traced database tools, then reanalyze verified scope.
3. Return a deterministic out-of-domain response when the question is not about the provided financial reports.
4. Return one specific clarification question when material details are missing.
5. Call the injected retrieval tool separately per selected company and accumulate evidence with source metadata.
6. Ask the model whether the context is sufficient; when it is not, refine the query and retry retrieval.
7. Stop after at most three retrieval rounds and formulate an evidence-bound answer.

## Public API

- `BaselineAgent(model, retriever=placeholder_retriever, max_retrieval_attempts=3, coverage=None)` builds the graph once.
- `BaselineAgent.invoke(question)` validates input, invokes the graph, and returns a typed result.
- `RetrievalRequest` requires a canonical company literal, query, required facts, and one-based round number.
- `RetrievedChunk` preserves evidence and citation metadata from company-specific vector tables in `agents.tools`.

## Design constraints

- Use LangChain prompt templates and structured model outputs for decisions.
- Make graph nodes and routing methods explicit so the workflow reads like the architecture diagram.
- Keep the retriever synchronous and injectable; the default placeholder returns no chunks.
- Preserve citation metadata in retrieved chunks and require source labels in generated answers.
- Require explicit company selection, search only its mapped table, and preserve nested structured-tool/retriever traces.
- Propagate model and retriever failures rather than hiding incomplete runs.

## Test-first coverage

- Answer an in-domain question with sufficient context.
- Reject an out-of-domain question without retrieval.
- Request missing details without retrieval.
- Retry with a refined query and accumulate context.
- Stop at the configured retrieval cap when evidence remains insufficient.
- Reject blank questions and invalid retry limits.

- Discover fresh database companies and gapped quarter intervals; preserve annual filing availability separately.
- Verify discovery precedes scope decisions and nested tool traces belong to the complete invocation.
- Require actual discovery calls and relevant company arguments in Promptfoo trajectories.
