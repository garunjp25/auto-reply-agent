from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from auto_reply.store.db import transaction


@dataclass(frozen=True)
class WikiChunk:
    product_id: str
    chunk_id: int
    text: str
    embedding: np.ndarray  # 1-D float32, L2-normalised


@dataclass(frozen=True)
class WikiHit:
    product_id: str
    chunk_id: int
    text: str
    score: float


def _vec_to_blob(v: np.ndarray) -> bytes:
    return v.astype(np.float32, copy=False).tobytes()


def _blob_to_vec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


class WikiStore:
    """SQLite-backed embedding store. Brute-force cosine top-K.

    Designed for tiny corpora (≤ a few thousand chunks).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_chunks(self, chunks: list[WikiChunk]) -> None:
        rows = [
            (c.product_id, c.chunk_id, c.text, _vec_to_blob(c.embedding))
            for c in chunks
        ]
        with transaction(self._conn):
            self._conn.executemany(
                "INSERT OR REPLACE INTO wiki_index "
                "(product_id, chunk_id, text, embedding) VALUES (?, ?, ?, ?)",
                rows,
            )

    def replace_product(self, product_id: str, chunks: list[WikiChunk]) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "DELETE FROM wiki_index WHERE product_id = ?", (product_id,)
            )
            self._conn.executemany(
                "INSERT INTO wiki_index "
                "(product_id, chunk_id, text, embedding) VALUES (?, ?, ?, ?)",
                [
                    (c.product_id, c.chunk_id, c.text, _vec_to_blob(c.embedding))
                    for c in chunks
                ],
            )

    def top_k(self, query: np.ndarray, k: int = 3) -> list[WikiHit]:
        rows = self._conn.execute(
            "SELECT product_id, chunk_id, text, embedding FROM wiki_index"
        ).fetchall()
        if not rows:
            return []
        q = query.astype(np.float32, copy=False)
        embeddings = np.stack([_blob_to_vec(r["embedding"]) for r in rows])
        scores = embeddings @ q
        top_idx = np.argsort(-scores)[:k]
        return [
            WikiHit(
                product_id=rows[i]["product_id"],
                chunk_id=rows[i]["chunk_id"],
                text=rows[i]["text"],
                score=float(scores[i]),
            )
            for i in top_idx
        ]
