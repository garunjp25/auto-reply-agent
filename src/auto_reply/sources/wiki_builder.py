from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from auto_reply.llm.client import LLMClient
from auto_reply.sources.wiki_store import WikiChunk, WikiStore

PRODUCT_SYSTEM_PROMPT = """You are writing internal documentation for a customer-support LLM agent.

For each product you are given as raw JSON, produce a single Markdown document
that an LLM can read to answer customer questions accurately. Karpathy-style:
dense, structured, no fluff, written for a reader who already knows English
but knows nothing about this product.

Rules:
- Use ONLY facts present in the provided JSON. Do not invent features,
  integrations, prices, SLAs, or refund terms. If a field is missing, omit
  it — do not fabricate.
- Cover: what the product is, who it is for, pricing tiers (verbatim), key
  features, integrations, refund / cancellation policy, support SLA.
- Use Markdown headings and bullet lists. No marketing copy. No emojis.
- Keep the document under ~1500 words.
"""


def chunk_markdown(md: str, max_chars: int = 1200) -> list[str]:
    """Split markdown on blank-line paragraphs; further split paragraphs that
    exceed max_chars. Empty chunks are dropped."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", md) if p.strip()]
    chunks: list[str] = []
    for p in paragraphs:
        if len(p) <= max_chars:
            chunks.append(p)
        else:
            for i in range(0, len(p), max_chars):
                chunks.append(p[i : i + max_chars])
    return chunks


class _Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray: ...


class WikiBuilder:
    """Generate one markdown doc per product, chunk it, embed it, persist it."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        wiki_dir: Path,
        conn: sqlite3.Connection,
        embedder: _Embedder | None = None,
        draft_model: str = "claude-sonnet-4-6",
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._wiki_dir = Path(wiki_dir)
        self._wiki_dir.mkdir(parents=True, exist_ok=True)
        self._store = WikiStore(conn)
        self._model = draft_model

    def build_one(self, product: dict[str, Any]) -> None:
        product_id = str(product["id"])
        md = self._llm.complete(
            model=self._model,
            system=PRODUCT_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(product, ensure_ascii=False, indent=2),
                }
            ],
            purpose="wiki_build",
            max_tokens=2048,
        )
        (self._wiki_dir / f"{product_id}.md").write_text(md, encoding="utf-8")

        if self._embedder is None:
            return  # wiki/*.md is the deliverable; embeddings are optional.

        texts = chunk_markdown(md)
        if not texts:
            return
        vectors = self._embedder.encode(texts)
        chunks = [
            WikiChunk(
                product_id=product_id,
                chunk_id=i,
                text=texts[i],
                embedding=vectors[i],
            )
            for i in range(len(texts))
        ]
        self._store.replace_product(product_id, chunks)

    def build_all(self, products: list[dict[str, Any]]) -> None:
        for p in products:
            self.build_one(p)
