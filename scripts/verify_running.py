"""Verify the running Docker app and real local model routes without printing keys."""

import argparse
import json
import time
from pathlib import Path

import httpx

from app.config import Settings

SAMPLES = {
    "trading": (
        "model-routing-demo.txt",
        "4",
        "demo",
        [
            ("How many minutes does support have to acknowledge a withdrawal complaint?", ["15"], "light", 1),
            (
                "Compare standard and security-flagged withdrawal handling. State the standard review target "
                "after verification and what support does if review exceeds 24 hours. Who can clear a "
                "security hold, and what must support not do? State the complaint acknowledgement and "
                "progress-update deadlines. Cite the relevant sections.",
                ["24", "payments", "security", "verification", "15", "2"],
                "strong",
                3,
            ),
            (
                "How many minutes after a successful provider deposit is missing from account activity "
                "should support escalate to payments operations?",
                ["60"],
                "light",
                1,
            ),
            (
                "Compare platform outage triage and outage customer updates: how many independent "
                "reports in what time window trigger escalation, and how often are customer status "
                "updates published during a confirmed outage? Cite both sections.",
                ["3", "10", "30"],
                "strong",
                2,
            ),
            ("What is the company policy on flying to Mars?", [], "light", 0),
        ],
    ),
    "policy": (
        "employee-policy.txt",
        "1",
        "hr",
        [
            ("How many days of paid annual leave do employees receive each year?", ["24"], "light", 1),
            ("What does SEC-401 mean?", ["expired"], "light", 1),
            ("Summarize annual leave, security and expense requirements.", ["24"], "strong", 1),
            ("What is the company policy on flying to Mars?", [], "light", 0),
        ],
    ),
}


def check_sample(client, root, headers, settings, name):
    filename, version, category, cases = SAMPLES[name]
    upload = client.post(
        "/documents",
        headers=headers,
        files={"file": (filename, (root / "samples" / filename).read_bytes())},
        data={"version": version, "category": category},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["document_id"]
    if name == "trading" and not upload.json()["deduplicated"]:
        assert upload.json()["chunks"] >= 18, upload.json()
    print(
        json.dumps(
            {
                "sample": name,
                "version": version,
                "new_chunks": upload.json()["chunks"],
                "deduplicated": upload.json()["deduplicated"],
            }
        ),
        flush=True,
    )
    records = []
    for question, terms, tier, min_citations in cases:
        body = {
            "question": question,
            "filters": {"filename": filename, "category": category, "version": version},
        }
        started = time.monotonic()
        response = client.post("/query", headers=headers, json=body)
        response.raise_for_status()
        answer = response.json()
        if settings.model_routing_enabled:
            assert answer["routing"]["tier"] == tier, answer
            assert answer["model_used"] in {settings.ollama_light_model, settings.ollama_chat_model}, answer
            if tier == "strong":
                assert answer["model_used"] == settings.ollama_chat_model, answer
        if terms:
            assert not answer["insufficient_evidence"] and answer["citations"], answer
            assert all(term in answer["answer"].lower() for term in terms), answer
            assert all(c["document_id"] == document_id for c in answer["citations"]), answer
            assert len({c["chunk_id"] for c in answer["citations"]}) >= min_citations, answer
            if min_citations > 1:
                assert len({c["section"] for c in answer["citations"]}) >= min_citations, answer
        else:
            assert answer["insufficient_evidence"] and not answer["citations"], answer
        record = dict(sample=name, question=question, seconds=round(time.monotonic() - started, 2), **answer)
        records.append(record)
        print(
            json.dumps(
                {
                    **{
                        k: record[k]
                        for k in ["sample", "question", "answer", "model_used", "routing", "seconds"]
                    },
                    "citation_sections": [c["section"] for c in answer["citations"]],
                }
            ),
            flush=True,
        )
        cached = client.post("/query", headers=headers, json=body)
        assert cached.status_code == 200 and cached.json()["cached"], cached.text
    documents = client.get("/documents", headers=headers)
    documents.raise_for_status()
    assert any(d["id"] == document_id for d in documents.json())
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", choices=["all", *SAMPLES], default="all")
    args = parser.parse_args()
    settings = Settings()
    root = Path(__file__).resolve().parents[1]
    headers = {"X-API-Key": next(iter(settings.api_keys))}
    records = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=600) as client:
        for attempt in range(30):
            try:
                health = client.get("/health/ready")
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        else:
            raise RuntimeError("API did not become ready within 60 seconds")
        assert health.json() == {"status": "ready", "mode": "ollama", "storage": "postgres"}
        for path in ["/", "/static/app.js", "/static/styles.css", "/docs", "/openapi.json"]:
            assert client.get(path).status_code == 200, path
        assert client.get("/documents").status_code == 401
        for name in SAMPLES if args.sample == "all" else [args.sample]:
            records.extend(check_sample(client, root, headers, settings, name))
        assert client.get("/metrics", headers=headers).status_code == 200
    report = root / "data/running-stack-verification.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Passed. Report: {report}")


if __name__ == "__main__":
    main()
