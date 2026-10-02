import io
import os
import uuid
from unittest.mock import Mock

import pytest
from langchain_core.runnables import RunnableLambda
from pypdf import PdfWriter

from app.config import Settings
from app.documents import parse_chunks
from app.pipeline import Claim, GeneratedAnswer, Models, Pipeline
from app.storage import Store
from scripts.evaluate import retrieval_metrics


def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, embedding_dimensions=64)


def test_pdf_pages_and_headings(tmp_path):
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for text in ["POLICY", "24 days annual leave"]:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    data = io.BytesIO()
    writer.write(data)
    chunks = parse_chunks(data.getvalue(), "policy.pdf", settings(tmp_path), "hr", "1")
    assert [c["page"] for c in chunks] == [1, 2]
    assert chunks[0]["section"] == "POLICY"


def test_citation_validation_and_abstention(tmp_path):
    config = settings(tmp_path)
    models = Models(config)
    fake_llm = Mock()
    fake_llm.with_structured_output.return_value = RunnableLambda(
        lambda _: GeneratedAnswer(claims=[Claim(text="Invented", source_ids=["S999"])])
    )
    models.llm = fake_llm
    pipeline = Pipeline(config, Mock(), models)
    state = {
        "question": "leave days?",
        "attempts": 1,
        "sufficient": True,
        "context": [
            {
                "id": "c1",
                "text": "24 days",
                "document_id": "d1",
                "filename": "a.txt",
                "page": 1,
                "section": "Leave",
                "version": "1",
            }
        ],
    }
    assert pipeline.answer(state)["result"]["insufficient_evidence"]
    fake_llm.with_structured_output.return_value = RunnableLambda(
        lambda _: GeneratedAnswer(claims=[Claim(text="24 days", source_ids=["S1"])])
    )
    assert pipeline.answer(state)["result"]["citations"][0]["chunk_id"] == "c1"
    fake_llm.with_structured_output.return_value = RunnableLambda(
        lambda _: GeneratedAnswer(insufficient_evidence=True)
    )
    assert pipeline.answer(state)["result"]["insufficient_evidence"]


def test_reranker_changes_order(tmp_path):
    models = Models(settings(tmp_path))
    models.reranker = Mock()
    models.reranker.predict.return_value = Mock(tolist=lambda: [-1, 4])
    ranked = models.rank("leave", [{"id": "a", "text": "expenses"}, {"id": "b", "text": "leave"}])
    assert [c["id"] for c in ranked] == ["b", "a"]


def test_retrieval_metrics():
    assert retrieval_metrics(["a", "b", "c"], ["b", "d"], 3) == {"recall_at_k": 0.5, "reciprocal_rank": 0.5}


def test_embedding_config_change_fails(tmp_path):
    first = Store(settings(tmp_path))
    first.engine.dispose()
    with pytest.raises(ValueError, match="Embedding configuration changed"):
        Store(Settings(_env_file=None, data_dir=tmp_path, embedding_dimensions=128))


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real pgvector integration"
)
def test_postgres_vector_fts_isolation_version_delete(tmp_path):
    config = Settings(
        _env_file=None,
        data_dir=tmp_path,
        storage_backend="postgres",
        database_url=os.getenv("TEST_DATABASE_URL"),
        embedding_dimensions=64,
    )
    store, models = Store(config), Models(config)
    tenant = "test-" + str(uuid.uuid4())
    doc_ids = []
    try:
        for version, number in [("1", "24"), ("2", "32")]:
            chunks = parse_chunks(
                f"Annual leave is {number} days.".encode(), "policy.md", config, "hr", version
            )
            doc = store.ingest(
                tenant, "policy.md", version, "hr", version, chunks, models.embed([c["text"] for c in chunks])
            )
            doc_ids.append(doc["document_id"])
        vector, keyword = store.search(tenant, "annual leave", models.embed(["annual leave"])[0], {}, 5)
        assert vector and keyword
        assert all(c["version"] == "2" for c in vector + keyword)
        assert not store.search("other-" + tenant, "annual leave", models.embed(["annual leave"])[0], {}, 5)[
            0
        ]
        assert (
            store.search(tenant, "annual leave", models.embed(["annual leave"])[0], {"version": "1"}, 5)[0][
                0
            ]["version"]
            == "1"
        )
        assert not store.delete("other-" + tenant, doc_ids[0])
    finally:
        for doc_id in doc_ids:
            store.delete(tenant, doc_id)
        store.engine.dispose()


def test_negative_reranker_score_allows_llm_evidence_decision(tmp_path):
    config = settings(tmp_path).model_copy(update={"reranker_mode": "cross_encoder"})
    models = Mock()
    models.rank.return_value = [
        {
            "id": "c1",
            "text": "The architecture uses FastAPI and PostgreSQL.",
            "document_id": "d1",
            "filename": "ARCHITECTURE.md",
            "page": 1,
            "section": "Architecture",
            "version": "1",
            "rerank_score": -8.5,
        }
    ]
    models.llm.with_structured_output.return_value = RunnableLambda(
        lambda _: GeneratedAnswer(
            claims=[Claim(text="FastAPI and PostgreSQL form the architecture.", source_ids=["S1"])]
        )
    )
    pipeline = Pipeline(config, Mock(), models)
    state = {"question": "How does storage work?", "attempts": 2, "candidates": []}
    state.update(pipeline.select(state))
    assert not state["sufficient"]
    assert pipeline.route(state) == "answer"
    result = pipeline.answer(state)["result"]
    assert not result["insufficient_evidence"]
    assert result["citations"][0]["filename"] == "ARCHITECTURE.md"
    models.llm.with_structured_output.return_value = RunnableLambda(
        lambda _: GeneratedAnswer(insufficient_evidence=True)
    )
    assert pipeline.answer(state)["result"]["reason"] == "model_abstention"


def test_overview_context_covers_sections(tmp_path):
    config = settings(tmp_path).model_copy(update={"context_k": 2, "reranker_mode": "cross_encoder"})
    models = Mock()
    models.rank.return_value = [
        {
            "id": "a",
            "document_id": "doc",
            "section": "Storage",
            "text": "SQL stores documents and vectors.",
            "rerank_score": -1,
        },
        {
            "id": "b",
            "document_id": "doc",
            "section": "Storage",
            "text": "SQL keeps document versions too.",
            "rerank_score": -2,
        },
        {
            "id": "c",
            "document_id": "doc",
            "section": "Pipeline",
            "text": "Upload, embed, retrieve, rerank, answer with citations.",
            "rerank_score": -4,
        },
    ]
    pipeline = Pipeline(config, Mock(), models)
    selected = pipeline.select({"question": "Explain the architecture", "candidates": []})
    assert [c["section"] for c in selected["context"]] == ["Storage", "Pipeline"]
    assert selected["sufficient"]
