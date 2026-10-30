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

see `data` directory. `data/raw` contains downloaded pdfs of reports. These is ground truth dataset we are only working it. No additional data scraping or data sourcing is required for the sake of simplicity and limitations of take-home excersize.


**Daga processing**

It has to be extracted to text using Pdf2md hierarchy aware tool. Than chancked and vectorized in postgres pgvector.

**PDF2vectors**

the following ETL workflow will be used for baseline. 
Extract hierarchical data from pdf using docling as it returns good results 
according to this paper: https://arxiv.org/pdf/2604.04948
If it does not work by default with images we really need to make textual annotations to make them trackable in rag. 

Then chunk it up to 1000 characters with overlap 200 (industry standard + used in the paper above). 
Then Generate embedding using openai embedding model.

Store in pg vector. 

**Baseline architecture** 
See `baseline.png` for more details. 
Agent should be implemented using langchain. 

** Tracing and trajectories** 
a solution should be able to track agent usage. 