**FAANG Financial Analyst Assistant**

![FAANG Financial Analyst Assistant demo](focused-demo.gif)

# TLDR

An AI assistant helping with public financial reports from FAANG companies.

This is a LangChain-based agentic AI workflow enhanced with RAG retrieval.

Development lifecycle: collect data → write evals → build a baseline workflow → evaluate, collect metrics, and analyze errors → refine the workflow → evaluate again.

Due to the limitations of a take-home assignment, including a very limited API token budget, the active dataset consists of 100 PDFs containing the latest financial reports and supporting materials from the five companies forming FAANG.

The project includes an ETL pipeline for processing data with Docling, including PDF conversion, image annotations, and table extraction. A RAG vector database is then built using hierarchy-aware chunking.

The evals consist of 114 questions that are handcrafted and synthetically generated. They cover retrieval accuracy, out-of-domain handling, image- and table-related questions, and complex scenarios. Evaluations are conducted with Promptfoo.

The baseline agent is written in LangChain, uses `gpt-6.1-terra`, and follows a straightforward workflow:

![focused-baseline.png](focused-baseline.png)

Evaluations showed that it performs well, achieving a **95.6% pass rate (109/114)**. Error analysis shows remaining gaps in handling incomplete retrieved evidence and producing complete answers. Another source of error is image and chart interpretation.

**Iterating.**

Given the high pass rate on the main eval suite, we concluded that the baseline is capable of solving the task, so we could use smaller models for parts of the workflow. The goal was to make inference faster and cheaper at the same time.

Agent v2 retains the general architecture. The main differences are its use of Jev, an NLP model that helps with out-of-domain handling, and a smaller model, `gpt-6-luna`, for planning and evidence assessment. It still uses `gpt-6.1-terra` for answers.

New evals show the same **95.6% pass rate**, with mean response time reduced from **9.52 to 6.97 seconds** and estimated runtime API cost reduced by **53%**, excluding evaluation grading.

---

## Prerequisites

| Requirement | Used for |
| --- | --- |
| Python 3.14 and `uv` | Installing Python dependencies and running the API |
| Docker with Docker Compose v2, with the Docker engine running | PostgreSQL and pgvector; Compose must support `up --wait` |
| Node.js 22.22 or later and npm | Installing and running the pinned Promptfoo evaluation tools |
| Bash and `make` | Running the commands below on macOS or Linux; on Windows, use WSL |
| A web browser | Using the app and viewing evaluation reports |

The frontend is static HTML, CSS, and JavaScript; it does not need a Node.js build. PostgreSQL and pgvector run in Docker, so no local PostgreSQL installation is required. The default ports are **5173** for the app, **8000** for the API, **55432** for PostgreSQL, and **15500** for the report viewer.

Run `make setup` to install Python and evaluation dependencies and create `.env` from [.env.example](.env.example). An existing `.env` is preserved. Add these credentials before asking questions or running fresh evals:

| Setting | Requirement |
| --- | --- |
| `OPENAI_API_KEY` | Required for both agents, query embeddings, and fresh evaluation grading. The configured models are `gpt-6.1-terra`, `gpt-6-luna`, and `text-embedding-3-small`. |
| `TYPESAFE_API_KEY` | Required for Agent v2, the default in the app, and paired evals. Baseline-only use does not require it. |
| `DATABASE_URL` | Defaults to `postgresql://rag:rag_local@localhost:55432/rag` for the included Docker database. |
| `LANGSMITH_API_KEY` | Required only when `LANGSMITH_TRACING=true`. Also set `LANGSMITH_PROJECT` and the appropriate regional `LANGSMITH_ENDPOINT`. Tracing is disabled by default. |

Opening the saved evaluation report requires Node.js, npm, `make`, and Bash. For report-only use, install Promptfoo with `npm --prefix evals ci`, then run `make report`. This does not require Python, Docker, or API keys and does not run new model calls.

## Quick start

From the project root:

