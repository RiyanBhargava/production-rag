# Production RAG

Upload documents and ask questions with hybrid retrieval, reranking and citations. FastAPI serves the browser interface/API. Choose Ollama locally, Gemini with local embeddings, or OpenAI.

This README covers setup. `PROJECT_GUIDE.md` is the concise local project explanation; it stays off GitHub because only README is published as Markdown.

## 1. Install

Use Python 3.12/3.13, [uv](https://docs.astral.sh/uv/getting-started/installation/), [Ollama](https://ollama.com/download) and Docker Desktop with Linux containers. Commands use PowerShell from the project folder.

```powershell
git clone https://github.com/RiyanBhargava/production-rag.git
cd production-rag
uv sync --frozen
if (-not (Test-Path .env)) { Copy-Item .env.ollama.example .env }
ollama pull llama3:latest
ollama pull nomic-embed-text:latest
```

Keep Ollama running. If it is not already serving, start `ollama serve` in another terminal. Preserve an existing `.env`. First startup downloads the reranker.

## 2. Start and try it

```powershell
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** and connect with an app key from private `.env` → `API_KEYS`. Upload `samples/employee-policy.txt`; ask about annual leave and check the cited 24-day passage. The template key `local-change-me` is for development only.

API reference: **http://127.0.0.1:8000/docs**. Stop with **Ctrl+C** and restart with the same command. Keep one worker; stored documents persist.

## 3. PostgreSQL setup

Generate two different secrets locally:

```powershell
uv run python -c "import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))"
```

Edit private `.env`, replace placeholders and keep other Ollama settings:

```dotenv
APP_ENV=production
MODEL_MODE=ollama
STORAGE_BACKEND=postgres
EMBEDDING_DIMENSIONS=768
RERANKER_MODE=cross_encoder
API_KEYS={"<random-app-key>":"my-company"}
POSTGRES_PASSWORD=<different-random-db-password>
DATABASE_URL=postgresql+psycopg://rag:<different-random-db-password>@127.0.0.1:5432/rag
```

Start Docker Desktop, stop the old API, then:

```powershell
docker compose up -d postgres
uv sync --frozen --no-dev
uv run --no-dev --frozen uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Use the app key on the website, not the DB/provider key. Switching stores requires re-uploading; changing embeddings requires a compatible new store. Changing a password in `.env` does not change an already initialized PostgreSQL role automatically.

### Containerize the API too

Stop the terminal API; keep host Ollama running:

```powershell
docker compose -f compose.yaml -f compose.ollama.yaml up -d --build
docker compose -f compose.yaml -f compose.ollama.yaml logs --tail 100 api
docker compose -f compose.yaml -f compose.ollama.yaml stop
docker compose -f compose.yaml -f compose.ollama.yaml start
```

After code/environment changes, use `up -d --build`. The override connects to host Ollama; check its listening/firewall settings if unreachable and keep port 11434 private. Named volumes retain data. **Do not delete volumes for ordinary shutdown.** Chroma is a development dependency excluded from the production image.

## 4. Optional Gemini and LangSmith

Create a key at [Google AI Studio](https://aistudio.google.com/apikey). Change/add in existing private `.env`:

```dotenv
MODEL_MODE=gemini
GEMINI_API_KEY=<your-real-key>
GEMINI_CHAT_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=60
```

Keep Ollama and embedding/database/tenant settings unchanged. Gemini generates answers/rewrites; Nomic still embeds, preserving compatible documents. Questions/selected evidence go to Google. Restart/recreate the API. The Gemini template is for fresh development setup, not overwriting existing configuration. OpenAI mode is supported but requires its embedding/store settings; Grok is not implemented.

Create a separate key at [LangSmith](https://smith.langchain.com), then add:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-langsmith-key>
LANGSMITH_PROJECT=production-rag
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
TRACE_CONTENT=false
```

Restart, ask an uncached question and open **production-rag → rag-question** in tracing. Use your account's region endpoint/workspace ID if required. Inputs/outputs are hidden; `TRACE_CONTENT=true` sends trace content to LangSmith. Never publish keys.

## 5. Database viewer

```powershell
docker compose --profile tools up -d adminer
```

Open **http://127.0.0.1:8080**. System: **PostgreSQL**; server: **postgres**; username/database: **rag**; password: private `POSTGRES_PASSWORD`. Choose **documents/chunks → Select data**. Adminer can modify data. Stop with `docker compose --profile tools stop adminer`.

Data is local in Docker's persistent PostgreSQL volume; extracted text/metadata/vectors are stored, original uploads are not archived. Check size:

```powershell
docker compose exec -T postgres psql -U rag -d rag -c "SELECT pg_size_pretty(pg_database_size('rag'));"
```

## 6. Verify

```powershell
uv sync --frozen
uv run pytest -q
uv run ruff check app tests scripts
uv run ruff format --check app tests scripts
uv run python -m scripts.demo_evaluation
```

`uv run python -m scripts.verify_local` checks actual Ollama/Gemini answers in an isolated store; hosted calls use quota/credits. Ordinary tests do not make paid model calls. PostgreSQL integration needs a separate test DB via `TEST_DATABASE_URL`; CI supplies one.

For real evaluation, export IDs with `uv run python -m scripts.export_chunks --tenant my-company`, manually label JSONL questions and run `uv run python -m scripts.evaluate <dataset> --tenant my-company --k 5`; add `--generate` for answers. Data/reports stay private.

## Deployment boundaries

Services bind to localhost. Public use needs HTTPS, identity/authorization, restricted DB roles, tested backups and load/quality checks. Uploads are synchronous; locks/cache/rate limits support one process. Citations validate IDs, not every claim's truth.

The 2026-10-06 audit found no known vulnerabilities in production dependencies; development Chroma retains server-path advisories and must not be exposed as an HTTP service. Secrets/stores/caches/local docs are excluded from Git/Docker context. This is a production-style implementation, not a security certification.
