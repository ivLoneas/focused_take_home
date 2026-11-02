This is a take home project designed to build a RAG agentic workflow. 

**Project directory**
- `data/` contains relevant datasets for rag agent
- `etl/` is data processing and vector db
- `evals/` contains promptfoo evals and testing
- `agent/` is agentic workflow
- `baseline.png` is baseline agentic architecture

**Task description** 

Build an assistant for answering questions about F100 companies public finantial reports. 

**Architecture**

It is a rag based system with a simple agentic workflow. We focus on eval driven development, therefore evaluations, metrics and tests are crusial for the task. 

**Plan**

1. Write evaluation and test examples using promptfoo. 
2. Build a baseline model
3. Build simple metrics, traces and trajectories system
4. Run evals, evaluate performance and conduct error-analysis looking for ways to improve it
5. Iterate the agent, refine architectural decisions and evaluate it. Report performance imporvements
6. Wrap up in a simple ui for demonstration. 

**Tech stack**

- An agent must be written using langchain and langraph if required. 
- Evals are running through promptfoo. 
- LLM models use openai as a baseline. As a follow up we can run evals for different models. 
- Postgress with pgvector for vector db for simplicity. 
- Postgress as main database
- Python 3.14, docker. 

**Data**

See `data/AGENTS.md` for the source-data contract. `data/raw` is the complete immutable ground-truth archive: 799 downloaded PDFs from 15 companies covering fiscal years 2022 to 2026 where available. Year 2026 is incomplete. No additional data scraping or sourcing is part of ETL, retrieval, or evaluation.

`data/active_manifest.csv` pins the baseline retrieval and positive-evaluation corpus to 100 PDFs: the newest 20 reports for each of Alphabet, Amazon, Apple, Meta, and Netflix. Code must not infer a different active corpus from the contents of `data/raw`.

**Daga processing**

It has to be extracted to text using Pdf2md hierarchy aware tool. Than chunked and vectorized in postgres pgvector.

**Baseline architecture** 
See `baseline.png` for more details. 
Agent should be implemented using langchain. 

**Tracing and trajectories** 

All agents must use LangSmith tracing. A trace must cover the complete agent invocation and preserve nested model calls,
tool calls, and retrievals so their inputs, outputs, errors, latency, token usage, and execution order can be monitored.
Implement custom model, tool, and retrieval boundaries with LangChain/LangGraph traceable interfaces (or explicit
LangSmith instrumentation) rather than untraced calls. Keep credentials out of trace metadata and fail clearly when
tracing is enabled without valid LangSmith configuration.

**Code style** 

Follow the KISS Principle. DO not add extra abstractions when it is not necessary 
Follow Testing driven development when writing code and implementing systems: write tests first using pytest library. 
Test should cover happy paths, edge cases, invalid inputs. Then implement a system. Test sets should be written by 
an independent subagent. 
