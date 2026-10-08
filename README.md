# Production RAG

## Explain the project in 30 seconds

> I built a document question-answering workspace for operational knowledge. Users upload policies or procedures, and the application retrieves relevant passages before asking a language model to answer. It combines semantic and keyword search, reranks the evidence, and returns answers with inspectable citations. My local setup uses FastAPI, PostgreSQL/pgvector in Docker, and two Ollama Llama models with automatic routing. LangSmith lets me inspect the execution, model choices and responses.

RAG means **Retrieval-Augmented Generation**. Uploading makes a document searchable; it does not train the models. The trading-support example is fictional and contains no real company policies.

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

## Live demo: run and verify everything

These steps use the installation already prepared on this Windows laptop. Use one private `.env`, one public `.env.example`, one Compose file and one README. Keep existing credentials and database volumes.

### 1. Open Docker Desktop and Ollama

Open both from the Start menu. Wait for Docker's engine to finish starting, and keep Ollama running. Ollama runs on Windows; the API, database and Adminer run in Docker.

### 2. Open PowerShell in the repository

```powershell
Set-Location 'C:/Users/riyan/Desktop/Projects and Research Papers/Production RAG/production-rag'
docker version
ollama list
```

Docker must show both Client and Server. Ollama should list `llama3.2:1b`, `llama3.2:3b` and `nomic-embed-text:latest`. Only pull missing models:

```powershell
ollama pull llama3.2:1b
ollama pull llama3.2:3b
ollama pull nomic-embed-text:latest
```

If Ollama is not serving, start `ollama serve` in a separate terminal. If it reports address already in use, keep the existing instance; do not start competing servers.

### 3. Check the private `.env`

```powershell
notepad .env
```

Preserve existing `API_KEYS`, `POSTGRES_PASSWORD`, `DATABASE_URL` and `LANGSMITH_API_KEY`. The current local setup uses Ollama, PostgreSQL, automatic routing and CPU inference. For full tracing, use:

```dotenv
MODEL_ROUTING_ENABLED=true
LANGSMITH_TRACING=true
TRACE_CONTENT=true
```

`TRACE_CONTENT=true` sends questions, selected document passages, graph inputs/outputs and model responses to your configured LangSmith service. `false` hides inputs/outputs while preserving routing/timing metadata. Only new traces reflect a setting change; old redacted traces cannot be reconstructed.

Local Ollama needs no paid provider key. The browser expects the **application secret from `API_KEYS`**, not the LangSmith key. Full configuration, optional providers and tuning are explained below.

### 4. Build and start the application

```powershell
docker compose --profile tools up -d --build
docker compose --profile tools ps
```

Expect API/PostgreSQL to become healthy and Adminer to be Up. A later start with unchanged source can omit `--build`. The frontend is served by FastAPI; no Node installation or frontend build is required.

### 5. Wait for readiness

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

Expected: `status=ready`, `mode=ollama`, `storage=postgres`. During startup the connection can close while models/reranker initialize. Wait for API health to become healthy before retrying. Check errors with:

```powershell
docker compose logs --tail 80 api
```

Readiness checks dependency availability, not answer quality; the following questions check generation.

### 6. Connect the browser

Copy the application secret without displaying it:

```powershell
uv run --frozen python -c "from app.config import Settings; print(next(iter(Settings().api_keys)))" | Set-Clipboard
```

Open **http://127.0.0.1:8000**, paste into Application API key and click **Connect**. Use Ctrl+F5 if old assets are cached. The key stays in page memory and is cleared on refresh. It is not saved in browser storage.

### 7. Upload the fictional trading-support sample

Choose [samples/model-routing-demo.txt](samples/model-routing-demo.txt), **version `3`**, **category `demo`**, then click Upload document. Wait for confirmation. An identical filename/version upload is deduplicated; changed content needs a new version.

Say: "The application extracts text, splits it into passages, embeds them, and stores their metadata and vectors."

