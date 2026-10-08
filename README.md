# Production RAG

## Explanation of the project

> I built a document question-answering application for operational knowledge. Users upload PDF, TXT or Markdown files. The system extracts their text, splits it into smaller passages and stores the passages with searchable vectors and document details. For a question, it combines semantic and keyword search, merges the results, reranks them and selects a limited amount of evidence. It can rewrite a weak search and retry before generating an answer.
>
> Automatic routing starts simple factual lookups on Llama 1B and uses Llama 3B for comparisons, summaries or larger evidence. A failed small-model response can get one larger-model fallback. Answers include source passages you can inspect; missing evidence or invalid output can produce a refusal. The workspace also supports document versions, duplicate-upload detection, filters, deletion, separate tenant access and cached answers. Browser demo tools link the database/SQL viewer, API explorer and LangSmith, and show health, metrics and query details.
>
> Everything runs locally except enabled LangSmith monitoring, which receives prompts, retrieved evidence and responses so I can inspect model choices, fallback, timing, errors and reported tokens. Health checks, metrics, automated tests and retrieval evaluation help me check whether the application works.

**RAG** means retrieving evidence before generating an answer; uploading does not train the models. Routing uses explicit rules, not a trained classifier. Citation IDs are validated, but I still check whether each passage supports its claim. The demo policies are fictional.

### What each part of my local setup does

- **FastAPI and Python:** Serve the website and handle authentication, uploads, questions, deletion and metrics.
- **HTML, CSS and JavaScript:** Provide the upload/library interface, filters, answers, citations and model activity panel.
- **Docker Compose:** Starts the API, database and viewer together and avoids native Windows dependency issues.
- **PostgreSQL:** Stores extracted text, metadata, versions and tenant records; Docker volumes preserve them across restarts.
- **pgvector:** Stores and searches document vectors; PostgreSQL full-text search supplies keyword matches.
- **Ollama:** Runs the local generation and embedding models without a hosted-model API key.
- **Llama 1B and 3B:** Provide two answer tiers suitable for this laptop's limited RAM; current inference uses CPU.
- **Nomic embeddings:** Convert document passages and questions into 768-dimensional vectors for similarity search.
- **Fusion and the cross-encoder reranker:** Merge retrieval rankings and move the most relevant passages first.
- **LangChain:** Connects model adapters and text-splitting tools to the application.
- **LangGraph:** Coordinates retrieval, evidence selection, bounded rewriting, model routing and answering.
- **LangSmith:** Records graph/model activity and, with full tracing enabled, prompts, evidence and responses.
- **Adminer:** Lets me inspect PostgreSQL tables in a browser.
- **uv and the lockfile:** Install and run consistent Python dependencies; scripts and CI run tests and evaluation.
- **.env:** Keeps application/database/provider keys and settings private; `.env.example` is the single public template.

Application keys scope data to workspaces; request/upload/context limits bound resource use. Identical questions can use a five-minute cache, and document changes prevent stale reuse. Original files are not archived. Gemini/OpenAI are optional providers; SQLite/Chroma and fake-model mode support development. The current setup uses one worker and does not include user accounts, OCR, streaming or automatic document syncing. Routing may need fallback and is not guaranteed to make answers faster.

## Features

| Feature | What it does | Implementation |
| --- | --- | --- |
| Document ingestion | Reads text-based PDF, UTF-8 TXT and Markdown; preserves metadata and chunks text | documents.py |
| Hybrid retrieval | Finds semantic matches and exact keyword matches in tenant-scoped documents | storage.py |
| Fusion and reranking | Combines ranked lists, then scores question-passage pairs | pipeline.py |
| Grounded answers | Requests supported claims with source IDs; attaches stored source excerpts | pipeline.py |
| Refusal and rewriting | Refuses missing/invalid evidence and conditionally retries retrieval | pipeline.py |
| Automatic local routing | Starts factual lookups on 1B and uses 3B for synthesis or complex context | routing.py |
| Model activity | Shows initial route, final model, fallback and cache status | app.js |
| Document lifecycle | Deduplication, categories, version filters and browser deletion | storage.py |
| Tenant isolation | Application keys identify workspaces and restrict document access | main.py |
| Caching and limits | Reuses identical queries and bounds requests, uploads and context | main.py, config.py |
| Persistent local storage | PostgreSQL text, metadata and vectors survive container restarts | [compose.yaml](compose.yaml) |
| Monitoring | LangSmith execution traces, health endpoints and Prometheus metrics | main.py |
| Evaluation | Retrieval Recall@K/MRR, automated regressions and real-model smoke checks | [scripts](scripts), [tests](tests) |