```sh
make setup
# Edit .env and add your API keys.
make db-restore  # Once, for an empty local database.
make app
```

`make db-restore` starts PostgreSQL, waits until it is healthy, and restores the included [retrieval database](data/dumps/README.md) in one transaction. If you already have the populated retrieval database, skip this step. It does not replace existing tables.

`make app` starts PostgreSQL, the API, and the frontend in one terminal. Open [http://localhost:5173](http://localhost:5173). The API health check is at [http://localhost:8000/health](http://localhost:8000/health), and API documentation is at [http://localhost:8000/docs](http://localhost:8000/docs). Press **Ctrl-C** to stop the API and frontend; PostgreSQL and its data remain available.

To view the latest committed paired evaluation, run:

```sh
make report
```

Open the report link printed in the terminal. This loads `reports/model-refresh-2026-11-03/full.json` into a local Promptfoo viewer on port 15500. Viewer data is stored under `.cache/promptfoo/`; the source report is unchanged. Press **Ctrl-C** to stop the viewer. To open another saved export or use a different port:

```sh
make report REPORT=reports/baseline-2026-11-02-v2/promptfoo.json REPORT_PORT=15501
```

To run a fresh comparison of the baseline and Agent v2 on all 114 questions:

```sh
make eval
make report REPORT=reports/comparison.json
```

Fresh evals use your configured API keys and incur model and grading costs. Results are written to `reports/comparison.json`. See the [evaluation workflow](evals/README.md) for individual suites, and run `make help` for all commands.

---

**Data**

Publicly accessible financial-report PDFs from FAANG companies were used as a dataset to get information from and run retrieval on. The active dataset contains 100 documents, covering issuer fiscal periods from FY2024 to Q3 FY2026, depending on the company. FY2026 is incomplete.

Documents include tables and images that make retrieval a non-trivial task.

Because of the size of the dataset, it does not represent a production retrieval environment: production datasets are much bigger.

Used dataset lists 20 newest reports per company: **3,503 pages**, approximately **91.6 MB of PDFs**, and **20,274 indexed chunks**.

| Company | Documents | Pages | Indexed chunks | Retained fiscal periods |
| --- | ---: | ---: | ---: | --- |
| Alphabet | 20 | 587 | 3,353 | FY2025 Q1–FY2026 Q3 |
| Amazon | 20 | 1,220 | 5,829 | FY2025 Q1–FY2026 Q3 |
| Apple | 20 | 490 | 2,779 | FY2024 Q2–FY2026 Q3 |
| Meta | 20 | 736 | 5,344 | FY2025 Q4–FY2026 Q3 |
| Netflix | 20 | 470 | 2,969 | FY2024 Q3–FY2026 Q3 |

To save disk space for you and GitHub, the source PDFs are not committed to the repository. There is a [script for downloading them](scripts/download_reports.py).

---

**Data preparation and Retrieval**

This system uses vector similarity RAG with hierarchy-aware chunking and image annotation.

Docling was used for PDF conversion, table extraction, and heading reconstruction, with `gpt-6-luna` annotating images. 
Chunks use a 1,000-character budget and 200-character overlap within sections. 
Tables retain column headers when split, and image descriptions retain their source pages. `text-embedding-3-small` supplies 1,536-dimensional embeddings.

The prepared database lets you skip ETL. To rebuild it from the pinned source PDFs, follow the [ETL instructions](etl/AGENTS.md#docker-operation). The [source-data contract](data/AGENTS.md) and [dataset README](data/raw/README.md) describe the archive and active corpus.

PostgreSQL's pgvector was used as the vector database. This decision was made mostly for simplicity. First, retrieval is relatively simple on 100 documents, and optimizing the vector database would not give much benefit. Second, I anticipated the need for PostgreSQL for the app demonstration, so I decided it was the easiest option.


We can leverage the structure of our dataset: each company's reports can be retrieved independently. Therefore, instead of searching across one index, we have five company-specific tables, each with its own vector index. A retrieval tool requires a company name as a mandatory parameter. Comparisons retrieve separately for each company.

We also maintain chunk-document-page references. When generating an answer, we supply the agent with source data that it passes to the user. This gives someone who does not trust AI a way to double-check answers themselves. Exact-format answers keep source references in the response metadata.

(We could also highlight the specific line in the PDF, making the UI really nice, but this is outside the scope of this take-home assignment.)


---

**Evals**

Before building an agent, we need to formalize the task it is going to solve. 
Therefore, evaluation tests are written before the baseline solution. 
Evals should cover a variety of possible examples, which makes them hard to get right in one shot.
The current set includes these 11 topics. For each topic, one question was handcrafted and then used as an example 
for AI to generate synthetic data:

1. Factual questions. Checking basic capabilities and RAG quality
2. Tool usage checks
3. Out-of-domain handling
4. Multiple-company questions (e.g., "Compare Apple's and Amazon's net income"). Checking that our database split works correctly
5. Complex questions requiring multiple retrievals ("In which year did Google have higher income?")
6. Handling in-domain questions with no available data
7. Extra calculations (net income in millions, while in the database it is in billions)
8. Ambiguous questions requiring more details ("Which company performs better?" We want the agent to clarify which metric.)
9. Image recognition
10. Table extraction
11. Formatting

There are 114 cases. A strict pass requires all applicable response-validity, workflow, answer-quality, and formatting checks to pass. Answer quality uses an LLM judge; the other checks are deterministic. A separate ten-case behavior suite tests bounded interpretations, comparisons, and exact formatting. See the [evaluation workflow](evals/README.md).

---

**Agent Baseline**

![focused-baseline.png](focused-baseline.png)

For a baseline, we built a simple workflow with basic common-sense checks first (out-of-domain handling and requests for specific details).
We also provide tools for retrieval. Tool design is really important to make an agent effective.
For this task we have:

- List companies: `() -> companies`. Returns a list of companies in the database. While working with FAANG, we can embed it in the prompt; when the database grows, it is better to retrieve it when needed. It also helps distinguish unavailable company coverage from out-of-domain requests.
- Company coverage: `(company) -> time periods`. The same logic as above: retrieving specific information and using it only when needed. Helps with missing-data handling.
- Retrieve: `(company, question) -> document chunks`. The retrieval itself. The agent formulates the retrieval query.

The baseline uses `gpt-6.1-terra` for all model calls. Evaluations retrieve up to eight chunks per company per round, with at most three retrieval rounds.

---

**Performance and error analysis**

After evaluating the baseline agent, we got a **73.7% pass rate (84/114)**, 
with 29 assertion failures and one runtime error. Main sources of error included formatting, unnecessary 
clarifications, and image recognition. All ten formatting cases failed the format check, and only five of ten image 
cases passed.

While formatting and clarification behavior can be improved by adjusting prompts that were not aligned with the desired behavior, image recognition may also be a data-processing or retrieval issue.

After prompt adjustments and a model refresh, the baseline pass rate reached **95.6% (109/114)** in **`eval-Woy-2026-11-03T15:08:01`**. The remaining failures were two tool-usage cases and three image cases. Questions and grading rules also changed between runs, so this comparison does not isolate the effect of prompt adjustments.

Some costs, token usage, and response times are shown here:

| Metric | Starting baseline, 2 November | Latest baseline, 3 November |
| --- | ---: | ---: |
| Strict pass rate | 84/114 (73.7%) | 109/114 (95.6%) |
| Runtime errors | 1 | 0 |
| Mean response time | 33.83 s | 9.52 s |
| Median response time | 31.49 s | 9.12 s |
| p95 response time | 68.63 s | 15.72 s |
| Median model tokens per question | 13,900 | 14,098 |
| p95 model tokens per question | 35,651 | 40,237 |
| Mean estimated runtime API cost per question | $0.00846 | $0.01131 |
| Median cumulative retrieval time | 0.391 s | 0.365 s |
| p95 cumulative retrieval time | 1.185 s | 1.257 s |

Latency and token statistics use completed responses: 113 in the starting run and 114 in the latest run. 
Retrieval times sum retrieval calls per question, including query embedding, 
and include only questions that retrieved evidence: 70 and 81 respectively. 
Model tokens exclude query embeddings and grading. 
Runtime cost includes model calls and query embeddings; the starting run also includes recovered usage from its failed invocation. Costs use the dated rates recorded for each run and exclude grading and infrastructure.

Sources: [starting evaluation](reports/baseline-2026-11-02-v2.md), [latest evaluation](reports/model-refresh-2026-11-03/report.md), and [latest cost estimates](reports/model-refresh-2026-11-03/cost-comparison.md).

Such a result suggests that the main eval suite is approaching saturation, although it does not establish coverage of all possible cases. The separate behavior suite still passed only 6/10 baseline cases. What we can do, though, is use smaller models for parts of the workflow. By simplifying the workflow or optimizing calls, we can make it faster and cheaper.

---

**Agent V2**

![focused-v2.png](focused-v2.png)

Given the high main-suite pass rate, a focus was on reducing costs and making the workflow faster.
Out-of-domain handling can be done using Jev instead of a generative LLM. A separate domain-only benchmark measured mean Jev HTTP round-trip time at **177.5 ms**, compared with **1.71 s for `gpt-5-mini`** and **2.20 s for `gpt-5-nano`**. All three classified **32/32 requests** correctly, using 16 questions repeated twice.

This was approximately **9.7× faster than mini** and **12.4× faster than nano**, 
while Jev also cost less under the benchmark's recorded pricing. 
See the [benchmark results](reports/agent-v2-refinement-2026-11-03/domain-benchmark-summary.json).

Jev is currently used only for domain screening.

Planning and evidence assessment were moved to `gpt-6-luna`; answers still use `gpt-6.1-terra`. After running evals, 
the pass rate stayed the same, while mean time to answer was **27% lower (1.37× faster)** and estimated runtime API cost was **53% lower**.
You can see the comparison below:

| Metric | Baseline | Agent v2 |
| --- | ---: | ---: |
| Strict pass rate | 109/114 (95.6%) | 109/114 (95.6%) |
| Separate behavior-suite passes | 6/10 | 7/10 |
| Mean response time | 9.52 s | 6.97 s |
| Median response time | 9.12 s | 6.89 s |
| p95 response time | 15.72 s | 12.56 s |
| Median model tokens per question | 14,098 | 11,463 |
| p95 model tokens per question | 40,237 | 27,059 |
| Mean estimated runtime API cost per question | $0.01131 | $0.00531 |
| Total estimated runtime API cost, 114 questions | $1.2895 | $0.6058 |
| Median cumulative retrieval time | 0.365 s | 0.364 s |
| p95 cumulative retrieval time | 1.257 s | 1.362 s |

Both agents were evaluated on the same questions and assertions. V2 tokens and runtime costs include Jev.
The same timing and cost definitions apply as above. 
These are single-run results; the speed and cost differences reflect the complete configured workflows,
including model choices and reasoning settings.


---

**Tracing**

Langsmith handles tracing and threads. In a real app we would configure threads in similar system as
OpenTelemetry threads: same thread for a user session. See some examples here:

- https://eu.smith.langchain.com/public/d55ab27b-b40d-4144-878f-4e95b87262e3/t
- https://eu.smith.langchain.com/public/69bfba2a-4555-4f81-b86f-57ddcbbab990/t
- https://eu.smith.langchain.com/public/e13d7330-2f30-48fe-830d-8386925ea9f3/t


---

**TODO**

- Image retrieval quality
- Using Jev was a positive experience. We may try to use it for identifying whether we have enough information.

What was Amazon's net income in each quarter in 2025?