# Phase 1 — LLM Wiki + Intent Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only knowledge layer the Drafter will consume in Phase 2: (1) an LLM-authored, Karpathy-style markdown wiki per product, embedded into a retrievable store; and (2) a Haiku-powered Intent Router that classifies the latest customer message and flags pricing/refund as sensitive. No drafting, no auto-send — just retrieval and routing primitives.

**Architecture:**
- `sources/lumenx.py` — typed HTTP client for the LumenX admin API (auth header, retries off, sync httpx).
- `sources/embeddings.py` — local `sentence-transformers/all-MiniLM-L6-v2` wrapper; no extra API key, runs on CPU. Vectors stored in the existing `wiki_index` SQLite table.
- `sources/wiki_builder.py` — for each product JSON, asks Sonnet to author a single Karpathy-style markdown file, chunks it, embeds it, persists.
- `sources/wiki_store.py` — load all chunks once, brute-force cosine top-K (corpus is tiny, ~20 products × ~5 chunks).
- `pipeline/intent_router.py` — `IntentRouter.classify(message) -> IntentResult` with Haiku 4.5, JSON output, sensitive-flag derived deterministically from the intent label.
- `scripts/build_wiki.py` — CLI that fetches products + generates + embeds + persists everything.
- `scripts/build_intent_eval.py` — CLI that fetches `/api/admin/export`, samples 30 diverse customer messages, labels them with Opus (one-shot, cached prompt), writes a JSONL fixture for the user to spot-check.
- `scripts/eval_intent.py` — CLI that runs the IntentRouter against the 30-msg fixture and reports accuracy. Not part of `pytest` (costs money).

**Tech Stack:** Python 3.11+ · httpx · anthropic SDK · sentence-transformers (pulls torch CPU) · numpy · stdlib sqlite3 · pytest. Uses the Phase 0 `LLMClient` for every Claude call.

---

## Dependencies to add

Append to `pyproject.toml` `[project] dependencies`:
- `sentence-transformers>=3.0`
- `numpy>=1.26`

`torch` is a transitive dep of sentence-transformers; we'll use the CPU build (default on Windows from PyPI). The model download (~80MB) happens at first use; cached under `~/.cache/huggingface/`.

---

## File structure produced by this phase

```
phase2-live/
├── pyproject.toml                    (modified — adds sentence-transformers, numpy)
├── src/auto_reply/
│   ├── sources/
│   │   ├── lumenx.py                 NEW
│   │   ├── embeddings.py             NEW
│   │   ├── wiki_builder.py           NEW
│   │   └── wiki_store.py             NEW
│   └── pipeline/
│       └── intent_router.py          NEW
├── scripts/
│   ├── build_wiki.py                 NEW
│   ├── build_intent_eval.py          NEW
│   └── eval_intent.py                NEW
├── tests/
│   ├── fixtures/
│   │   ├── lumenx_products.json      NEW (committed; cached snapshot)
│   │   └── intent_eval.jsonl         NEW (committed; 30 labelled msgs)
│   ├── test_lumenx.py                NEW
│   ├── test_embeddings.py            NEW
│   ├── test_wiki_builder.py          NEW
│   ├── test_wiki_store.py            NEW
│   └── test_intent_router.py         NEW
└── wiki/                             generated, gitignored
```

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml`**

Modify the `dependencies` list under `[project]` to add the two new entries. The full updated list should be:

```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "anthropic>=0.40",
  "httpx>=0.27",
  "sentence-transformers>=3.0",
  "numpy>=1.26",
]
```

- [ ] **Step 2: Sync**

Run: `uv sync --extra dev`
Expected: installs `sentence-transformers`, `numpy`, `torch` (CPU), `transformers`, etc., updates `uv.lock`.

- [ ] **Step 3: Sanity-check imports**

Run: `uv run python -c "import sentence_transformers, numpy; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add sentence-transformers and numpy for wiki embeddings"
```

---

## Task 2: LumenX HTTP client

**Files:**
- Create: `src/auto_reply/sources/lumenx.py`
- Create: `tests/test_lumenx.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lumenx.py
import httpx
import pytest

from auto_reply.sources.lumenx import LumenXClient


def test_get_products_uses_admin_token(httpx_mock_factory=None):
    # Use httpx MockTransport for hermetic testing — no network.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/admin/products"
        assert request.headers["X-Admin-Token"] == "lmx_test"
        return httpx.Response(200, json={"products": [{"id": "emailpilot"}]})

    transport = httpx.MockTransport(handler)
    client = LumenXClient(
        base_url="https://lumenx.test",
        admin_token="lmx_test",
        transport=transport,
    )
    data = client.get_products()
    assert data == {"products": [{"id": "emailpilot"}]}
    client.close()


