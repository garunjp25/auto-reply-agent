from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from auto_reply.llm.client import LLMClient
from auto_reply.sources.wiki_builder import (
    PRODUCT_SYSTEM_PROMPT,
    WikiBuilder,
    chunk_markdown,
)


def test_chunk_markdown_splits_on_paragraphs():
    md = "# Heading\n\nFirst paragraph.\n\nSecond paragraph.\n\nThird."
    chunks = chunk_markdown(md, max_chars=200)
    assert len(chunks) >= 1
    assert all(c.strip() for c in chunks)
    joined = " ".join(chunks)
    assert "First paragraph" in joined
    assert "Second paragraph" in joined
    assert "Third" in joined


def test_chunk_markdown_respects_max_chars():
    para = "x" * 500
    md = f"para1\n\n{para}\n\npara3"
    chunks = chunk_markdown(md, max_chars=100)
    assert all(len(c) <= 100 for c in chunks)


def test_wiki_builder_writes_md_and_persists_chunks(tmp_path: Path, db):
    fake_md = "# EmailPilot\n\nAn email tool.\n\nIt does email things."

    sdk = MagicMock()
    fake_resp = MagicMock()
    fake_resp.id = "msg_1"
    fake_resp.usage.input_tokens = 100
    fake_resp.usage.output_tokens = 50
    fake_resp.usage.cache_read_input_tokens = 0
    fake_resp.usage.cache_creation_input_tokens = 0
    fake_resp.content = [MagicMock(text=fake_md)]
    sdk.messages.create.return_value = fake_resp
    llm = LLMClient(sdk=sdk, conn=db)

    class _FakeEmb:
        dim = 3
        def encode(self, texts):
            return np.array([[1.0, 0.0, 0.0]] * len(texts), dtype=np.float32)

    builder = WikiBuilder(
        llm=llm,
        embedder=_FakeEmb(),
        wiki_dir=tmp_path,
        conn=db,
    )

    builder.build_one({"id": "emailpilot", "name": "EmailPilot", "tagline": "x"})

    md_path = tmp_path / "emailpilot.md"
    assert md_path.exists()
    assert md_path.read_text(encoding="utf-8") == fake_md

    rows = db.execute(
        "SELECT product_id, text FROM wiki_index WHERE product_id='emailpilot' ORDER BY chunk_id"
    ).fetchall()
    assert len(rows) >= 1
    assert all(r["product_id"] == "emailpilot" for r in rows)

    cost_rows = db.execute("SELECT purpose FROM cost_log").fetchall()
    assert len(cost_rows) == 1
    assert cost_rows[0]["purpose"] == "wiki_build"


def test_system_prompt_mentions_no_hallucination():
    assert "don't" in PRODUCT_SYSTEM_PROMPT.lower() or "do not" in PRODUCT_SYSTEM_PROMPT.lower()
    assert "invent" in PRODUCT_SYSTEM_PROMPT.lower() or "fabricat" in PRODUCT_SYSTEM_PROMPT.lower()


def test_wiki_builder_without_embedder_only_writes_md(tmp_path: Path, db):
    fake_md = "# X\n\nFirst.\n\nSecond."
    sdk = MagicMock()
    fake_resp = MagicMock()
    fake_resp.id = "msg_noemb"
    fake_resp.usage.input_tokens = 10
    fake_resp.usage.output_tokens = 5
    fake_resp.usage.cache_read_input_tokens = 0
    fake_resp.usage.cache_creation_input_tokens = 0
    fake_resp.content = [MagicMock(text=fake_md)]
    sdk.messages.create.return_value = fake_resp
    llm = LLMClient(sdk=sdk, conn=db)

    builder = WikiBuilder(llm=llm, wiki_dir=tmp_path, conn=db)  # no embedder
    builder.build_one({"id": "x", "name": "X"})

    assert (tmp_path / "x.md").exists()
    rows = db.execute(
        "SELECT COUNT(*) FROM wiki_index WHERE product_id='x'"
    ).fetchone()
    assert rows[0] == 0  # no embeddings persisted when embedder is None
