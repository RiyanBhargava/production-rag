# Production RAG

Upload documents and ask questions with hybrid retrieval, reranking and citations. FastAPI serves the browser interface/API. Choose Ollama locally, Gemini with local embeddings, or OpenAI.

This README covers setup on a new device. Read [PROJECT_GUIDE.md](PROJECT_GUIDE.md) for the plain-language explanation and code references. Both documents are included in the repository.

## 1. Install

Use Python 3.12/3.13, [uv](https://docs.astral.sh/uv/getting-started/installation/), [Ollama](https://ollama.com/download) and Docker Desktop with Linux containers. Commands use PowerShell from the project folder.

On a new device, first install [Git](https://git-scm.com/downloads), [Python](https://www.python.org/downloads/), uv, Ollama, and [Docker Desktop](https://docs.docker.com/desktop/). Open Docker Desktop and Ollama, then reopen your terminal so installed commands are available. Docker is required for PostgreSQL; local Chroma setup can run without it. Allow several GB for downloaded models and Python packages. A GPU helps local generation but is not required.

Check installation with `git --version`, `uv --version`, `ollama --version`, and `docker version`. Docker's server section requires its engine to be running.

```powershell
git clone https://github.com/RiyanBhargava/production-rag.git
cd production-rag
uv sync --frozen
if (-not (Test-Path .env)) { Copy-Item .env.ollama.example .env }
ollama pull llama3:latest
ollama pull nomic-embed-text:latest
```

Keep Ollama running. If it is not already serving, start `ollama serve` in another terminal. Preserve an existing `.env`. First startup downloads the reranker.

The repository includes source, frontend assets, scripts/tests, sample TXT, dependency lockfile, Docker definitions and configuration templates. Private `.env`, virtual environments, models and document databases are not included. Each new device creates/downloads these locally. Re-upload documents unless you separately restore a compatible private database backup.

On macOS/Linux, use the same `git`, `uv`, `ollama` and API commands; replace the PowerShell copy line with `test -f .env || cp .env.ollama.example .env`. Docker with host Ollama is simplest on Docker Desktop. On Linux Docker Engine, use the terminal API + PostgreSQL route to avoid host-container Ollama networking differences.

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

Sign in to [Google AI Studio](https://aistudio.google.com/apikey), create an API key, and choose/create its Google Cloud project if prompted. Copy the key into private `.env`; follow Google's [key setup instructions](https://ai.google.dev/gemini-api/docs/api-key) if your account needs project setup. Check the account's quota/billing before using hosted models. Change/add:

```dotenv
MODEL_MODE=gemini
GEMINI_API_KEY=<your-real-key>
GEMINI_CHAT_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=60
```

Keep Ollama and embedding/database/tenant settings unchanged. Gemini generates answers/rewrites; Nomic still embeds, preserving compatible documents. Questions/selected evidence go to Google. Restart/recreate the API. The Gemini template is for fresh development setup, not overwriting existing configuration. Grok is not implemented.

Sign up/sign in to [LangSmith](https://smith.langchain.com), open **Settings > API Keys**, choose a personal key for your own development or a workspace service key for the application, and click **Create API Key**. Copy it immediately; it is shown once. See the [official account/key instructions](https://docs.langchain.com/langsmith/create-account-api-key). Then add:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-langsmith-key>
LANGSMITH_PROJECT=production-rag
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
TRACE_CONTENT=false
```

Restart, ask an uncached question and open **production-rag → rag-question** in tracing. Use your account's region endpoint/workspace ID if required. Inputs/outputs are hidden; `TRACE_CONTENT=true` sends trace content to LangSmith. Never publish keys.

### Optional OpenAI instead

Sign in to the [OpenAI API dashboard](https://platform.openai.com/api-keys), select your project, create a secret API key, and copy it into `.env`. Set up API billing/credits if your account requires them; follow the [official quickstart](https://developers.openai.com/api/docs/quickstart).

For a **fresh development store**, keep your app key and tracing settings, and change:

```dotenv
APP_ENV=development
STORAGE_BACKEND=chroma
DATA_DIR=./data-openai
MODEL_MODE=openai
OPENAI_API_KEY=<your-openai-key>
CHAT_MODEL=gpt-4.1-mini
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
RERANKER_MODE=cross_encoder
```

Run `uv sync --frozen`, restart the API, and re-upload documents. OpenAI sends both embedding text and answer context to its service. For PostgreSQL, use a separate database initialized with the new embedding settings; do not reuse the 768-dimensional Ollama store.

### Which secret goes where?

| Setting | Where it comes from | Where you use it |
| --- | --- | --- |
| `API_KEYS` | Generate a random secret yourself (command in section 3) | Website's app-key field; the JSON value identifies its tenant |
| `POSTGRES_PASSWORD` | Generate a different random secret yourself | PostgreSQL, matching password in `DATABASE_URL`, and Adminer |
| `GEMINI_API_KEY` | Google AI Studio | Backend `.env` only, when using Gemini |
| `OPENAI_API_KEY` | OpenAI API dashboard | Backend `.env` only, when using OpenAI |
| `LANGSMITH_API_KEY` | LangSmith Settings | Backend `.env` only, when enabling tracing |

Ollama needs no provider API key. For example, with `API_KEYS={"your-generated-secret":"my-company"}`, enter only `your-generated-secret` on the website. Provider keys cannot be arbitrary strings: they must be issued by the provider. Keep `.env` private, replace template app keys before sharing access, and restart the backend after editing settings. Never put provider keys into frontend code.

## 5. Database viewer

Complete the PostgreSQL setup in section 3 first. This viewer shows PostgreSQL data; it does not show a Chroma development store.

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

The 2026-10-06 audit found no known vulnerabilities in production dependencies; development Chroma retains server-path advisories and must not be exposed as an HTTP service. Secrets/stores/caches are excluded from Git and Docker context; documentation is excluded from the Docker image. This is a production-style implementation, not a security certification.