## Demo

Use the existing private `.env` and installed models. Full tracing/routing are already enabled. Keep Docker Desktop and Ollama open; do not start a second Ollama server. These instructions do not start services until you run them.

### 1. Start and connect

Run in PowerShell:

```powershell
Set-Location 'C:/Users/riyan/Desktop/Projects and Research Papers/Production RAG/production-rag'
docker compose --profile tools up -d --build
docker compose --profile tools ps
```

Wait until API/PostgreSQL are **healthy** and Adminer is **Up**, then run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
uv run --frozen python -c "from app.config import Settings; print(next(iter(Settings().api_keys)))" | Set-Clipboard
```

Expect `ready / ollama / postgres`. Open **http://127.0.0.1:8000**, paste the copied application key and click **Connect**. Ctrl+F5 refreshes old UI assets. The LangSmith key is not the website key; refreshing the tab clears the website key.

### 2. Upload and show ingestion

Upload samples/model-routing-demo.txt, **version** `4`, **category** `demo`. Wait for confirmation. Confirm query filters: category `demo`, filename `model-routing-demo.txt`, version `4`.

The expanded fictional handbook covers withdrawal deadlines, security holds, verification, deposits, complaints, outages, privacy and handovers. Its 19 named sections become separate searchable chunks. In the library, select **Ask about this**, then use the example buttons beside the question box. A factual lookup can cite one passage; the comparison asks for several policies and should cite different sections. More stored chunks does not mean every answer must cite all of them.

Show the library, Refresh library and Ask about this. Re-upload the identical filename/version to show duplicate detection. PDF/Markdown support can be shown by uploading a small text-based file and asking a fact from it.

Latest means the most recently uploaded version, not the largest version number. Version `4` preserves the previous short sample as history. If you have already used that version for different content, choose a new unused version and filter to it.

### 3. Ask and inspect the answers

| Input | What to show |
| --- | --- |
| **How many minutes does support have to acknowledge a withdrawal complaint?** | 15 minutes; initial 1B route, actual final model and any 3B fallback |
| **What happens if a standard withdrawal review exceeds 24 hours?** | Escalation to payments operations; retrieval of an exact policy detail |
| **How many minutes after a successful provider deposit is missing from account activity should support escalate to payments operations?** | 60 minutes; a factual lookup from a different chunk |
| **What is the company policy on flying to Mars?** | Insufficient evidence without citations |
| Repeat the first question with identical filters within five minutes | Cache hit; no fresh model generation |

For the larger-model example, ask:

> Compare standard and security-flagged withdrawal handling. State the standard review target after verification and what support does if review exceeds 24 hours. Who can clear a security hold, and what must support not do? State the complaint acknowledgement and progress-update deadlines. Cite the relevant sections.

Show the **3B** route and citations from **STANDARD WITHDRAWAL REVIEW**, **SECURITY FLAGGED WITHDRAWAL** and **WITHDRAWAL COMPLAINT ACKNOWLEDGEMENT**. Check 24-hour standard review after verification, overdue escalation to payments operations, security clearance before release, no verification bypass, 15-minute acknowledgement and 2-hour progress updates during staffed hours.

For a second comparison across different chunks, ask:

> Compare platform outage triage and outage customer updates: how many independent reports in what time window trigger escalation, and how often are customer status updates published during a confirmed outage? Cite both sections.

Expect 3 reports in 10 minutes, updates every 30 minutes, a **3B** route and citations from both outage sections. Citation count depends on the claims the model produces; inspect the excerpts rather than counting labels alone.

Expand citations to inspect filename, version, page/section and excerpt. Show Copy answer, Model activity and Inspect query request and response for the API JSON. The factual example can fall back to 3B; do not promise a 1B-only answer. Set category to `nonexistent-demo-category` and ask a new question to show excluded evidence, then restore `demo`.

### 4. Show LangSmith

Click **View traces**, sign in at [LangSmith](https://smith.langchain.com), and open **production-rag**. Select a fresh `rag-request`, expand `rag-question`, and show:

- **Graph steps:** Retrieval, selected evidence and conditional search rewriting/retries.
- **route_model metadata:** Initial model, tier, reason and policy.
- **answer / generate-answer:** Final model, fallback and timing.
- **Nested model Inputs/Outputs:** System prompt, question, retrieved evidence and generated response.
- **Request/model details:** Cache hit, refusal reason, errors and reported token usage.

Cached requests have no new generation span. Rephrase a question for a fresh model trace; delivery can take a few seconds. Rewriting is conditional, so it may not appear on every question. Upload/parsing/SQL do not have dedicated detailed spans, and local electricity cost/private model reasoning are not shown.

### 5. Show everything from the website

Use **Demo tools / Health & metrics** in the sidebar:

| Website control | What to demonstrate |
| --- | --- |
| **Check health** | Process and database/model readiness responses, displayed on the page |
| **Load metrics** | API request counts and latency buckets; uses the connected app key |
| **Database & SQL** | Opens Adminer in a browser tab: PostgreSQL, server `postgres`, username/database `rag`, password from `.env` -&gt; `POSTGRES_PASSWORD` |
| **API explorer** | Opens `/docs` in a browser tab; Authorize with the app key and try list/upload/query/delete/metrics endpoints |
| **LangSmith traces** | Opens the tracing service in a browser tab; sign in and choose `production-rag` |
| **Query request and response** | Expand under an answer to inspect submitted filters and returned answer/citations/routing JSON |
| **Version filter / Ask this version** | Upload a disposable TXT, change one fact, upload a new version, then query each version from the page |
| **Delete** in the library | Confirm deletion of the disposable version; verify the library updates |

In Adminer, show **documents**, **chunks** and **rag_config**. Open **SQL command** and run a read-only example:

```sql
SELECT filename, version, category, active FROM documents ORDER BY created_at DESC;
SELECT COUNT(*) AS stored_passages FROM chunks;
```

Keep the main trading sample intact. Database/API/LangSmith are separate browser tools launched from the main page; health, metrics, historical queries and deletion work in the workspace itself. Separate-tenant isolation is covered by automated tests.

### 6. Show verification and evaluation

```powershell
uv run --frozen python -m scripts.verify_running
uv run --frozen python -m scripts.check_docker
```

The live verifier checks both samples: auth/assets, routing, answers, summaries, refusal, citations, cache, library and metrics. It pins fixture versions and writes `data/running-stack-verification.json`; use `--sample trading` for only the trading fixture.

The Docker checker runs tests, lint, formatting and sample retrieval evaluation using a separate `rag_test` database. Show the test result and **Recall@K** (relevant passages found) / **MRR** (how early they appear). These are sample checks, not proof of perfect answers. For your own labeled evaluation, see export_chunks.py and evaluate.py.

### 7. Show persistence and stop

```powershell
docker compose --profile tools restart
```

Wait for readiness, reconnect and show the library still exists. Database volumes persist; the in-memory cache clears.

```powershell
docker compose --profile tools stop
ollama stop llama3.2:1b
ollama stop llama3.2:3b
ollama stop nomic-embed-text:latest
```

Do not use `down -v` for normal shutdown; it deletes volumes.

### If something fails

```powershell
docker compose logs --tail 80 api
ollama list
```

Connection closed during startup: wait for healthy. Missing models: pull the missing `llama3.2:1b`, `llama3.2:3b` or `nomic-embed-text:latest` tag. Empty trace content: check `LANGSMITH_TRACING=true` and `TRACE_CONTENT=true` in private `.env`, then recreate API with `docker compose up -d --force-recreate api`. Full tracing sends prompts/evidence/responses to LangSmith. Preserve existing secrets; `.env.example` contains only placeholders.
