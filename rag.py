"""
rag.py - Schema retrieval via FAISS vector search.
The index is built ONCE at import time and reused for every query.
"""

from sentence_transformers import SentenceTransformer
import faiss
import numpy as np


# Build index once
_MODEL_NAME = "all-MiniLM-L6-v2"
_SCHEMA_FILE = "schema.txt"
_TOP_K       = 6          # retrieve more chunks for complex multi-table queries

_model: SentenceTransformer | None = None
_index: faiss.Index | None = None
_documents: list[str] = []


def _build_index():
    global _model, _index, _documents

    _model = SentenceTransformer(_MODEL_NAME)

    with open(_SCHEMA_FILE) as f:
        raw = f.read()

    # Split on blank lines; filter empty chunks
    _documents = [d.strip() for d in raw.split("\n\n") if d.strip()]

    embeddings = _model.encode(_documents, show_progress_bar=False)
    dim = embeddings.shape[1]

    _index = faiss.IndexFlatL2(dim)
    _index.add(np.array(embeddings, dtype="float32"))


# Build at import time so the first query has no latency hit
_build_index()


def retrieve_schema(question: str, top_k: int = _TOP_K) -> str:
    """Return the most relevant schema chunks for *question*."""
    q_emb = _model.encode([question])
    _, indices = _index.search(np.array(q_emb, dtype="float32"), top_k)
    return "\n\n".join(_documents[i] for i in indices[0] if i < len(_documents))