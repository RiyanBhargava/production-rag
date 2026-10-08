"""Runnable sample evaluation; isolated from your real document store."""

import json
import os
from pathlib import Path

from app.config import Settings
from app.documents import parse_chunks
from app.pipeline import Models
from app.storage import Store


def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / "data" / "sample-evaluation"
    config = Settings(
        _env_file=None,
        data_dir=directory,
        embedding_dimensions=64,
        model_mode="demo",
        storage_backend="chroma",
    )
    store, models = Store(config), Models(config)
    content = (root / "samples" / "employee-policy.txt").read_bytes()
    chunks = parse_chunks(content, "employee-policy.md", config, "general", "1")
    import hashlib

    store.ingest(
        "demo",
        "employee-policy.md",
        "1",
        "general",
        hashlib.sha256(content).hexdigest(),
        chunks,
        models.embed([c["text"] for c in chunks]),
    )
    semantic, keyword = store.search("demo", "annual leave", models.embed_query("annual leave"), {}, 10)
    all_chunks = {c["id"]: c for c in semantic + keyword}
    examples = [
        ("How many days of annual leave do employees receive?", "24 days", ["24"]),
        ("What does SEC-401 mean?", "SEC-401", ["certificate"]),
        ("When must expense reports be submitted?", "30 days", ["30"]),
    ]
    labels = []
    for question, phrase, terms in examples:
        labels.append(
            {
                "question": question,
                "relevant_chunk_ids": [c["id"] for c in all_chunks.values() if phrase in c["text"]],
                "expected_answer_terms": terms,
            }
        )
    dataset = directory / "questions.jsonl"
    dataset.write_text("\n".join(json.dumps(r) for r in labels), encoding="utf-8")
    store.engine.dispose()
    # Run CLI in a subprocess with explicit isolated settings, regardless of the user's .env.
    import subprocess
    import sys

    env = dict(
        os.environ,
        DATA_DIR=str(directory),
        MODEL_MODE="demo",
        STORAGE_BACKEND="chroma",
        EMBEDDING_DIMENSIONS="64",
        RERANKER_MODE="lexical",
        APP_ENV="development",
        MODEL_ROUTING_ENABLED="false",
        LANGSMITH_TRACING="false",
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.evaluate",
            str(dataset),
            "--tenant",
            "demo",
            "--generate",
            "--output",
            str(directory / "report.json"),
        ],
        env=env,
        check=True,
    )
    print(f"Sample report: {directory / 'report.json'}")


if __name__ == "__main__":
    main()
