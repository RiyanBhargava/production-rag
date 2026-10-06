import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_settings_do_not_print_secrets():
    secret = "private-test-key-never-print"
    settings = Settings(_env_file=None, gemini_api_key=secret, api_keys={secret: "tenant"})
    assert secret not in repr(settings)
    with pytest.raises(ValueError) as error:
        Settings(_env_file=None, api_keys={secret: " "})
    assert secret not in str(error.value)
    with pytest.raises(ValueError):
        Settings(_env_file=None, max_upload_bytes=-1)


def test_parser_errors_and_browser_headers(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_dimensions=64)
    with TestClient(create_app(settings)) as client:
        private_text = "private-document-content"

        def broken_parser(*args):
            raise RuntimeError(private_text)

        monkeypatch.setattr("app.main.parse_chunks", broken_parser)
        response = client.post(
            "/documents",
            headers={"X-API-Key": "local-change-me"},
            files={"file": ("policy.txt", b"text")},
        )
        assert response.status_code == 422 and private_text not in response.text
        page = client.get("/")
        assert "script-src 'self'" in page.headers["Content-Security-Policy"]
        assert page.headers["X-Frame-Options"] == "DENY"
        assert page.headers["Referrer-Policy"] == "no-referrer"
        assert client.get("/static/app.js").status_code == 200
        # Interactive Swagger documentation needs its own external assets.
        assert "Content-Security-Policy" not in client.get("/docs").headers