Confirm query filters: **category `demo`**, **filename `model-routing-demo.txt`**. Upload fills these automatically. They keep other documents from affecting the demonstration.

### 8. Show factual routing and a citation

Ask:

> How many minutes does support have to acknowledge a withdrawal complaint?

Expected supported fact: **15 minutes**. Expand the citation to show the source excerpt and version. Inspect Model activity: the initial route is lightweight `llama3.2:1b`. If 1B abstains despite positive retrieval or returns malformed output, one 3B fallback is allowed. The panel shows the actual final model; this sample has needed fallback in verified runs. Do not describe it as guaranteed 1B-only generation.

### 9. Show the larger-model route

Ask:

> Compare standard and security-flagged withdrawals. A customer urgently requests a withdrawal while account verification is incomplete and a security hold is active. Explain what support should do and what it must not do.

Expected initial route: larger `llama3.2:3b`. Check acknowledgement within 15 minutes, security escalation, no verification bypass or release, keeping the security hold and a customer update without revealing detection rules. A standard review is within 24 hours after verification; overdue reviews escalate to payments operations. Review completeness and each supporting passage; routing does not guarantee every detail appears.

The suggestion buttons prefill these two questions but do not submit them automatically.

### 10. Show refusal, cache and library filters

Ask:

> What is the company policy on flying to Mars?

Expect insufficient evidence without citations. Repeat the exact factual question with identical filters within five minutes: expect **Cache hit** and no new generation. The activity panel describes the reused answer's original route.

Click Refresh library and Ask about this to focus on a document. Re-upload the identical file/version to show deduplication. Set category to `nonexistent-demo-category`, ask a new question, and expect insufficient evidence; then restore `demo`.

### 11. Inspect LangSmith prompts and routing

