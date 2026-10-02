from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: Literal["development", "production"] = "development"
    storage_backend: Literal["chroma", "postgres"] = "chroma"
    model_mode: Literal["demo", "openai", "ollama"] = "demo"
    data_dir: Path = Path("data")
    api_keys: dict[str, str] = {"local-change-me": "demo"}
    openai_api_key: str = ""
    chat_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = "llama3:latest"
    ollama_embedding_model: str = "nomic-embed-text:latest"
    ollama_timeout_seconds: float = Field(default=120, gt=0, le=600)
    ollama_context_tokens: int = Field(default=8192, ge=4096)
    ollama_document_prefix: str = "search_document: "
    ollama_query_prefix: str = "search_query: "
    database_url: str = ""
    reranker_mode: Literal["lexical", "cross_encoder"] = "lexical"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    trace_content: bool = False
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "production-rag"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_document_chars: int = 2_000_000
    max_chunks: int = 5000
    chunk_size: int = 1000
    chunk_overlap: int = 150
    candidate_k: int = 20
    context_k: int = 5
    context_chars: int = 12000
    max_attempts: int = 2
    cache_ttl_seconds: int = 300
    rate_limit_per_minute: int = 60

    @model_validator(mode="after")
    def validate_setup(self):
        if self.chunk_overlap >= self.chunk_size or self.max_attempts not in range(1, 4):
            raise ValueError("Invalid chunk overlap or retrieval attempt limit")
        if not self.api_keys:
            raise ValueError("Configure at least one API key")
        if self.model_mode == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        if self.model_mode == "ollama":
            from urllib.parse import urlparse

            url = urlparse(self.ollama_base_url)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
                raise ValueError("OLLAMA_BASE_URL must be an HTTP(S) URL without credentials")
            if any(
                "cloud" in model.lower() for model in (self.ollama_chat_model, self.ollama_embedding_model)
            ):
                raise ValueError("Ollama mode requires local model tags, not cloud models")
        if self.storage_backend == "postgres" and not self.database_url:
            raise ValueError("DATABASE_URL is required")
        if self.app_env == "production":
            if (
                self.model_mode == "demo"
                or self.storage_backend != "postgres"
                or self.reranker_mode != "cross_encoder"
            ):
                raise ValueError("Production requires real models, PostgreSQL and cross_encoder reranking")
            if any(len(k) < 32 or k == "local-change-me" for k in self.api_keys):
                raise ValueError("Production API keys must be random, at least 32 characters")
        return self
