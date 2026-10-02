"""SQL is authoritative. Chroma is a rebuildable local vector index."""

import json
import threading
import uuid
from datetime import datetime, timezone

from rank_bm25 import BM25Okapi
from sqlalchemy import create_engine, text

from app.documents import tokenize


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.pg = settings.storage_backend == "postgres"
        url = settings.database_url if self.pg else f"sqlite:///{settings.data_dir / 'catalog.db'}"
        self.engine = create_engine(url, pool_pre_ping=True)
        with self.engine.begin() as conn:
            if self.pg:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text("""CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, filename TEXT NOT NULL,
                category TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL,
                active BOOLEAN NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(tenant, filename, version))""")
            )
            vector_type = f"vector({settings.embedding_dimensions})" if self.pg else "TEXT"
            conn.execute(
                text(f"""CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                tenant TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL,
                embedding {vector_type} NOT NULL)""")
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS chunks_tenant ON chunks(tenant)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS documents_tenant ON documents(tenant, active)"))
            if self.pg:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS chunks_vector ON chunks USING hnsw (embedding vector_cosine_ops)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS chunks_fts ON chunks USING gin (to_tsvector('english', content))"
                    )
                )
                # No direct access through Supabase's public REST API; backend uses a private DB role.
                conn.execute(text("ALTER TABLE documents ENABLE ROW LEVEL SECURITY"))
                conn.execute(text("ALTER TABLE chunks ENABLE ROW LEVEL SECURITY"))
        self.check_fingerprint()
        self.chroma = None
        if not self.pg:
            import chromadb

            client = chromadb.PersistentClient(path=str(settings.data_dir / "chroma"))
            namespace = f"chunks-{settings.embedding_mode}-{settings.embedding_dimensions}"
            self.chroma = client.get_or_create_collection(namespace, metadata={"hnsw:space": "cosine"})
            self.rebuild_index()

    def check_fingerprint(self):
        fingerprint = json.dumps(
            (
                [
                    self.settings.embedding_mode,
                    self.settings.ollama_embedding_model,
                    self.settings.embedding_dimensions,
                    self.settings.ollama_document_prefix,
                    self.settings.ollama_query_prefix,
                ]
                if self.settings.embedding_mode == "ollama"
                else [
                    self.settings.embedding_mode,
                    self.settings.embedding_model,
                    self.settings.embedding_dimensions,
                ]
            )
        )
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS rag_config (id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL)"
                )
            )
            old = conn.execute(text("SELECT fingerprint FROM rag_config WHERE id=1")).scalar()
            if old and old != fingerprint:
                raise ValueError(
                    "Embedding configuration changed. Use a new database/data directory and re-ingest."
                )
            if not old:
                conn.execute(text("INSERT INTO rag_config VALUES (1, :f)"), {"f": fingerprint})

    def rebuild_index(self):
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT id, tenant, embedding FROM chunks")).mappings().all()
        # Recover committed uploads after a process crash between SQL commit and index write.
        for start in range(0, len(rows), 500):
            batch = rows[start : start + 500]
            self.chroma.upsert(
                ids=[r["id"] for r in batch],
                embeddings=[json.loads(r["embedding"]) for r in batch],
                metadatas=[{"tenant": r["tenant"]} for r in batch],
            )

    def list_documents(self, tenant):
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    text("SELECT * FROM documents WHERE tenant=:t ORDER BY created_at DESC"), {"t": tenant}
                ).mappings()
            ]

    def revision(self, tenant):
        return [(d["id"], bool(d["active"])) for d in self.list_documents(tenant)]

    def ingest(self, tenant, filename, version, category, digest, chunks, embeddings):
        with self.lock:
            with self.engine.begin() as conn:
                existing = (
                    conn.execute(
                        text("SELECT * FROM documents WHERE tenant=:t AND filename=:f AND version=:v"),
                        {"t": tenant, "f": filename, "v": version},
                    )
                    .mappings()
                    .first()
                )
                if existing:
                    if existing["digest"] != digest:
                        raise ValueError(
                            "This filename/version already exists with different content; use a new version"
                        )
                    return {"document_id": existing["id"], "deduplicated": True, "chunks": 0}
                doc_id = str(uuid.uuid4())
                conn.execute(
                    text("UPDATE documents SET active=false WHERE tenant=:t AND filename=:f"),
                    {"t": tenant, "f": filename},
                )
                conn.execute(
                    text("INSERT INTO documents VALUES (:id,:t,:f,:c,:v,:h,true,:date)"),
                    {
                        "id": doc_id,
                        "t": tenant,
                        "f": filename,
                        "c": category,
                        "v": version,
                        "h": digest,
                        "date": datetime.now(timezone.utc).isoformat(),
                    },
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True):
                    chunk["document_id"] = doc_id
                    sql = "INSERT INTO chunks VALUES (:id,:d,:t,:content,:meta," + (
                        "CAST(:e AS vector))" if self.pg else ":e)"
                    )
                    conn.execute(
                        text(sql),
                        {
                            "id": chunk["id"],
                            "d": doc_id,
                            "t": tenant,
                            "content": chunk["text"],
                            "meta": json.dumps(chunk),
                            "e": json.dumps(embedding),
                        },
                    )
            if self.chroma is not None:
                self.rebuild_index()
            return {"document_id": doc_id, "deduplicated": False, "chunks": len(chunks)}

    def delete(self, tenant, doc_id):
        with self.lock, self.engine.begin() as conn:
            found = conn.execute(
                text("SELECT id FROM documents WHERE id=:d AND tenant=:t"), {"d": doc_id, "t": tenant}
            ).scalar()
            if not found:
                return False
            ids = (
                conn.execute(
                    text("SELECT id FROM chunks WHERE document_id=:d AND tenant=:t"),
                    {"d": doc_id, "t": tenant},
                )
                .scalars()
                .all()
            )
            conn.execute(
                text("DELETE FROM chunks WHERE document_id=:d AND tenant=:t"), {"d": doc_id, "t": tenant}
            )
            conn.execute(text("DELETE FROM documents WHERE id=:d AND tenant=:t"), {"d": doc_id, "t": tenant})
            if ids and self.chroma is not None:
                self.chroma.delete(ids=ids)
            return True

    def search(self, tenant, query, embedding, filters, k):
        clauses = ["c.tenant=:t", "d.tenant=:t"]
        params = {"t": tenant, "k": k, "q": query, "e": json.dumps(embedding)}
        if not filters.get("version"):
            clauses.append("d.active=true")
        for field in ("category", "version", "filename"):
            if filters.get(field):
                clauses.append(f"d.{field}=:{field}")
                params[field] = filters[field]
        if filters.get("document_ids"):
            names = []
            for i, value in enumerate(filters["document_ids"]):
                params[f"d{i}"] = value
                names.append(f":d{i}")
            clauses.append(f"d.id IN ({','.join(names)})")
        base = " FROM chunks c JOIN documents d ON c.document_id=d.id WHERE " + " AND ".join(clauses)
        with self.engine.connect() as conn:
            if self.pg:
                # Exact scoped vector search avoids ANN post-filter recall loss for small tenants.
                semantic = (
                    conn.execute(
                        text(
                            "WITH eligible AS MATERIALIZED (SELECT c.metadata, c.embedding"
                            + base
                            + ") SELECT metadata FROM eligible ORDER BY embedding <=> CAST(:e AS vector) LIMIT :k"
                        ),
                        params,
                    )
                    .scalars()
                    .all()
                )
                keyword = (
                    conn.execute(
                        text(
                            "SELECT c.metadata"
                            + base
                            + " AND to_tsvector('english',c.content) @@ plainto_tsquery('english',:q)"
                            " ORDER BY ts_rank_cd(to_tsvector('english',c.content),plainto_tsquery('english',:q)) DESC LIMIT :k"
                        ),
                        params,
                    )
                    .scalars()
                    .all()
                )
                return [json.loads(r) for r in semantic], [json.loads(r) for r in keyword]
            rows = conn.execute(text("SELECT c.id,c.content,c.metadata" + base), params).mappings().all()
        if not rows:
            return [], []
        allowed = {r["id"]: json.loads(r["metadata"]) for r in rows}
        # Filter by exact allowed IDs before ranking, including active version and tenant restrictions.
        result = self.chroma.query(
            query_embeddings=[embedding], ids=list(allowed), n_results=min(k, len(rows))
        )
        semantic = [allowed[i] for i in result["ids"][0] if i in allowed]
        tokens = [tokenize(r["content"]) or ["_empty"] for r in rows]
        scores = BM25Okapi(tokens).get_scores(tokenize(query))
        keyword = [
            allowed[rows[i]["id"]]
            for i in sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)
            if set(tokenize(query)) & set(tokens[i])
        ][:k]
        return semantic, keyword
