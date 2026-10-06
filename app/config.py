from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    app_env: Literal["development", "production"] = "development"
    storage_backend: Literal["chroma", "postgres"] = "chroma"
    model_mode: Literal["demo", "openai", "ollama", "gemini"] = "demo"
    data_dir: Path = Path("data")
    api_keys: dict[str, str] = Field(default={"local-change-me": "demo"}, repr=False)
    openai_api_key: str = Field(default="", repr=False)
    gemini_api_key: str = Field(default="", repr=False)
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = Field(default=60, gt=0, le=600)
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
    database_url: str = Field(default="", repr=False)
    reranker_mode: Literal["lexical", "cross_encoder"] = "lexical"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    trace_content: bool = False
    langsmith_tracing: bool = False
    langsmith_api_key: str = Field(default="", repr=False)
    langsmith_project: str = "production-rag"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_workspace_id: str = ""
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_document_chars: int = Field(default=2_000_000, gt=0)
    max_chunks: int = Field(default=5000, gt=0)
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=150, ge=0)
    candidate_k: int = Field(default=20, gt=0)
    context_k: int = Field(default=5, gt=0)
    context_chars: int = Field(default=12000, gt=0)
    max_attempts: int = 2
    cache_ttl_seconds: int = Field(default=300, ge=0)
    rate_limit_per_minute: int = Field(default=60, gt=0)

    @property
    def embedding_mode(self):
        """Gemini changes generation only; retain the existing local embedding space."""
        return "ollama" if self.model_mode == "gemini" else self.model_mode

    @model_validator(mode="after")
    def validate_setup(self):
        if self.chunk_overlap >= self.chunk_size or self.max_attempts not in range(1, 4):
            raise ValueError("Invalid chunk overlap or retrieval attempt limit")
        if not self.api_keys:
            raise ValueError("Configure at least one API key")
        if any(not key.strip() or not tenant.strip() for key, tenant in self.api_keys.items()):
            raise ValueError("Application keys and tenant IDs must not be blank")
        if self.model_mode == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        if self.model_mode == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required")
        if self.langsmith_tracing and not self.langsmith_api_key:
            raise ValueError("LANGSMITH_API_KEY is required when tracing is enabled")
        if self.embedding_mode == "ollama":
            from urllib.parse import urlparse

            url = urlparse(self.ollama_base_url)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
                raise ValueError("OLLAMA_BASE_URL must be an HTTP(S) URL without credentials")
            local_models = [self.ollama_embedding_model]
            if self.model_mode == "ollama":
                local_models.append(self.ollama_chat_model)
            if any("cloud" in model.lower() for model in local_models):
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
