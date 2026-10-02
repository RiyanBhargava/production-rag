import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pipeline import reciprocal_rank_fusion


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        embedding_dimensions=64,
        api_keys={"alice-secret": "alice", "bob-secret": "bob"},
    )
    with TestClient(create_app(settings)) as c:
        yield c


def upload(client, key="alice-secret", content="Employees receive 24 days of annual leave.", version="1"):
    return client.post(
        "/documents",
        headers={"X-API-Key": key},
        files={"file": ("policy.md", content.encode(), "text/markdown")},
        data={"version": version},
    )


def ask(client, key="alice-secret", question="How many days of annual leave?", filters=None):
    return client.post(
        "/query", headers={"X-API-Key": key}, json={"question": question, "filters": filters or {}}
    )


def test_upload_query_cache_and_citations(client):
    result = upload(client)
    assert result.status_code == 201
    response = ask(client)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert "24" in answer["answer"]
    assert answer["citations"][0]["page"] == 1
    assert answer["citations"][0]["document_id"] == result.json()["document_id"]
    assert not answer["cached"]
    assert ask(client).json()["cached"]


def test_isolation_and_delete(client):
    doc = upload(client).json()["document_id"]
    assert ask(client, key="bob-secret").json()["insufficient_evidence"]
    assert client.get("/documents", headers={"X-API-Key": "bob-secret"}).json() == []
    assert client.delete("/documents/" + doc, headers={"X-API-Key": "bob-secret"}).status_code == 404
    assert ask(client).json()["citations"]
    assert client.delete("/documents/" + doc, headers={"X-API-Key": "alice-secret"}).status_code == 200
    assert ask(client).json()["insufficient_evidence"]


def test_versions_dedup_and_filters(client):
    assert upload(client).status_code == 201
    assert upload(client).json()["deduplicated"]
    assert upload(client, content="Changed content").status_code == 409
    assert (
        upload(client, content="Employees receive 32 days of annual leave.", version="2").status_code == 201
    )
    response = ask(client).json()
    assert "32" in response["answer"] and "24" not in response["answer"]
    assert ask(client, filters={"version": "1"}).json()["citations"][0]["version"] == "1"
    assert ask(client, filters={"category": "nonexistent"}).json()["insufficient_evidence"]


def test_auth_parse_and_steps(client):
    assert client.get("/documents").status_code == 401
    assert client.get("/documents", headers={"X-API-Key": "wrong"}).status_code == 401
    assert upload(client, content="").status_code == 422
    bad = client.post(
        "/documents",
        headers={"X-API-Key": "alice-secret"},
        files={"file": ("bad.pdf", b"not a pdf", "application/pdf")},
    )
    assert bad.status_code == 422
    answer = ask(client, question="Unrelated quantum astrophysics?").json()
    assert answer["insufficient_evidence"] and answer["attempts"] == 2


def test_fusion():
    a, b = {"id": "a"}, {"id": "b"}
    fused = reciprocal_rank_fusion([a, b], [b])
    assert [c["id"] for c in fused] == ["b", "a"]


def test_production_fails_closed():
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="production")


def test_upload_limits_and_rate_limit(tmp_path):
    config = Settings(
        _env_file=None,
        data_dir=tmp_path,
        embedding_dimensions=64,
        max_upload_bytes=16,
        rate_limit_per_minute=2,
    )
    with TestClient(create_app(config)) as client:
        headers = {"X-API-Key": "local-change-me"}
        assert (
            client.post("/documents", headers=headers, files={"file": ("large.txt", b"x" * 17)}).status_code
            == 413
        )
        assert client.get("/documents", headers=headers).status_code == 200
        assert client.get("/documents", headers=headers).status_code == 429


def test_cache_is_tenant_scoped(client):
    upload(client, content="Employees receive 24 days of annual leave.")
    upload(client, key="bob-secret", content="Employees receive 12 days of annual leave.")
    assert "24" in ask(client).json()["answer"]
    assert "12" in ask(client, key="bob-secret").json()["answer"]
    assert "24" not in ask(client, key="bob-secret").json()["answer"]
