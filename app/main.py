"""FastAPI boundary: authentication, limits, lifecycle, cache, and safe errors."""

import hashlib
import hmac
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import Settings
from app.documents import parse_chunks
from app.pipeline import Models, Pipeline
from app.storage import Store

logger = logging.getLogger("rag")
REQUESTS = Counter("rag_requests_total", "API requests", ["method", "status"])
LATENCY = Histogram("rag_request_seconds", "API latency")
ROOT = Path(__file__).resolve().parents[1]


class Filters(BaseModel):
    category: str | None = Field(default=None, max_length=100)
    filename: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=100)
    document_ids: list[str] = Field(default_factory=list, max_length=50)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    filters: Filters = Field(default_factory=Filters)


class Cache:
    def __init__(self, ttl):
        self.ttl, self.values, self.lock = ttl, {}, threading.Lock()

    def get(self, key):
        with self.lock:
            item = self.values.get(key)
            if item and time.monotonic() - item[0] < self.ttl:
                return dict(item[1], cached=True)
            self.values.pop(key, None)

    def put(self, key, value):
        with self.lock:
            if len(self.values) >= 1000:
                self.values.clear()
            self.values[key] = (time.monotonic(), value)


def create_app(settings=None):
    settings = settings or Settings()
    os.environ["LANGSMITH_TRACING"] = str(settings.langsmith_tracing).lower()
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    # Tracing can expose document content. Default to redacted traces even if tracing is enabled.
    os.environ["LANGSMITH_HIDE_INPUTS"] = str(not settings.trace_content).lower()
    os.environ["LANGSMITH_HIDE_OUTPUTS"] = str(not settings.trace_content).lower()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(settings)
        app.state.models = Models(settings)
        app.state.pipeline = Pipeline(settings, app.state.store, app.state.models)
        yield
        app.state.store.engine.dispose()

    app = FastAPI(title="Production RAG", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    cache = Cache(settings.cache_ttl_seconds)
    rate = defaultdict(deque)
    rate_lock = threading.Lock()
    mutation_lock = threading.RLock()
    auth_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def tenant(key: str | None = Depends(auth_header)):
        selected = None
        for secret, tenant_id in settings.api_keys.items():
            if key and hmac.compare_digest(key.encode(), secret.encode()):
                selected = tenant_id
        if selected is None:
            raise HTTPException(401, "Invalid or missing API key")
        with rate_lock:
            now = time.monotonic()
            queue = rate[selected]
            while queue and queue[0] <= now - 60:
                queue.popleft()
            if len(queue) >= settings.rate_limit_per_minute:
                raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
            queue.append(now)
        return selected

    @app.middleware("http")
    async def instrument(request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logger.error("request_failed request_id=%s path=%s", request_id, request.url.path)
            response = JSONResponse(
                status_code=503,
                content={"detail": "Service temporarily unavailable", "request_id": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        REQUESTS.labels(request.method, str(response.status_code)).inc()
        LATENCY.observe(time.monotonic() - start)
        return response

    @app.get("/", include_in_schema=False)
    def ui():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        try:
            with app.state.store.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            if app.state.store.chroma is not None:
                app.state.store.chroma.count()
            app.state.models.check_available()
        except Exception as exc:
            raise HTTPException(503, "Storage or local model service unavailable") from exc
        return {"status": "ready", "mode": settings.model_mode, "storage": settings.storage_backend}

    @app.get("/metrics", dependencies=[Depends(tenant)])
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/documents", status_code=201)
    def upload(
        file: UploadFile = File(...),
        version: str = Form("1", max_length=100),
        category: str = Form("general", max_length=100),
        tenant_id: str = Depends(tenant),
    ):
        data = file.file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, "File exceeds upload limit")
        if not data:
            raise HTTPException(422, "File is empty")
        filename = Path((file.filename or "document.txt").replace("\\", "/")).name
        if len(filename) > 255:
            raise HTTPException(422, "Filename is too long")
        try:
            chunks = parse_chunks(data, filename, settings, category, version)
        except Exception as exc:
            raise HTTPException(422, "Could not parse document: " + str(exc)[:200]) from exc
        embeddings = app.state.models.embed([c["text"] for c in chunks])
        with mutation_lock:
            try:
                result = app.state.store.ingest(
                    tenant_id,
                    filename,
                    version,
                    category,
                    hashlib.sha256(data).hexdigest(),
                    chunks,
                    embeddings,
                )
                return dict(result, filename=filename, version=version, category=category)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.get("/documents")
    def documents(tenant_id: str = Depends(tenant)):
        return app.state.store.list_documents(tenant_id)

    @app.delete("/documents/{document_id}")
    def delete(document_id: str, tenant_id: str = Depends(tenant)):
        with mutation_lock:
            if not app.state.store.delete(tenant_id, document_id):
                raise HTTPException(404, "Document not found")
        return {"deleted": True}

    @app.post("/query")
    def query(body: Question, tenant_id: str = Depends(tenant)):
        filters = body.filters.model_dump(exclude_none=True)
        # Hold through answer so local delete/version updates cannot invalidate in-flight citations.
        # For multiple production replicas, use document revisions plus transaction-level snapshots.
        with mutation_lock:
            key = json.dumps(
                [tenant_id, body.model_dump(), app.state.store.revision(tenant_id)], sort_keys=True
            )
            hit = cache.get(key)
            if hit:
                return hit
            result = app.state.pipeline.ask(tenant_id, body.question, filters)
            cache.put(key, result)
            return dict(result, cached=False)

    return app