def test_get_thread_by_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/admin/threads/abc-123"
        return httpx.Response(200, json={"thread": {"id": "abc-123"}})

    transport = httpx.MockTransport(handler)
    client = LumenXClient("https://lumenx.test", "lmx_test", transport=transport)
    data = client.get_thread("abc-123")
    assert data == {"thread": {"id": "abc-123"}}
    client.close()


def test_get_export():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/admin/export"
        return httpx.Response(200, json={"threads": [], "products": []})

    transport = httpx.MockTransport(handler)
    client = LumenXClient("https://lumenx.test", "lmx_test", transport=transport)
    data = client.get_export()
    assert "threads" in data and "products" in data
    client.close()


def test_raises_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad token"})

    transport = httpx.MockTransport(handler)
    client = LumenXClient("https://lumenx.test", "wrong", transport=transport)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_products()
    client.close()


def test_post_reply():
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        posted["url"] = str(request.url.path)
        posted["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = LumenXClient("https://lumenx.test", "lmx_test", transport=transport)
    res = client.post_reply(
        thread_id="abc",
        text="hello",
        draft_source="agent",
        confidence=0.92,
    )
    assert res == {"ok": True}
    assert posted["url"] == "/api/admin/threads/abc/reply"
    body = posted["body"].decode()
    assert '"text":"hello"' in body or '"text": "hello"' in body
    assert '"draft_source":"agent"' in body or '"draft_source": "agent"' in body
    client.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lumenx.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/sources/lumenx.py
from typing import Any

import httpx


class LumenXClient:
    """Sync HTTP client for the LumenX admin API.

    Auth via the X-Admin-Token header on every request. No retries (retries
    belong in the Poller, not here). All errors raise httpx.HTTPStatusError.
    """

    def __init__(
        self,
        base_url: str,
        admin_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-Admin-Token": admin_token},
            transport=transport,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LumenXClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── reads ────────────────────────────────────────────────────────────
    def get_products(self) -> dict[str, Any]:
        r = self._client.get("/api/admin/products")
        r.raise_for_status()
        return r.json()

    def get_inbox(self, since: str | None = None) -> dict[str, Any]:
        params = {"since": since} if since else None
        r = self._client.get("/api/admin/inbox", params=params)
        r.raise_for_status()
        return r.json()

    def get_threads(self) -> dict[str, Any]:
        r = self._client.get("/api/admin/threads")
        r.raise_for_status()
        return r.json()

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        r = self._client.get(f"/api/admin/threads/{thread_id}")
        r.raise_for_status()
        return r.json()

    def get_export(self) -> dict[str, Any]:
        r = self._client.get("/api/admin/export")
        r.raise_for_status()
        return r.json()

    # ── writes ───────────────────────────────────────────────────────────
    def post_reply(
        self,
        *,
        thread_id: str,
        text: str,
        draft_source: str = "agent",
        confidence: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text, "draft_source": draft_source}
        if confidence is not None:
            body["confidence"] = confidence
        r = self._client.post(f"/api/admin/threads/{thread_id}/reply", json=body)
        r.raise_for_status()
        return r.json()

    def mark_read(self, thread_id: str) -> dict[str, Any]:
        r = self._client.post(f"/api/admin/threads/{thread_id}/mark-read")
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_lumenx.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/auto_reply/sources/lumenx.py tests/test_lumenx.py`
Expected: no errors. (If `httpx_mock_factory=None` parameter in `test_get_products_uses_admin_token` is flagged as unused, that's fine — it's a placeholder kept for clarity; remove it if ruff complains.)

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/sources/lumenx.py tests/test_lumenx.py
git commit -m "feat(sources): typed LumenX admin API client"
```

---

## Task 3: Cache a real `/api/admin/products` snapshot as a test fixture

**Files:**
- Create: `tests/fixtures/lumenx_products.json`
- Create: `scripts/__init__.py` (empty, marks scripts/ as a package for imports)
- Create: `scripts/refresh_fixtures.py`

This task pulls a real snapshot once so subsequent tasks have data to work with. It requires a working `.env` with `LUMENX_BASE` and `LUMENX_ADMIN_TOKEN`.

- [ ] **Step 1: Write `scripts/__init__.py`** (empty file).

- [ ] **Step 2: Write `scripts/refresh_fixtures.py`**

```python
"""Fetch live LumenX snapshots and write them to tests/fixtures/.

Run manually whenever LumenX product data changes:
    uv run python scripts/refresh_fixtures.py
"""
import json
from pathlib import Path

from auto_reply.settings import get_settings
from auto_reply.sources.lumenx import LumenXClient

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    with LumenXClient(settings.lumenx_base, settings.lumenx_admin_token) as client:
        products = client.get_products()
        export = client.get_export()

    (FIXTURE_DIR / "lumenx_products.json").write_text(
        json.dumps(products, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (FIXTURE_DIR / "lumenx_export.json").write_text(
        json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote products + export to {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Ensure `.env` is populated**

Verify `.env` exists in repo root with real `LUMENX_BASE` and `LUMENX_ADMIN_TOKEN`. If absent, copy `.env.example` and fill in real values from `api_description.txt`. Do not commit `.env` (it's in `.gitignore`).

- [ ] **Step 4: Run the fixture refresh**

Run: `uv run python scripts/refresh_fixtures.py`
Expected: writes `tests/fixtures/lumenx_products.json` and `tests/fixtures/lumenx_export.json` (the export may be a few MB — that's fine).

If this fails because `LUMENX_ADMIN_TOKEN` is missing or wrong, STOP and report it.

- [ ] **Step 5: Sanity-check the fixture**

Run: `uv run python -c "import json; d = json.load(open('tests/fixtures/lumenx_products.json', encoding='utf-8')); print(len(d.get('products', d)))"`
Expected: prints `20` (or thereabouts — should be the count of products).

- [ ] **Step 6: Decide what to commit**

- Commit `tests/fixtures/lumenx_products.json` — small, deterministic, useful for hermetic tests.
- Do NOT commit `tests/fixtures/lumenx_export.json` — it may contain customer messages and is large. Add `tests/fixtures/lumenx_export.json` to `.gitignore`.

Modify `.gitignore` to append:

```
tests/fixtures/lumenx_export.json
```

- [ ] **Step 7: Commit**

```bash
git add scripts/__init__.py scripts/refresh_fixtures.py tests/fixtures/lumenx_products.json .gitignore
git commit -m "chore(fixtures): refresh script + committed products snapshot"
```

---

## Task 4: Embeddings wrapper

**Files:**
- Create: `src/auto_reply/sources/embeddings.py`
- Create: `tests/test_embeddings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embeddings.py
import numpy as np
import pytest

from auto_reply.sources.embeddings import EmbeddingModel


@pytest.fixture(scope="module")
def model() -> EmbeddingModel:
    # Loads the sentence-transformer the first time; ~80MB download on first run.
    return EmbeddingModel()


def test_encode_returns_unit_vectors(model):
    vecs = model.encode(["hello world", "foo bar baz"])
    assert isinstance(vecs, np.ndarray)
    assert vecs.shape == (2, model.dim)
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)


def test_semantic_similarity(model):
    a, b, c = model.encode([
        "How much does the pro plan cost?",
        "what's the price of your premium tier",
        "I want to delete my account",
    ])
    sim_ab = float(np.dot(a, b))
    sim_ac = float(np.dot(a, c))
    # Pricing questions should be much closer to each other than to an unrelated topic.
    assert sim_ab > sim_ac + 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_embeddings.py -v`
Expected: FAIL with `ImportError`. (Don't be alarmed if the test fixture is slow to start — once you write the impl, the first run will download the model.)

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/sources/embeddings.py
from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingModel:
    """Local CPU embeddings via sentence-transformers.

    Returns L2-normalised vectors so cosine similarity == dot product.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model = SentenceTransformer(model_name)
        self.dim: int = self._model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_embeddings.py -v`
Expected: 2 passed. First run may take 30–60s for model download.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/auto_reply/sources/embeddings.py tests/test_embeddings.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/sources/embeddings.py tests/test_embeddings.py
git commit -m "feat(sources): sentence-transformer embeddings wrapper"
```

---

## Task 5: Wiki store — persist + retrieve

**Files:**
- Create: `src/auto_reply/sources/wiki_store.py`
- Create: `tests/test_wiki_store.py`

The `wiki_index` table from migration 0001 already exists with columns
`(product_id, chunk_id, text, embedding BLOB)`. This task adds reads and writes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_store.py
import numpy as np

from auto_reply.sources.wiki_store import WikiStore, WikiChunk


def test_save_and_search_returns_top_k(db):
    store = WikiStore(db)
    # Three chunks, with clearly distinct vectors so similarity ranking is determined.
    v_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    v_c = np.array([0.9, 0.1, 0.0], dtype=np.float32)
    v_c /= np.linalg.norm(v_c)

    store.save_chunks([
        WikiChunk(product_id="p1", chunk_id=0, text="apples", embedding=v_a),
        WikiChunk(product_id="p2", chunk_id=0, text="bananas", embedding=v_b),
        WikiChunk(product_id="p1", chunk_id=1, text="apple pie", embedding=v_c),
    ])

    query = v_a  # closest to apples and apple pie, far from bananas
    hits = store.top_k(query, k=2)
    texts = [h.text for h in hits]
    assert "apples" in texts
    assert "apple pie" in texts
    assert "bananas" not in texts


def test_replace_product_chunks_is_idempotent(db):
    store = WikiStore(db)
    v = np.array([1.0, 0.0], dtype=np.float32)
    store.save_chunks([
        WikiChunk(product_id="p1", chunk_id=0, text="old", embedding=v),
    ])
    store.replace_product("p1", [
        WikiChunk(product_id="p1", chunk_id=0, text="new", embedding=v),
        WikiChunk(product_id="p1", chunk_id=1, text="also new", embedding=v),
    ])
    rows = db.execute(
        "SELECT text FROM wiki_index WHERE product_id='p1' ORDER BY chunk_id"
    ).fetchall()
    assert [r["text"] for r in rows] == ["new", "also new"]


def test_top_k_handles_empty_store(db):
    store = WikiStore(db)
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    hits = store.top_k(query, k=3)
    assert hits == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_store.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/sources/wiki_store.py
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
    score: float  # cosine similarity in [-1, 1]


def _vec_to_blob(v: np.ndarray) -> bytes:
    return v.astype(np.float32, copy=False).tobytes()


def _blob_to_vec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


class WikiStore:
    """SQLite-backed embedding store. Brute-force cosine top-K.

    Designed for tiny corpora (≤ a few thousand chunks). For larger corpora,
    swap for a real ANN index.
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
        # Brute-force: stack all embeddings, compute dot product.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_wiki_store.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/auto_reply/sources/wiki_store.py tests/test_wiki_store.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/sources/wiki_store.py tests/test_wiki_store.py
git commit -m "feat(sources): WikiStore — sqlite-backed brute-force vector retrieval"
```

---

## Task 6: Wiki builder — author markdown per product

**Files:**
- Create: `src/auto_reply/sources/wiki_builder.py`
- Create: `tests/test_wiki_builder.py`

The builder takes the products JSON, calls Sonnet via the Phase 0 `LLMClient`
to author one Karpathy-style markdown file per product, then chunks it. The
chunker is naive (paragraph-split with a max length); it's good enough for ~20
products.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_builder.py
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from auto_reply.llm.client import LLMClient
from auto_reply.sources.embeddings import EmbeddingModel
from auto_reply.sources.wiki_builder import (
    PRODUCT_SYSTEM_PROMPT,
    WikiBuilder,
    chunk_markdown,
)


def test_chunk_markdown_splits_on_paragraphs():
    md = "# Heading\n\nFirst paragraph.\n\nSecond paragraph.\n\nThird."
    chunks = chunk_markdown(md, max_chars=200)
    assert len(chunks) >= 1
    # All chunks are non-empty after stripping.
    assert all(c.strip() for c in chunks)
    # Joined chunks include all the meaningful text.
    joined = " ".join(chunks)
    assert "First paragraph" in joined
    assert "Second paragraph" in joined
    assert "Third" in joined


def test_chunk_markdown_respects_max_chars():
    para = "x" * 500
    md = f"para1\n\n{para}\n\npara3"
    chunks = chunk_markdown(md, max_chars=100)
    # The long paragraph gets split into pieces no longer than max_chars each.
    assert all(len(c) <= 100 for c in chunks)


def test_wiki_builder_writes_md_and_persists_chunks(tmp_path: Path, db, monkeypatch):
    # Mock the LLM so we don't call Anthropic.
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

    # Stub embedding model.
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

    # Cost was logged.
    cost_rows = db.execute("SELECT purpose FROM cost_log").fetchall()
    assert len(cost_rows) == 1
    assert cost_rows[0]["purpose"] == "wiki_build"


def test_system_prompt_mentions_no_hallucination():
    # Sanity: anti-hallucination guardrail should be in the system prompt.
    assert "don't" in PRODUCT_SYSTEM_PROMPT.lower() or "do not" in PRODUCT_SYSTEM_PROMPT.lower()
    assert "invent" in PRODUCT_SYSTEM_PROMPT.lower() or "fabricat" in PRODUCT_SYSTEM_PROMPT.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_builder.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/sources/wiki_builder.py
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
        embedder: _Embedder,
        wiki_dir: Path,
        conn: sqlite3.Connection,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_wiki_builder.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/auto_reply/sources/wiki_builder.py tests/test_wiki_builder.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/sources/wiki_builder.py tests/test_wiki_builder.py
git commit -m "feat(sources): WikiBuilder authors markdown + chunks + embeds per product"
```

---

## Task 7: `scripts/build_wiki.py` — end-to-end CLI

**Files:**
- Create: `scripts/build_wiki.py`

This is a one-shot CLI. No new unit tests — we ran the pieces under test in
Tasks 4–6. Smoke-test by running it manually against the live API.

- [ ] **Step 1: Write `scripts/build_wiki.py`**

```python
"""Build the LLM Wiki end-to-end.

Steps:
1. Fetch products from LumenX.
2. For each product, ask Sonnet to author wiki/<id>.md.
3. Chunk + embed each doc.
4. Persist chunks to the SQLite wiki_index table.

Run:
    uv run python scripts/build_wiki.py
"""
from __future__ import annotations

from pathlib import Path

from anthropic import Anthropic

from auto_reply.llm.client import LLMClient
from auto_reply.settings import get_settings
from auto_reply.sources.embeddings import EmbeddingModel
from auto_reply.sources.lumenx import LumenXClient
from auto_reply.sources.wiki_builder import WikiBuilder
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations

WIKI_DIR = Path(__file__).resolve().parents[1] / "wiki"


def main() -> None:
    settings = get_settings()
    conn = connect(settings.agent_db_path)
    apply_migrations(conn)

    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)
    embedder = EmbeddingModel()

    with LumenXClient(settings.lumenx_base, settings.lumenx_admin_token) as lx:
        payload = lx.get_products()

    # The /api/admin/products endpoint returns { products: [...], policies: {...} }
    # — we only generate per-product docs for now.
    products = payload.get("products", payload if isinstance(payload, list) else [])

    builder = WikiBuilder(llm=llm, embedder=embedder, wiki_dir=WIKI_DIR, conn=conn)
    for i, product in enumerate(products, start=1):
        pid = product.get("id", "<unknown>")
        print(f"[{i}/{len(products)}] {pid} ...")
        builder.build_one(product)

    total_cost = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_log WHERE purpose='wiki_build'"
    ).fetchone()[0]
    print(f"Done. Wrote {len(products)} docs. Total wiki_build cost: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it (live)**

Run: `uv run python scripts/build_wiki.py`
Expected: prints `[1/20] ...` through `[20/20] ...`, then the total cost (likely under $0.50). The `wiki/` directory is now populated with 20 `.md` files.

If something fails partway, the wiki_index in SQLite has partial state — re-running is safe because `WikiBuilder.build_one` uses `replace_product` (idempotent per product).

- [ ] **Step 3: Spot-check one of the generated docs**

Open `wiki/emailpilot.md` (or any one). Confirm it reads like reasonable product docs, mentions pricing tiers verbatim, and does not contain obvious invented features.

- [ ] **Step 4: Commit the script (NOT the generated wiki/)**

```bash
git add scripts/build_wiki.py
git commit -m "feat(scripts): build_wiki CLI — products → markdown → embeddings"
```

The `wiki/` directory is in `.gitignore` (added in Phase 0). Confirm `git status` does not show `wiki/` as untracked.

---

## Task 8: Intent Router

**Files:**
- Create: `src/auto_reply/pipeline/intent_router.py`
- Create: `tests/test_intent_router.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intent_router.py
from unittest.mock import MagicMock

import pytest

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.intent_router import (
    INTENTS,
    SENSITIVE_INTENTS,
    IntentResult,
    IntentRouter,
)


def _make_llm(db, label: str) -> LLMClient:
    """LLMClient that always returns a fixed JSON label."""
    sdk = MagicMock()
    resp = MagicMock()
    resp.id = "msg_intent_test"
    resp.usage.input_tokens = 30
    resp.usage.output_tokens = 5
    resp.usage.cache_read_input_tokens = 0
    resp.usage.cache_creation_input_tokens = 0
    resp.content = [MagicMock(text=f'{{"intent": "{label}"}}')]
    sdk.messages.create.return_value = resp
    return LLMClient(sdk=sdk, conn=db)


def test_intents_constant_matches_spec():
    assert set(INTENTS) == {
        "greeting", "pricing", "refund", "technical",
        "feature_question", "integration", "other",
    }
    assert SENSITIVE_INTENTS == {"pricing", "refund"}


def test_classify_returns_intent_result(db):
    llm = _make_llm(db, "technical")
    router = IntentRouter(llm=llm)
    result = router.classify("My integration with Slack broke yesterday")
    assert isinstance(result, IntentResult)
    assert result.intent == "technical"
    assert result.sensitive is False


def test_sensitive_flag_set_for_pricing(db):
    llm = _make_llm(db, "pricing")
    router = IntentRouter(llm=llm)
    result = router.classify("How much is the Pro plan?")
    assert result.intent == "pricing"
    assert result.sensitive is True


def test_sensitive_flag_set_for_refund(db):
    llm = _make_llm(db, "refund")
    router = IntentRouter(llm=llm)
    result = router.classify("I want my money back")
    assert result.intent == "refund"
    assert result.sensitive is True


def test_unknown_label_falls_back_to_other(db):
    llm = _make_llm(db, "completely_made_up")
    router = IntentRouter(llm=llm)
    result = router.classify("???")
    assert result.intent == "other"
    assert result.sensitive is False


def test_classify_writes_cost_row(db):
    llm = _make_llm(db, "greeting")
    router = IntentRouter(llm=llm)
    router.classify("hi there")
    rows = db.execute(
        "SELECT purpose, model FROM cost_log WHERE purpose='intent'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["model"] == "claude-haiku-4-5-20251001"


def test_malformed_json_falls_back_to_other(db):
    sdk = MagicMock()
    resp = MagicMock()
    resp.id = "msg_bad"
    resp.usage.input_tokens = 5
    resp.usage.output_tokens = 5
    resp.usage.cache_read_input_tokens = 0
    resp.usage.cache_creation_input_tokens = 0
    resp.content = [MagicMock(text="not json at all")]
    sdk.messages.create.return_value = resp
    llm = LLMClient(sdk=sdk, conn=db)

    router = IntentRouter(llm=llm)
    result = router.classify("anything")
    assert result.intent == "other"
    assert result.sensitive is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_intent_router.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/pipeline/intent_router.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from auto_reply.llm.client import LLMClient

INTENTS: tuple[str, ...] = (
    "greeting",
    "pricing",
    "refund",
    "technical",
    "feature_question",
    "integration",
    "other",
)
SENSITIVE_INTENTS: frozenset[str] = frozenset({"pricing", "refund"})

INTENT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You classify a single customer-support message into ONE intent.

Valid intents:
- greeting        — pure social ("hi", "thanks", "have a good day"). No product question.
- pricing         — anything about cost, plans, tiers, discounts, billing amount.
- refund          — refund requests, cancellation, money-back, charge disputes.
- technical       — bug reports, errors, broken behaviour, performance issues.
- feature_question — "does X support Y?", "how do I do Z?", capability or how-to.
- integration     — connecting to other tools (Slack, Zapier, Stripe, etc.).
- other           — anything that does not fit above, including unclear messages.

Reply with ONLY a single JSON object: {"intent": "<one of the above>"}.
No prose, no markdown fences, no explanation.
"""


@dataclass(frozen=True)
class IntentResult:
    intent: str
    sensitive: bool


def _parse_intent(text: str) -> str:
    """Extract the intent label from the model's JSON reply, with fallbacks."""
    # Try strict JSON first.
    try:
        data = json.loads(text.strip())
        candidate = str(data.get("intent", "")).strip().lower()
        if candidate in INTENTS:
            return candidate
    except (json.JSONDecodeError, AttributeError):
        pass
    # Fallback: regex-find a known intent token anywhere in the reply.
    for intent in INTENTS:
        if re.search(rf"\b{re.escape(intent)}\b", text, re.IGNORECASE):
            return intent
    return "other"


class IntentRouter:
    """Classify a single customer message into one of the canonical intents."""

    def __init__(self, *, llm: LLMClient, model: str = INTENT_MODEL) -> None:
        self._llm = llm
        self._model = model

    def classify(self, customer_message: str) -> IntentResult:
        raw = self._llm.complete(
            model=self._model,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": customer_message}],
            purpose="intent",
            max_tokens=64,
            temperature=0.0,
        )
        intent = _parse_intent(raw)
        return IntentResult(intent=intent, sensitive=intent in SENSITIVE_INTENTS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_intent_router.py -v`
Expected: 7 passed.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/auto_reply/pipeline/intent_router.py tests/test_intent_router.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/pipeline/intent_router.py tests/test_intent_router.py
git commit -m "feat(pipeline): IntentRouter — Haiku classifier with sensitive flag"
```

---

## Task 9: Build the 30-message intent eval fixture

**Files:**
- Create: `scripts/build_intent_eval.py`
- Create: `tests/fixtures/intent_eval.jsonl` (committed)

This script samples diverse customer messages from `/api/admin/export` and uses
**Opus 4.7** to label them. The result is a JSONL fixture you review by hand.
This is a one-shot run; commit the file so future runs of the evaluator are
deterministic.

- [ ] **Step 1: Write `scripts/build_intent_eval.py`**

```python
"""Build the IntentRouter eval set.

Reads tests/fixtures/lumenx_export.json (refresh with scripts/refresh_fixtures.py).
Samples 30 diverse customer messages and labels them with Opus.
Writes tests/fixtures/intent_eval.jsonl — one {"message": ..., "intent": ...} per line.

Run once, then hand-review the output. Re-run only when you want to refresh.

    uv run python scripts/build_intent_eval.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from anthropic import Anthropic

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.intent_router import INTENTS, SYSTEM_PROMPT, _parse_intent
from auto_reply.settings import get_settings
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
EXPORT_PATH = FIXTURE_DIR / "lumenx_export.json"
OUT_PATH = FIXTURE_DIR / "intent_eval.jsonl"

N = 30
LABELLER_MODEL = "claude-opus-4-7"


def collect_customer_messages(export: dict) -> list[str]:
    out: list[str] = []
    for thread in export.get("threads", []):
        for msg in thread.get("messages", []):
            if msg.get("role") == "customer":
                text = (msg.get("text") or "").strip()
                if 4 <= len(text) <= 600:
                    out.append(text)
    return out


def main() -> None:
    settings = get_settings()
    if not EXPORT_PATH.exists():
        raise SystemExit(
            f"{EXPORT_PATH} not found. Run `uv run python scripts/refresh_fixtures.py` first."
        )
    export = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    messages = collect_customer_messages(export)
    if len(messages) < N:
        raise SystemExit(f"Only {len(messages)} candidates — need ≥ {N}.")

    random.seed(20260527)
    sample = random.sample(messages, N)

    conn = connect(settings.agent_db_path)
    apply_migrations(conn)
    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for i, msg in enumerate(sample, start=1):
            raw = llm.complete(
                model=LABELLER_MODEL,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": msg}],
                purpose="intent_eval_label",
                max_tokens=64,
                temperature=0.0,
            )
            intent = _parse_intent(raw)
            if intent not in INTENTS:
                intent = "other"
            fh.write(json.dumps({"message": msg, "intent": intent}, ensure_ascii=False) + "\n")
            print(f"[{i}/{N}] {intent:18s} {msg[:60]!r}")

    print(f"\nWrote {OUT_PATH}")
    print("Hand-review the labels and edit any that are wrong. The file is JSONL —")
    print("safe to edit in any text editor.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make sure `tests/fixtures/lumenx_export.json` exists**

If you skipped it in Task 3, run: `uv run python scripts/refresh_fixtures.py`

- [ ] **Step 3: Run the labeller**

Run: `uv run python scripts/build_intent_eval.py`
Expected: prints 30 lines like `[1/30] technical  '...'` and writes `tests/fixtures/intent_eval.jsonl`. Cost: under $0.10 with Opus on short messages.

- [ ] **Step 4: Hand-review**

Open `tests/fixtures/intent_eval.jsonl` and read every line. Fix any labels that look wrong. The intent of this file is to be a high-quality reference — Opus is good but not perfect on edge cases.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_intent_eval.py tests/fixtures/intent_eval.jsonl
git commit -m "feat(scripts): intent eval set generator + 30 hand-reviewed labels"
```

---

## Task 10: Offline accuracy evaluator + acceptance gate

**Files:**
- Create: `scripts/eval_intent.py`
- Create: `tests/test_intent_eval_fixture.py`

The evaluator runs the live IntentRouter against the fixture and reports
accuracy + confusion matrix. It is a CLI, not part of `pytest`, because it
costs real money to run (~$0.01 per run with Haiku).

We DO add a pytest that validates the fixture itself is well-formed (cheap, no
API call).

- [ ] **Step 1: Write `tests/test_intent_eval_fixture.py`**

```python
import json
from pathlib import Path

from auto_reply.pipeline.intent_router import INTENTS

FIXTURE = Path(__file__).parent / "fixtures" / "intent_eval.jsonl"


def test_fixture_exists():
    assert FIXTURE.exists(), "Run scripts/build_intent_eval.py to generate it."


def test_fixture_has_30_entries():
    lines = [ln for ln in FIXTURE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 30


def test_every_entry_has_valid_intent_and_nonempty_message():
    seen_intents = set()
    for ln in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        obj = json.loads(ln)
        assert "message" in obj and obj["message"].strip()
        assert obj.get("intent") in INTENTS, f"Bad intent: {obj.get('intent')!r}"
        seen_intents.add(obj["intent"])
    # Sanity: at least 3 distinct intents represented (otherwise the eval is degenerate).
    assert len(seen_intents) >= 3
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_intent_eval_fixture.py -v`
Expected: 3 passed.

- [ ] **Step 3: Write `scripts/eval_intent.py`**

```python
"""Run the IntentRouter on the eval fixture and print accuracy.

Costs real Anthropic credit (~$0.01 with Haiku).

    uv run python scripts/eval_intent.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from anthropic import Anthropic

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.intent_router import IntentRouter
from auto_reply.settings import get_settings
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "intent_eval.jsonl"
ACCEPTANCE_THRESHOLD = 0.80  # ≥ 80% accuracy is the Phase 1 acceptance gate.


def main() -> None:
    settings = get_settings()
    conn = connect(settings.agent_db_path)
    apply_migrations(conn)
    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)
    router = IntentRouter(llm=llm)

    correct = 0
    total = 0
    confusion: dict[str, Counter] = defaultdict(Counter)
    mistakes: list[tuple[str, str, str]] = []

    with FIXTURE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            gold = obj["intent"]
            pred = router.classify(obj["message"]).intent
            total += 1
            confusion[gold][pred] += 1
            if pred == gold:
                correct += 1
            else:
                mistakes.append((gold, pred, obj["message"][:80]))

    acc = correct / total if total else 0.0
    print(f"\nAccuracy: {correct}/{total} = {acc:.1%}\n")
    print("Confusion (gold → predicted):")
    for gold, preds in confusion.items():
        print(f"  {gold:18s} {dict(preds)}")
    if mistakes:
        print(f"\nMistakes ({len(mistakes)}):")
        for gold, pred, msg in mistakes:
            print(f"  gold={gold:14s} pred={pred:14s} {msg!r}")

    print(f"\nAcceptance threshold: {ACCEPTANCE_THRESHOLD:.0%}")
    if acc >= ACCEPTANCE_THRESHOLD:
        print("PASS ✅")
    else:
        print("FAIL ❌ — iterate on the system prompt.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run it**

Run: `uv run python scripts/eval_intent.py`
Expected: prints accuracy ≥ 80%. If lower, iterate on `SYSTEM_PROMPT` in `intent_router.py` (add a one-line clarification per recurring mistake) and re-run.

If after two prompt-tweak iterations accuracy is still below 80%, STOP and report — the eval set may have ambiguous labels (in which case fix the fixture) or the model may need to upgrade to Sonnet (in which case escalate, since that changes the cost story).

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_intent.py tests/test_intent_eval_fixture.py
git commit -m "feat(scripts): IntentRouter eval CLI + fixture-shape pytest"
```

---

## Task 11: Final lint + full suite + milestone commit

**Files:** none

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests green. Previous Phase 0: 16. This phase adds:
- test_lumenx: 5
- test_embeddings: 2
- test_wiki_store: 3
- test_wiki_builder: 4
- test_intent_router: 7
- test_intent_eval_fixture: 3

Total expected: **40 passed**.

- [ ] **Step 2: Ruff**

Run: `uv run ruff check src tests scripts`
Expected: no errors. Fix any that surface and amend.

- [ ] **Step 3: Milestone commit**

```bash
git commit --allow-empty -m "chore: phase 1 green — wiki built, intent router meets 80% accuracy gate"
```

---

## Self-review notes

- **Spec coverage:**
  - Spec §5.7 (LLM Wiki) — Tasks 4, 5, 6, 7.
  - Spec §5.2 (IntentRouter, 7 categories, sensitive on pricing/refund) — Task 8.
  - Spec §11 Phase 1 deliverable "30-msg eval set" — Tasks 9, 10.
  - Cost logging integrated via Phase 0 `LLMClient` in every Claude call (wiki build, intent classify, intent labelling).
- **Placeholders:** none — every code/SQL/command step shows the full content.
- **Type consistency:** `IntentRouter.classify()` returns `IntentResult`; downstream phases (Context Builder, Router) consume the same type. `WikiStore.top_k()` returns `list[WikiHit]`; Context Builder will consume that.
- **Risk callouts:**
  - First sentence-transformers run triggers a ~80MB model download. Acceptable.
  - `scripts/build_wiki.py` against live LumenX makes 20 Sonnet calls (~$0.10–0.50). Cheap, but tracked in `cost_log`.
  - The 80% intent accuracy gate is a deliberate Phase 1 bar — if Haiku underperforms, the prompt is the first lever, not the model.
