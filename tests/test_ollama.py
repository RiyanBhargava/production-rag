from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pipeline import Models


def local_settings(tmp_path, **options):
    return Settings(
        _env_file=None,
        model_mode="ollama",
        data_dir=tmp_path,
        embedding_dimensions=options.pop("embedding_dimensions", 3),
        **options,
    )


def test_ollama_prefixes_and_dimensions(tmp_path, monkeypatch):
    embedder = Mock()
    embedder.embed_documents.side_effect = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]
    embedder.embed_query.return_value = [0.0, 1.0, 0.0]
    monkeypatch.setattr("app.pipeline.OllamaEmbeddings", Mock(return_value=embedder))
    monkeypatch.setattr("app.pipeline.ChatOllama", Mock())
    monkeypatch.setattr(Models, "check_available", lambda self: None)
    models = Models(local_settings(tmp_path))
    assert models.embed(["document text"]) == [[1.0, 0.0, 0.0]]
    embedder.embed_documents.assert_called_with(["search_document: document text"])
    assert models.embed_query("a question") == [0.0, 1.0, 0.0]
    embedder.embed_query.assert_called_once_with("search_query: a question")
    embedder.embed_query.return_value = [0.0, 1.0]
    with pytest.raises(ValueError, match="EMBEDDING_DIMENSIONS"):
        models.embed_query("bad dimension")
    with pytest.raises(ValueError):
        models.validate_vectors([[float("nan"), 0.0, 1.0]], 1)


def test_missing_ollama_model(tmp_path, monkeypatch):
    response = Mock()
    response.json.return_value = {"models": [{"name": "llama3:latest"}]}
    monkeypatch.setattr("app.pipeline.httpx.get", Mock(return_value=response))
    model = Models.__new__(Models)
    model.settings = local_settings(tmp_path)
    with pytest.raises(ValueError, match="ollama pull nomic-embed-text"):
        model.check_available()
    monkeypatch.setattr("app.pipeline.httpx.get", Mock(side_effect=httpx.ConnectError("offline")))
    with pytest.raises(RuntimeError, match="Cannot reach Ollama"):
        model.check_available()


def test_local_production_and_cloud_rejection(tmp_path):
    settings = local_settings(
        tmp_path,
        app_env="production",
        storage_backend="postgres",
        database_url="postgresql+psycopg://localhost/rag",
        reranker_mode="cross_encoder",
        api_keys={"x" * 40: "tenant"},
    )
    assert settings.model_mode == "ollama" and not settings.openai_api_key
    with pytest.raises(ValueError, match="cloud"):
        local_settings(tmp_path, ollama_chat_model="qwen3-coder:480b-cloud")


def test_readiness_checks_local_service(tmp_path, monkeypatch):
    # Exercise the API check using a demo store without starting an external model server.
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_dimensions=64)
    with TestClient(create_app(settings)) as client:
        monkeypatch.setattr(
            client.app.state.models, "check_available", Mock(side_effect=RuntimeError("offline"))
        )
        assert client.get("/health/ready").status_code == 503
