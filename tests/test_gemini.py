from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.config import Settings
from app.pipeline import Models, Pipeline
from app.storage import Store


def config(tmp_path, **options):
    return Settings(
        _env_file=None,
        model_mode="gemini",
        gemini_api_key="test-only-not-real",
        embedding_dimensions=3,
        data_dir=tmp_path,
        **options,
    )


def test_gemini_uses_local_embeddings_and_preserves_store(tmp_path, monkeypatch):
    local = Settings(_env_file=None, model_mode="ollama", embedding_dimensions=3, data_dir=tmp_path)
    store = Store(local)
    original_collection = store.chroma.name
    store.engine.dispose()
    switched = Store(config(tmp_path))
    assert switched.chroma.name == original_collection
    switched.engine.dispose()

    embedder = Mock()
    embedder.embed_documents.side_effect = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]
    embedder.embed_query.return_value = [0.0, 1.0, 0.0]
    monkeypatch.setattr("app.pipeline.OllamaEmbeddings", Mock(return_value=embedder))
    chat_factory = Mock()
    monkeypatch.setattr("app.pipeline.ChatGoogleGenerativeAI", chat_factory)
    monkeypatch.setattr("app.pipeline.ChatOllama", Mock(side_effect=AssertionError("Not needed")))
    monkeypatch.setattr(Models, "check_available", lambda self: None)
    models = Models(config(tmp_path))
    models.embed(["a passage"])
    embedder.embed_documents.assert_called_with(["search_document: a passage"])
    models.embed_query("a question")
    embedder.embed_query.assert_called_once_with("search_query: a question")
    assert chat_factory.call_args.kwargs["vertexai"] is False
    assert chat_factory.call_args.kwargs["api_key"] == "test-only-not-real"


def test_gemini_readiness_requires_embedding_model_only(tmp_path, monkeypatch):
    model = Models.__new__(Models)
    model.settings = config(tmp_path)
    response = Mock()
    response.json.return_value = {"models": [{"name": "nomic-embed-text:latest"}]}
    monkeypatch.setattr("app.pipeline.httpx.get", Mock(return_value=response))
    model.check_available()


def test_gemini_schema_and_content_block_rewrite(tmp_path):
    llm = Mock()

    def structured(schema, **options):
        assert options == {"method": "json_schema"}
        assert schema.model_json_schema()["$defs"]["EvidenceClaim"]["properties"]["source_ids"]["items"] == {
            "enum": ["S1"],
            "type": "string",
        }
        return RunnableLambda(
            lambda _: schema(claims=[{"text": "24 days", "source_ids": ["S1"]}], insufficient_evidence=False)
        )

    llm.with_structured_output.side_effect = structured
    models = Mock(llm=llm)
    pipeline = Pipeline(config(tmp_path), Mock(), models)
    result = pipeline.answer(
        {
            "question": "Leave?",
            "attempts": 1,
            "sufficient": True,
            "context": [
                {
                    "id": "c1",
                    "document_id": "d1",
                    "filename": "policy.txt",
                    "page": 1,
                    "section": "Leave",
                    "version": "1",
                    "text": "24 days",
                }
            ],
        }
    )["result"]
    assert result["mode"] == "gemini" and result["citations"][0]["chunk_id"] == "c1"
    models.llm = RunnableLambda(lambda _: AIMessage(content=[{"type": "text", "text": "annual leave days"}]))
    assert pipeline.rewrite({"question": "Leave?"})["query"] == "annual leave days"


def test_gemini_and_tracing_require_separate_keys():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        Settings(_env_file=None, model_mode="gemini")
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        Settings(_env_file=None, langsmith_tracing=True)
    production = Settings(
        _env_file=None,
        model_mode="gemini",
        gemini_api_key="test-only-not-real",
        app_env="production",
        storage_backend="postgres",
        database_url="postgresql+psycopg://localhost/test",
        reranker_mode="cross_encoder",
        api_keys={"x" * 40: "tenant"},
    )
    assert production.embedding_mode == "ollama" and not production.openai_api_key
