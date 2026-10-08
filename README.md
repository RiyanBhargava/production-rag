# Production RAG

## Explain the project before the demo

> I built a document question-answering application for operational knowledge. Users upload PDF, TXT or Markdown files. The system extracts their text, splits it into smaller passages and stores the passages with searchable vectors and document details. For a question, it combines semantic and keyword search, merges the results, reranks them and selects a limited amount of evidence. It can rewrite a weak search and retry before generating an answer.
>
> Automatic routing starts simple factual lookups on Llama 1B and uses Llama 3B for comparisons, summaries or larger evidence. A failed small-model response can get one larger-model fallback. Answers include source passages you can inspect; missing evidence or invalid output can produce a refusal. The workspace also supports document versions, duplicate-upload detection, filters, deletion, separate tenant access and cached answers.
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

## Features to introduce before the demo

| Feature | What it does | Implementation |
|---|---|---|
| Document ingestion | Reads text-based PDF, UTF-8 TXT and Markdown; preserves metadata and chunks text | [documents.py](app/documents.py) |
| Hybrid retrieval | Finds semantic matches and exact keyword matches in tenant-scoped documents | [storage.py](app/storage.py) |
| Fusion and reranking | Combines ranked lists, then scores question-passage pairs | [pipeline.py](app/pipeline.py) |
| Grounded answers | Requests supported claims with source IDs; attaches stored source excerpts | [pipeline.py](app/pipeline.py) |
| Refusal and rewriting | Refuses missing/invalid evidence and conditionally retries retrieval | [pipeline.py](app/pipeline.py) |
| Automatic local routing | Starts factual lookups on 1B and uses 3B for synthesis or complex context | [routing.py](app/routing.py) |
| Model activity | Shows initial route, final model, fallback and cache status | [app.js](static/app.js) |
| Document lifecycle | Deduplication, categories, filters, latest/historical versions and API deletion | [storage.py](app/storage.py) |
| Tenant isolation | Application keys identify workspaces and restrict document access | [main.py](app/main.py) |
| Caching and limits | Reuses identical queries and bounds requests, uploads and context | [main.py](app/main.py), [config.py](app/config.py) |
| Persistent local storage | PostgreSQL text, metadata and vectors survive container restarts | [compose.yaml](compose.yaml) |
| Monitoring | LangSmith execution traces, health endpoints and Prometheus metrics | [main.py](app/main.py) |
| Evaluation | Retrieval Recall@K/MRR, automated regressions and real-model smoke checks | [scripts](scripts), [tests](tests) |

## Demo: exactly what to run and show

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

Upload [samples/model-routing-demo.txt](samples/model-routing-demo.txt), **version `3`**, **category `demo`**. Wait for confirmation. Confirm query filters: category `demo`, filename `model-routing-demo.txt`.

Show the library, Refresh library and Ask about this. Re-upload the identical filename/version to show duplicate detection. PDF/Markdown support can be shown by uploading a small text-based file and asking a fact from it.

Latest means the most recently uploaded version, not the largest version number. If another upload made version `3` historical, upload the sample with a new unused version and category `demo` before asking.

### 3. Ask and inspect the answers

| Input | What to show |
|---|---|
| **How many minutes does support have to acknowledge a withdrawal complaint?** | 15 minutes; initial 1B route, actual final model and any 3B fallback |
| **What happens if a standard withdrawal review exceeds 24 hours?** | Escalation to payments operations; retrieval of an exact policy detail |
| **What is the company policy on flying to Mars?** | Insufficient evidence without citations |
| Repeat the first question with identical filters within five minutes | Cache hit; no fresh model generation |

For the larger-model example, ask:

> Compare standard and security-flagged withdrawals. A customer urgently requests a withdrawal while account verification is incomplete and a security hold is active. Explain what support should do and what it must not do.

Show the **3B** route. Check acknowledgement within 15 minutes, security escalation, keeping the hold, no verification bypass/release, and a customer update without exposing detection rules. Standard reviews are within 24 hours after verification; overdue reviews escalate to payments operations.

Expand citations to inspect filename, version, page/section and excerpt. Show Copy answer and the Model activity panel. The factual example can fall back to 3B; do not promise a 1B-only answer. Set category to `nonexistent-demo-category` and ask a new question to show excluded evidence, then restore `demo`.

### 4. Show LangSmith

Click **View traces**, sign in at [LangSmith](https://smith.langchain.com), and open **production-rag**. Select a fresh `rag-request`, expand `rag-question`, and show:

- **Graph steps:** Retrieval, selected evidence and conditional search rewriting/retries.
- **route_model metadata:** Initial model, tier, reason and policy.
- **answer / generate-answer:** Final model, fallback and timing.
- **Nested model Inputs/Outputs:** System prompt, question, retrieved evidence and generated response.
- **Request/model details:** Cache hit, refusal reason, errors and reported token usage.

Cached requests have no new generation span. Rephrase a question for a fresh model trace; delivery can take a few seconds. Rewriting is conditional, so it may not appear on every question. Upload/parsing/SQL do not have dedicated detailed spans, and local electricity cost/private model reasoning are not shown.

### 5. Show database, API, versions and deletion

Open **http://127.0.0.1:8080**: PostgreSQL, server `postgres`, username/database `rag`, password from `.env` -> `POSTGRES_PASSWORD`. Show **documents**, **chunks** and **rag_config**: extracted text, metadata and vectors.

Open **http://127.0.0.1:8000/docs**, Authorize with the app key, then show:

| Action | Endpoint/check |
|---|---|
| List uploaded versions | `GET /documents` |
| Inspect request counts/latency | `GET /metrics` |
| Check process/dependencies | `GET /health/live`, `GET /health/ready` |
| Demonstrate authentication | A protected request without a valid key returns 401 |
| Demonstrate versions | Upload a disposable TXT, change one fact, then upload under the same filename with a new version |
| Query the earlier version | `POST /query` with question and filters containing filename plus version |
| Delete the disposable version | `DELETE /documents/{document_id}`; confirm it disappears from the list |

Historical query example; replace filename/version with your disposable upload:

```json
{"question":"What does the policy require?","filters":{"filename":"version-demo.txt","version":"1"}}
```

Historical-version selection and deletion are API features. Keep the main trading sample intact. Separate-tenant isolation is covered by the automated tests.

### 6. Show verification and evaluation

```powershell
uv run --frozen python -m scripts.verify_running
uv run --frozen python -m scripts.check_docker
```

The live verifier checks both samples: auth/assets, routing, answers, summaries, refusal, citations, cache, library and metrics. It pins fixture versions and writes `data/running-stack-verification.json`; use `--sample trading` for only the trading fixture.

The Docker checker runs tests, lint, formatting and sample retrieval evaluation using a separate `rag_test` database. Show the test result and **Recall@K** (relevant passages found) / **MRR** (how early they appear). These are sample checks, not proof of perfect answers. For your own labeled evaluation, see [export_chunks.py](scripts/export_chunks.py) and [evaluate.py](scripts/evaluate.py).

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
