# How I explain my RAG project

This guide is written in first person so I can use it to explain the project. README.md covers setup and commands; this document explains how the pieces work together. Code references link to repository files and lines on GitHub; after cloning, open the named file at the indicated line.

## 1. What I built

I built an application where users upload documents and ask questions about them. The system finds relevant passages, generates an answer from that evidence, and returns citations so the user can check it.

For example, a user can upload an employee policy and ask about annual leave. My application finds the leave section, explains the allowance and shows the supporting passage. If the document does not contain an answer, the system can refuse instead of inventing one.

This is called **Retrieval-Augmented Generation**, or **RAG**: retrieve evidence first, then generate an answer. Uploading documents makes them searchable; it does not train the language model.

## 2. The overall architecture

There are two paths:

```text
Upload -> Extract text -> Chunk -> Add metadata -> Embed -> Store

Question -> Hybrid search -> Merge -> Rerank -> Select evidence
         -> Generate answer -> Validate citations -> Respond
```

FastAPI receives requests and serves the browser interface. LangChain supplies text splitting and model adapters. LangGraph connects retrieval, retries and answering. Storage is either Chroma/SQLite for development or PostgreSQL/pgvector for production-oriented use.

**Code:** [app/main.py:64](app/main.py#L64), [app/pipeline.py:182](app/pipeline.py#L182).

## 3. How I prepare documents

I accept PDF, TXT and Markdown files. The parser extracts text and preserves useful information such as PDF page numbers and inferred headings. Scanned PDFs need OCR before upload; complex tables may not extract perfectly.

I split the text into **chunks**, which are smaller passages that can be retrieved independently. Defaults are 1000 characters with 150 characters of overlap, helping preserve context across boundaries. Each chunk keeps metadata such as filename, page, section, category and version. This supports filtering and citations.

Next, an embedding model converts each chunk into a numerical representation of its meaning. Similar meanings can then be found even when the question uses different words. Embeddings are checked for valid dimensions and values before storage.

I also handle duplicates and versions. Identical filename/version uploads are deduplicated; changed content requires a new version. New uploads become active, while older versions remain available through explicit filters. “Latest” means last uploaded, not the largest version label. Processing is synchronous, and duplicate detection happens after embedding.

**Code:** [app/documents.py:15](app/documents.py#L15), [app/pipeline.py:105](app/pipeline.py#L105), [app/storage.py:121](app/storage.py#L121).

## 4. How I answer questions

First, I identify the user's workspace from its application key. Searches apply that workspace and any filename, category, version or document-ID filters. Filters are exact matches; active document versions are used by default.

I use **hybrid retrieval**: semantic search finds related meanings, while keyword search helps with specific terms and codes. Development uses BM25 for keywords; PostgreSQL uses English full-text search, which is not BM25.

I merge the ranked lists using **reciprocal rank fusion**, then use a **cross-encoder reranker** to read the question and candidate passages together and improve their order. Retrieval tries to find useful evidence; reranking helps put the best evidence first.

I select a limited context—by default five chunks and 12000 characters—rather than sending every result to the model. Overview questions get passages from different sections. If retrieval is weak, LangGraph can rewrite the search query and retry. The default limit is two attempts, preventing unlimited loops and unnecessary cost.

Finally, I instruct the model to answer using the selected evidence and return structured claims with source IDs. The application checks those IDs and attaches stored filenames, pages, sections, versions and excerpts. Missing evidence or malformed/invalid output produces an insufficient-evidence response with a reason.

Citation validation checks references, not the truth of every claim. A valid citation still needs to be read when accuracy matters.

**Code:** [app/storage.py:198](app/storage.py#L198), [app/pipeline.py:40](app/pipeline.py#L40), [app/pipeline.py:210](app/pipeline.py#L210), [app/pipeline.py:249](app/pipeline.py#L249), [app/pipeline.py:268](app/pipeline.py#L268).

## 5. My storage and model choices

| Option | Role |
|---|---|
| Chroma + SQLite | Local development: SQLite holds authoritative records; Chroma is a rebuildable vector index |
| PostgreSQL + pgvector | Stores documents, metadata, text and vectors together |
| Ollama | Local generation and embeddings, without a paid provider key |
| Gemini | Hosted generation/query rewriting, while keeping local Ollama embeddings |
| OpenAI | Hosted generation and embeddings |
| Demo | Fake embeddings and retrieved excerpts for testing plumbing, not answer quality |

My current PostgreSQL is local in Docker. Supabase can supply a private PostgreSQL connection, but frontend Supabase authentication is not implemented. Grok is not integrated.

The database has `documents`, `chunks` and `rag_config` tables. It stores extracted text and vectors, not an archive of original uploaded files. Changing embedding models/dimensions/prefixes requires a compatible new store and re-ingestion. Switching Ollama answers to Gemini preserves existing vectors when embedding settings stay unchanged.

PostgreSQL vector retrieval currently uses exact search over eligible rows. An HNSW index exists, but the current query does not use it for approximate search.

**Code:** [app/config.py:51](app/config.py#L51), [app/pipeline.py:49](app/pipeline.py#L49), [app/storage.py:14](app/storage.py#L14), [app/storage.py:65](app/storage.py#L65).

## 6. Features users can access

The browser supports uploads, document versions/categories, a document library, search filters, suggested questions, loading/errors, answer copying and expandable citation passages. The application key stays in page memory rather than browser storage.

FastAPI exposes upload/list/delete document endpoints and a question endpoint. `/docs` provides an interactive API reference; health endpoints check process/dependency availability, and authenticated `/metrics` exposes request counts and latency. Historical-version queries and deletion are API features; there is no delete button in the UI.

Repeated questions can use a memory cache. Its key includes workspace, question, filters and document revision, so updates prevent stale reuse. The default lifetime is 300 seconds, with a 1000-entry limit. Upload, question and rate limits help bound resource use.

**Code:** [static/app.js:216](static/app.js#L216), [app/main.py:46](app/main.py#L46), [app/main.py:211](app/main.py#L211).

## 7. How I monitor and evaluate it

I use optional **LangSmith tracing** to inspect graph/model steps, timing, errors and reported token usage. Inputs/outputs are hidden by default; enabling trace content can send questions and document passages to LangSmith. Cached answers bypass model calls. Upload/PDF/SQL operations are not individually detailed spans yet. Prometheus metrics complement these traces, but dashboards/alerts are not bundled.

I evaluate retrieval separately from generation. **Recall@K** measures how many labeled relevant passages appear in the top results. **MRR** rewards finding a relevant passage early. This distinguishes missing evidence from a poor answer based on retrieved evidence.

Evaluation uses manually labeled chunk IDs. Answer-term matching is only a smoke check, so I also review correctness, completeness, citations and refusals. Tests cover API behavior, tenant isolation, versions, cache, parsing, providers and security. Real-model checks use an isolated store; CI supplies a disposable PostgreSQL database.

**Code:** [app/pipeline.py:367](app/pipeline.py#L367), [scripts/evaluate.py:13](scripts/evaluate.py#L13), [scripts/verify_local.py:16](scripts/verify_local.py#L16), [.github/workflows/checks.yml:1](.github/workflows/checks.yml#L1).

## 8. Docker, security and deployment limits

Docker packages the API and database into predictable services. An image is the package, a container runs it, and a volume preserves data. Compose connects PostgreSQL, the optional API and Adminer database viewer. Ollama remains on the Windows host. Services bind to localhost; the API image runs as a non-root user with one worker.

Actual credentials belong in private `.env` or deployment secrets/environment settings. Git and Docker exclude `.env`; public templates/tests contain fake values. Provider keys stay on the backend, although the browser needs the application key. Runtime processes also hold secrets in memory.

Security controls include tenant-restricted queries, constant-time key checks, limits, safe text rendering, browser headers, generic errors, request IDs and secret redaction. PostgreSQL RLS is enabled, but its backend owner can bypass it, so app SQL predicates remain the tenant boundary. Static workspace keys are not a full user-login system. Adminer has privileged access and should remain local.

The recorded 2026-10-06 audit found no configured secrets in tracked Git history and no known vulnerabilities in production dependencies. Development Chroma retained server-path advisories; it is excluded from production installs, and this app does not launch a Chroma HTTP server. This reduces exposure rather than patching the dependency.

I describe this as **production-style**, not a complete enterprise deployment. Public use still needs HTTPS, identity/authorization, restricted DB roles, backups and load/quality checks. One process is supported because locks/cache/rate limits are local and queries serialize with document mutations. Scaling needs shared coordination and background ingestion. OCR, automatic freshness syncing, streaming, managed migrations and semantic proof of claims are not bundled.

**Code:** [Dockerfile:1](Dockerfile#L1), [compose.yaml:1](compose.yaml#L1), [app/main.py:92](app/main.py#L92), [app/main.py:110](app/main.py#L110), [app/config.py:56](app/config.py#L56).

## 9. My compact code map

| File(s) | Responsibility |
|---|---|
| [app/config.py:8](app/config.py#L8) | Settings, limits and production validation |
| [app/documents.py:15](app/documents.py#L15) | Parsing, metadata, splitting and chunk deduplication |
| [app/storage.py:14](app/storage.py#L14) | Storage, versions, filters, retrieval and deletion |
| [app/pipeline.py:182](app/pipeline.py#L182) | Models, fusion, reranking, graph, context and citations |
| [app/main.py:64](app/main.py#L64) | API, auth, cache, health, metrics and safe errors |
| [static/index.html:1](static/index.html#L1), [static/styles.css:1](static/styles.css#L1), [static/app.js:1](static/app.js#L1) | Interface layout, styling and interactions |
| [scripts/export_chunks.py:1](scripts/export_chunks.py#L1), [scripts/evaluate.py:24](scripts/evaluate.py#L24) | Export evaluation IDs and measure retrieval/answers |
| [scripts/demo_evaluation.py:13](scripts/demo_evaluation.py#L13), [scripts/verify_local.py:16](scripts/verify_local.py#L16) | Sample evaluation and real-model smoke checks |
| [tests/test_api.py:1](tests/test_api.py#L1), [tests/test_components.py:1](tests/test_components.py#L1) | API/components and optional PostgreSQL tests |
| [tests/test_ollama.py:1](tests/test_ollama.py#L1), [tests/test_gemini.py:1](tests/test_gemini.py#L1), [tests/test_security.py:1](tests/test_security.py#L1) | Provider and security regressions |
| [app/__init__.py:1](app/__init__.py#L1), [scripts/__init__.py:1](scripts/__init__.py#L1), [samples/employee-policy.txt:1](samples/employee-policy.txt#L1) | Package markers and fictitious sample policy |
| [pyproject.toml:1](pyproject.toml#L1), [uv.lock:1](uv.lock#L1) | Dependencies/tool settings and locked versions |
| [Dockerfile:1](Dockerfile#L1), [compose.yaml:1](compose.yaml#L1), [compose.ollama.yaml:1](compose.ollama.yaml#L1) | Image/services and host Ollama connection |
| [.github/workflows/checks.yml:1](.github/workflows/checks.yml#L1) | Automated lint/format/tests |
| [.env.example:1](.env.example#L1), [.env.ollama.example:1](.env.ollama.example#L1), [.env.gemini.example:1](.env.gemini.example#L1) | Public configuration templates |
| [.gitignore:1](.gitignore#L1), [.dockerignore:1](.dockerignore#L1), [.gitattributes:1](.gitattributes#L1) | Private/generated-file exclusions and consistent text endings |
| `README.md`, `PROJECT_GUIDE.md` | Setup and this explanation |

Virtual environments, caches, generated reports/stores and Docker volumes are runtime material, not additional authored modules. This guide and README are published; private configuration and runtime data remain excluded.
