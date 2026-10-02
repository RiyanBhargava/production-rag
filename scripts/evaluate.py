"""Evaluate retrieval and generation separately on your own labeled JSONL dataset."""

import argparse
import json
import time
from pathlib import Path

from app.config import Settings
from app.pipeline import Models, Pipeline, reciprocal_rank_fusion
from app.storage import Store


def retrieval_metrics(ranked_ids, relevant_ids, k):
    relevant = set(relevant_ids)
    if not relevant:
        raise ValueError("Retrieval labels need at least one relevant chunk ID")
    hits = [i for i, chunk_id in enumerate(ranked_ids[:k], 1) if chunk_id in relevant]
    return {
        "recall_at_k": len(set(ranked_ids[:k]) & relevant) / len(relevant),
        "reciprocal_rank": 1 / hits[0] if hits else 0.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--generate", action="store_true", help="Also call the answer pipeline (may incur API costs)"
    )
    parser.add_argument("--output", type=Path, default=Path("data/evaluation.json"))
    args = parser.parse_args()
    settings = Settings()
    store = Store(settings)
    models = Models(settings)
    pipeline = Pipeline(settings, store, models)
    records = []
    for line in args.dataset.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        question, filters = item["question"], item.get("filters", {})
        start = time.monotonic()
        semantic, keyword = store.search(
            args.tenant, question, models.embed_query(question), filters, settings.candidate_k
        )
        fused = reciprocal_rank_fusion(semantic, keyword)
        ranked = models.rank(question, fused)
        record = {"question": question, "retrieval_seconds": time.monotonic() - start}
        for name, results in [
            ("semantic", semantic),
            ("keyword", keyword),
            ("fused", fused),
            ("reranked", ranked),
        ]:
            record[name] = retrieval_metrics([c["id"] for c in results], item["relevant_chunk_ids"], args.k)
        if args.generate:
            start = time.monotonic()
            answer = pipeline.ask(args.tenant, question, filters)
            expected = item.get("expected_answer_terms", [])
            record.update(
                answer=answer,
                generation_seconds=time.monotonic() - start,
                answer_term_recall=(
                    sum(term.lower() in answer["answer"].lower() for term in expected) / len(expected)
                    if expected
                    else None
                ),
                abstention_correct=(answer["insufficient_evidence"] == item.get("expect_abstention", False)),
            )
            # Term recall is only a smoke metric; human review establishes factual support and completeness.
        records.append(record)
    if not records:
        raise ValueError("Dataset is empty")
    summary = {
        name: {
            "recall_at_k": sum(r[name]["recall_at_k"] for r in records) / len(records),
            "mrr": sum(r[name]["reciprocal_rank"] for r in records) / len(records),
        }
        for name in ("semantic", "keyword", "fused", "reranked")
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"k": args.k, "summary": summary, "records": records}, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    store.engine.dispose()


if __name__ == "__main__":
    main()
