"""Verify local embeddings and either Ollama or Gemini answers in an isolated store."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def main():
    config = Settings()
    if config.model_mode not in {"ollama", "gemini"}:
        raise ValueError("Configure MODEL_MODE=ollama or gemini before running this check")
    root = Path(__file__).resolve().parents[1]
    records = []
    if len(sys.argv) == 1:
        # Chroma holds native file handles until process exit on Windows.
        # Run inference in a child, then clean up after those handles are released.
        with tempfile.TemporaryDirectory(prefix="rag-local-check-") as directory:
            resolved = Path(directory).resolve()
            assert resolved.parent == Path(tempfile.gettempdir()).resolve()
            assert resolved.name.startswith("rag-local-check-")
            subprocess.run([sys.executable, "-m", "scripts.verify_local", str(resolved)], check=True)
        return
    config = config.model_copy(
        update={"data_dir": Path(sys.argv[1]), "storage_backend": "chroma", "app_env": "development"}
    )
    with TestClient(create_app(config)) as client:
        headers = {"X-API-Key": next(iter(config.api_keys))}
        upload = client.post(
            "/documents",
            headers=headers,
            files={
                "file": (
                    "employee-policy.md",
                    (root / "samples/employee-policy.txt").read_bytes(),
                    "text/markdown",
                )
            },
        )
        assert upload.status_code == 201, upload.text
        for question, expected in [
            ("How many days of paid annual leave do employees receive each year?", "24"),
            ("What does SEC-401 mean?", "expired"),
            ("What is the company policy on flying to Mars?", None),
        ]:
            started = time.monotonic()
            response = client.post("/query", headers=headers, json={"question": question})
            assert response.status_code == 200, response.text
            answer = response.json()
            assert answer["mode"] == config.model_mode
            if expected:
                assert not answer["insufficient_evidence"], answer
                assert expected in answer["answer"].lower(), answer
                assert answer["citations"] and all(
                    c["filename"] == "employee-policy.md" for c in answer["citations"]
                )
            else:
                assert answer["insufficient_evidence"] and not answer["citations"], answer
            records.append({"question": question, "seconds": round(time.monotonic() - started, 2), **answer})
            print(json.dumps(records[-1], ensure_ascii=False), flush=True)
        assert client.get("/health/ready").status_code == 200
    output = (
        root
        / "data"
        / (
            "gemini-model-verification.json"
            if config.model_mode == "gemini"
            else "local-model-verification.json"
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Passed. Report: {output}")


if __name__ == "__main__":
    main()
