"""Local sentence embeddings (all-MiniLM-L6-v2). Vectors are L2-normalised float32."""
from __future__ import annotations

from functools import lru_cache

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache
def model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME, device="cpu")


def embed(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    return model().encode(texts, batch_size=64, normalize_embeddings=True,
                          show_progress_bar=False).astype(np.float32)


def to_blob(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def article_text(title: str, summary: str) -> str:
    return f"{title}. {summary}".strip() if summary else title