Click **View traces**, sign in at [LangSmith](https://smith.langchain.com), and open project **production-rag**. Select the latest `rag-request`, then expand `rag-question`.

| Trace or field | What to show |
|---|---|
| Graph steps | Retrieval, evidence selection, conditional rewriting, routing and answering |
| `route_model` metadata | `tier`, initial `model`, `reason`, `policy` |
| `answer` / `generate-answer` | Final model, fallback reason and generation duration |
| Nested model call Inputs | System instructions, question and selected evidence when content tracing is enabled |
| Nested model call Outputs | Generated structured response, including abstention |
| Request metadata | Cache hit, final model and refusal reason |
| Model usage | Reported input/output tokens when supplied by the model integration |
| Errors and duration | Failed runs and time spent in individual steps |

Traces can take a few seconds to appear. Cached requests have a request trace without a fresh model span. Rephrase a prompt or restart the API to generate a fresh trace. LangSmith shows inputs/outputs and execution, not private model reasoning. Local electricity/hardware cost is not measured automatically. Upload, parsing and SQL do not have dedicated detailed spans yet; graphs/models are traced. See [LangSmith content controls](https://docs.langchain.com/langsmith/mask-inputs-outputs).

### 12. Show the API, database and lifecycle

Open **http://127.0.0.1:8000/docs** and Authorize with the application secret. List documents, query them and inspect metrics. Protected endpoints return 401 without the key.

Open **http://127.0.0.1:8080**: PostgreSQL, server `postgres`, username/database `rag`, password `.env` -> `POSTGRES_PASSWORD`. Show `documents`, `chunks` and `rag_config`. Adminer can modify data, so use it locally and carefully.

For versioning, upload a disposable file, then upload changed content under the same filename with a new version. Query it in API docs with `filters.version` to select a historical version. Latest means the most recently uploaded active version, not the largest numeric label. For deletion, call `DELETE /documents/{document_id}` on the disposable version and confirm it disappears. The UI does not have historical-version or delete controls.

For PDF/Markdown parsing, upload a small text-based file and ask a fact supported by it. OCR for scanned PDFs is not implemented.

### 13. Run the feature checks

```powershell
uv run --frozen python -m scripts.verify_running
uv run --frozen python -m scripts.check_docker
```

The first uses the live API and real models to check readiness/assets, authentication, both sample uploads, initial/final routing, factual answers, summaries, refusal, citations, caching, library and metrics. It uploads the trading fixture as version `3`, pins each query to its fixture version, leaves the sample documents in your workspace and writes `data/running-stack-verification.json`. Use `--sample trading` or `--sample policy` for one fixture. Answer-term checks are smoke checks, not proof of complete correctness.

The second runs tests, lint, formatting and sample retrieval evaluation in a temporary Linux container and a separate `rag_test` database. It does not replace the production document store. It downloads development dependencies when needed. The real-model verifier and backend suite test different things.

### 14. Demonstrate persistence and stop

Restart, wait for readiness, reconnect and check the library:

```powershell
docker compose --profile tools restart
```

Database records persist in volumes. The in-memory cache clears on API restart. Stop with:

```powershell
docker compose --profile tools stop
```

Optionally unload local models:

```powershell
ollama stop llama3.2:1b
ollama stop llama3.2:3b
ollama stop nomic-embed-text:latest
```

Docker Desktop/Ollama can remain idle. **Do not use `down -v` for normal shutdown:** it deletes database/cache volumes. After code changes use `up -d --build`; after `.env` changes recreate the API with `docker compose up -d --force-recreate api`.

## How the implementation works

```text
Upload -> Extract -> Chunk + metadata -> Embed -> Store
Question -> Tenant/filters -> Semantic + keyword retrieval -> Rank fusion
         -> Cross-encoder reranking -> Limited evidence -> Conditional rewrite
         -> Model routing -> Structured answer -> Validate source IDs -> Respond
```

FastAPI serves the UI and endpoints. LangChain supplies model adapters and text splitting. LangGraph coordinates retrieval, retries and answering. The browser renders text safely and provides loading/error states, copying and expandable sources.

Document chunks default to 1000 characters with 150 overlap. Metadata includes tenant, filename, version, category, page, heading and document/chunk identifiers. Deduplication avoids re-storing identical uploads. SQL is authoritative; the system stores extracted text, not an archive of uploaded originals.

Semantic retrieval compares vectors; keywords help with exact codes and terminology. PostgreSQL uses English full-text search, not BM25. Development uses BM25 plus Chroma vectors. Reciprocal rank fusion combines rankings without assuming their raw scores are comparable. The CPU cross-encoder scores question/passage pairs to improve ordering.

The answer context defaults to five chunks and 12000 characters. Overview selection seeks section diversity. Weak retrieval can trigger a bounded query rewrite; the default is two attempts. A rewrite is conditional and need not occur on every question.

The generator returns claims with source IDs. The application checks IDs against retrieved sources and attaches stored excerpts. Invalid/malformed output, absent candidates or model abstention produce a refusal. Duplicate claims/source IDs are normalized after validation. **Valid citation IDs do not prove semantic support:** read the cited passage, especially for consequential claims. Models can omit details or misattribute a claim.

PostgreSQL vector search is exact over eligible rows. An HNSW index exists, but the current query does not use approximate nearest-neighbor search.

## Why these models and how routing works

| Component | Local model | Role |
|---|---|---|
| Lightweight generation | `llama3.2:1b`, about 1.3 GB download | Factual lookups and query rewriting |
| Larger generation | `llama3.2:3b`, about 2 GB download | Synthesis, conservative defaults and fallback |
| Embeddings | `nomic-embed-text:latest`, about 274 MB download | 768-dimensional document/question vectors |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | CPU question/passage scoring; cached in Docker |

The laptop has 16 GB RAM and limited free memory. 1B/3B offer two local tiers without an 8B download/runtime. Download size is not total inference RAM. 3B is larger relative to 1B, not a frontier model. This is a practical initial choice, not a measured optimal model selection.

Routing runs after evidence selection. Policy `llama-rules-v1` is deterministic:

| Signal | Decision |
|---|---|
| No evidence | Refuse without answer generation |
| Summary/comparison/explanation/reasoning keywords | 3B |
| Multiple source documents or more than 6000 context characters | 3B |
| Short single-document what/when/who/where/how-many lookup | 1B |
| Other question phrasing | Conservative 3B default |
| 1B malformed output | One 3B retry |
| 1B abstains despite positive retrieval | One 3B second opinion |

There is no trained classifier or calibrated confidence score. Positive reranker output permits fallback; it is not proof that evidence answers the question. The stronger model must still cite sources or refuse. Weak-evidence abstention does not trigger repeated escalation.

Both generation models unload after calls (`keep_alive=0`) to reduce memory use; this adds reload latency. The current CPU settings avoid the Intel GPU model-loading stalls observed on this laptop. Remove `OLLAMA_NUM_GPU` and `OLLAMA_EMBEDDING_NUM_GPU` to let Ollama select devices on other hardware. Device placement does not change embedding model/dimensions or require re-ingestion.

Routing/fallback worked in live checks, but the trading factual example needed 3B fallback. Routing is not guaranteed to save time. Use labeled domain questions to assess model quality, fallback frequency and latency before making efficiency claims.

## One configuration file and all keys

[.env.example](.env.example) is the only public template. **`.env` is the private active file**, next to `compose.yaml`. Provider differences are settings, not separate sample files. Existing `.env` must be preserved; templates contain placeholders and no real credentials. Git/Docker exclude `.env`.

| Setting(s) | Meaning |
|---|---|
| `APP_ENV`, `STORAGE_BACKEND`, `MODEL_MODE` | Validation profile, storage and model provider |
| `API_KEYS` | JSON secret-to-tenant mapping; application login/authentication |
| `POSTGRES_PASSWORD`, `DATABASE_URL` | Distinct database secret and host SQL connection; Compose supplies container address |
| `DATA_DIR` | Development files; Compose sets writable `/app/data` |
| `OLLAMA_BASE_URL` | Host commands use localhost; Docker sets `host.docker.internal` |
| `OLLAMA_LIGHT_MODEL`, `OLLAMA_CHAT_MODEL` | Initial factual and larger generation model tags |
| `OLLAMA_EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | Embedding space; current Nomic dimension is 768 |
| `MODEL_ROUTING_ENABLED`, `ROUTING_CONTEXT_CHARS` | Enable local routing and long-context threshold |
| `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_CONTEXT_TOKENS` | Request timeout and model context window |
| `OLLAMA_NUM_GPU`, `OLLAMA_EMBEDDING_NUM_GPU` | Zero forces CPU; omit for default device selection |
| `RERANKER_MODE`, `RERANKER_MODEL` | Lexical dev mode or real cross-encoder |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` | Enable tracing and authenticate to LangSmith |
| `TRACE_CONTENT` | Include or hide inputs/outputs; full content goes to LangSmith |
| `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`, `LANGSMITH_WORKSPACE_ID` | Project/region/workspace routing; full names appear in the template |
| `GEMINI_API_KEY`, `GEMINI_CHAT_MODEL`, `GEMINI_TIMEOUT_SECONDS` | Optional hosted Gemini generation |
| `OPENAI_API_KEY`, `CHAT_MODEL`, `EMBEDDING_MODEL` | Optional hosted OpenAI generation and embeddings |

The template shows tuning defaults: chunk size/overlap, retrieval candidates, context budget, attempts, cache lifetime, per-key rate limit, upload bytes, extracted characters and chunk count. Settings validation rejects invalid overlap, unsupported routing/provider combinations, missing required keys and incompatible production modes. See [config.py](app/config.py).

Do not rotate an initialized database password by only editing `.env`: PostgreSQL's existing role must also be updated. Changing embedding model, dimensions or prefixes needs a fresh compatible store and re-ingestion. Switching generation alone preserves compatible embeddings.

## Fresh installation on another device

Install Git, Python 3.12/3.13, [uv](https://docs.astral.sh/uv/getting-started/installation/), [Docker Desktop](https://docs.docker.com/desktop/) with Linux containers, and [Ollama](https://ollama.com/download). Open Docker/Ollama and reopen PowerShell so commands are available.

```powershell
git clone https://github.com/RiyanBhargava/production-rag.git
cd production-rag
uv sync --frozen
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv run --frozen python -c "import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))"
notepad .env
```

Use the first generated secret inside `API_KEYS`; use the different second secret for `POSTGRES_PASSWORD` and the password in `DATABASE_URL`. Save a LangSmith key from your own account, or set `LANGSMITH_TRACING=false` if tracing is not configured. Choose trace content deliberately. Pull the three Ollama models, then follow demo steps 4 onward. Initial builds download packages and the reranker and need several GB of disk space.

Models, `.env`, virtual environments and Docker volumes are not in Git. New devices create/download them and re-upload documents unless restoring a compatible private database backup. macOS/Linux commands are similar; replace the PowerShell conditional copy with `test -f .env || cp .env.example .env`. Linux Docker Engine may need a host gateway mapping for `host.docker.internal` or host-run API configuration.

## Optional provider and development modes

All modes use the same `.env.example`. Preserve app/database/tracing settings and edit only the required settings. The default local demo does not need these hosted providers.

**Gemini:** set `MODEL_MODE=gemini`, `MODEL_ROUTING_ENABLED=false`, `GEMINI_API_KEY` and `GEMINI_CHAT_MODEL`. Keep Nomic/768-dimensional embeddings and storage unchanged. Questions and selected context go to Google. Obtain the key from [Google AI Studio](https://aistudio.google.com/apikey); check your account's quota/billing. Recreate the API.

**OpenAI:** set `MODEL_MODE=openai`, `MODEL_ROUTING_ENABLED=false`, `OPENAI_API_KEY`, `CHAT_MODEL` and `EMBEDDING_MODEL`. With `text-embedding-3-small`, set dimensions to 1536 and use a separate compatible database/store, then re-upload. Obtain the key from the [API dashboard](https://platform.openai.com/api-keys). Both embedding text and generation context go to OpenAI. Do not reuse the current Nomic store.

**Offline plumbing mode:** set `APP_ENV=development`, `STORAGE_BACKEND=chroma`, `MODEL_MODE=demo`, `MODEL_ROUTING_ENABLED=false`, `RERANKER_MODE=lexical`, dimensions 64 and a separate data directory. Install dev dependencies with `uv sync --frozen`, then run `uv run uvicorn app.main:create_app --factory --port 8000`. This uses fake hashed embeddings and retrieved excerpts, not real LLM answers. It is rejected in production mode.

The Docker production image excludes development Chroma. The default Docker route is recommended on this laptop because native Windows dependency loading was blocked by Application Control; no security policy was disabled.

## API, evaluation and repository map

| Endpoint | Access and purpose |
|---|---|
| `/`, `/static/*` | Public frontend assets |
| `/docs`, `/openapi.json` | Interactive API reference/schema |
| `GET /health/live`, `GET /health/ready` | Process/dependency checks |
| `POST /documents` | App key; multipart file/version/category upload |
| `GET /documents` | App key; tenant-scoped document versions |
| `DELETE /documents/{document_id}` | App key; tenant-scoped deletion |
| `POST /query` | App key; question and optional category/filename/version/document-ID filters |
| `GET /metrics` | App key; Prometheus request counts and latency |

Use `X-API-Key` for protected endpoints. Static keys represent workspaces, not individual user accounts. The cache key includes tenant, question, filters, document revision and routing policy/settings. Upload/delete revisions prevent stale reuse. Default cache lifetime is five minutes with a 1000-entry bound.

Retrieval evaluation separates evidence retrieval from generation: Recall@K measures labeled relevant passages found; MRR rewards early relevant results. Export tenant chunk IDs with [export_chunks.py](scripts/export_chunks.py), label JSONL questions manually, and run [evaluate.py](scripts/evaluate.py). Use their `--help` options for exact arguments. [demo_evaluation.py](scripts/demo_evaluation.py) exercises fake-mode retrieval in isolation. Reported sample scores are not broad real-world quality guarantees.

| Files | Responsibility |
|---|---|
| `app/config.py` | Settings and validation |
| `app/documents.py` | Extraction, headings, chunking and metadata |
| `app/storage.py` | Authoritative records, tenant filters, versions, vectors and keywords |
| `app/pipeline.py` | Model adapters, fusion, reranker, graph, rewriting and answers |
| `app/routing.py` | Small deterministic model-selection policy |
| `app/main.py` | API, authentication, locks, limits, cache, health and tracing |
| `static/index.html`, `styles.css`, `app.js` | Plain HTML/CSS/JS workspace; no build framework |
| `scripts/verify_running.py` | One HTTP/real-model verifier for both samples |
| `scripts/check_docker.py` | Linux regression checks with separate test database |
| `scripts/verify_local.py` | Alternative isolated host/provider check; requires supported native dependencies |
| `scripts/evaluate.py`, `export_chunks.py`, `demo_evaluation.py` | Labeled evaluation, IDs and sample checks |
| `tests/` | API, isolation, versions, parsing, providers, security and routing tests |
| `samples/` | Fictional trading demo and employee-policy regression fixture |
| `Dockerfile`, `compose.yaml` | Non-root API image, PostgreSQL, optional Adminer and volumes |
| `pyproject.toml`, `uv.lock` | Python tooling and locked dependencies |
| `.env.example`, `.gitignore`, `.dockerignore` | Single template and private/generated-file exclusions |
| `.github/workflows/checks.yml` | CI tests, lint and formatting with disposable PostgreSQL |
| `README.md` | Single explanation, demonstration and operational reference |

Package `__init__.py` files mark Python modules. `.venv`, model caches, generated reports and volumes are runtime material, not extra authored documentation. The production image contains app/static, not scripts/tests; verification uses host tooling or the dedicated test container.

## Operational limits and troubleshooting

This is a **production-style local application**, not a complete enterprise deployment. One worker/process is supported because locks, rate limits and cache are in memory. Queries and document mutations serialize; shared coordination and background ingestion are needed for replicas/high throughput.

Services bind to localhost. The API runs non-root; credentials remain in backend configuration. Tenant SQL predicates enforce workspace isolation; PostgreSQL RLS is enabled but the owner can bypass it. Public deployment still requires HTTPS, user identity/authorization, restricted DB roles, backups, migrations and load/quality testing. OCR, streaming, automatic document syncing, managed migrations, bundled monitoring dashboards and semantic proof of claims are not implemented.

| Symptom | Action |
|---|---|
| Docker cannot connect | Open Docker Desktop and wait for the engine |
| Connection closes immediately after start | Wait for API health; read `docker compose logs --tail 80 api` |
| API is 503 or local model is missing | Check Ollama, `ollama list`, models and container logs |
| GPU runner stalls | Current `.env` uses CPU; restart Ollama from its tray, then restart API |
| Application key rejected | Use the secret inside `API_KEYS`, not LangSmith/DB/provider keys |
| Changed settings ignored | Recreate API; rebuild too when source changes |
| Insufficient evidence | Check active version, file/category filters and cited source content |
| Changed upload conflicts | Use a new version for changed content |
| Trace inputs are empty | Check `TRACE_CONTENT`, recreate API and submit a new uncached request |
| No new model trace | Cached request; rephrase or clear memory cache via API restart |
| UI looks old | Rebuild API and Ctrl+F5 |

The latest local verification passed 35 automated tests, PostgreSQL integration, lint, formatting and sample evaluation. Real-model checks exercised both routing tiers, fallback, supported facts, summaries, refusal, citations and caching. UI interactions were checked in headless Chrome with simulated responses at desktop/mobile widths; these are separate from live-model checks. No test result guarantees perfect answers on arbitrary documents. The consolidated verifier provides a repeatable check after changes.
