# Phase 2 — Draft Pipeline (No Auto-Send) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end producer-only pipeline. When a customer posts a message on LumenX, our service polls the admin inbox, classifies the intent, builds a context prompt (wiki + current-thread history), drafts a reply with Sonnet, and persists the draft to SQLite. **Nothing is auto-sent.** A read-only `/agent/queue` dashboard page lets you see pending drafts and the exact context that produced each one.

**Architecture:**
- One background async task (the Poller) drives the pipeline at 10s cadence.
- Pipeline is a straight line: `IntentRouter.classify` → `ContextBuilder.build` → `Drafter.draft` → SQLite `drafts` row. Pricing/refund and `greeting`/`other` follow templated short-circuits; everything else hits Sonnet.
- Prompt caching is applied to two large static blocks: the persona/safety system prompt and the concatenated wiki content. Anthropic's 5-minute TTL covers our polling rhythm well.
- The dashboard is a small FastAPI router with HTTP Basic auth and Jinja2 templates. No HTMX yet — that lands in Phase 3 with the approve/edit/reject buttons.

**Tech Stack:** Python 3.11+ · FastAPI · Jinja2 · asyncio · stdlib sqlite3 · Anthropic SDK (`claude-haiku-4-5-20251001` for intent, `claude-sonnet-4-6` for drafts with cache_control). Uses Phase 0 `LLMClient`, Phase 1 `LumenXClient` / `IntentRouter` / `WikiBuilder`-generated `wiki/*.md` / `truststore` setup.

---

## Dependencies to add

Append to `pyproject.toml` `[project] dependencies`:
- `jinja2>=3.1`
- `python-multipart>=0.0.9` (FastAPI's form parser; HTTP Basic doesn't need it but the Phase 3 forms will)

(`itsdangerous` would be needed if we used Starlette session middleware. We are not — HTTP Basic is sufficient for this single-admin tool.)

---

## File structure produced by this phase

```
src/auto_reply/
├── sources/
│   ├── wiki_loader.py        NEW — reads wiki/*.md once into memory
│   └── poller.py             NEW — async polling loop, dedup
├── pipeline/
│   ├── templates.py          NEW — greeting / other short-circuit replies
│   ├── context_builder.py    NEW — assembles the Drafter prompt
│   ├── drafter.py            NEW — Sonnet call with cache_control
│   └── process_message.py    NEW — orchestrator: intent → context → draft → store
└── web/
    ├── app.py                MODIFIED — lifespan starts/stops poller; mounts dashboard
    ├── dashboard.py          NEW — APIRouter for /agent/* + HTTP Basic auth
    └── templates/
        ├── base.html         NEW
        └── queue.html        NEW

tests/
├── test_wiki_loader.py       NEW
├── test_templates.py         NEW
├── test_context_builder.py   NEW
├── test_drafter.py           NEW
├── test_process_message.py   NEW
├── test_poller.py            NEW
└── test_dashboard.py         NEW
```

---

## Design decisions captured up front

- **No cross-thread customer summary in Phase 2.** Spec §5.3 calls for a one-paragraph summary of the same user's prior threads. That requires an extra LLM call per draft and a fetch over `/api/admin/threads`. Deferring to Phase 3 once we have feedback signal worth optimising against. Phase 2's `ContextBuilder` uses only the current thread.
- **No feedback-log retrieval in Phase 2.** The `feedback` and `training_labels` tables exist but are empty until Phase 3.
- **Full wiki in context, no RAG.** Decided in Phase 1: ~50K-token wiki fits well inside Sonnet's 200K context window, and avoids the corporate-SSL HuggingFace problem. `WikiLoader` reads every `wiki/*.md` once at startup and concatenates them.
- **Poller is a single async task, not a worker pool.** 10-second cadence × 20-product traffic = no parallelism needed. One task, easy to reason about, easy to shut down on app stop.
- **Dashboard auth: HTTP Basic.** One admin user, one env-var password. The browser remembers the credential for the session. No session cookies, no CSRF tokens.

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml`**

Modify the `dependencies` list to add Jinja2 and python-multipart. The full updated list should be:

```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "anthropic>=0.40",
  "httpx>=0.27",
  "numpy>=1.26",
  "truststore>=0.10.4",
  "jinja2>=3.1",
  "python-multipart>=0.0.9",
]
```

- [ ] **Step 2: Sync**

Run: `uv sync --extra dev`
Expected: installs jinja2 + python-multipart, updates `uv.lock`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add jinja2 + python-multipart for dashboard"
```

---

## Task 2: WikiLoader — read all wiki/*.md into memory

**Files:**
- Create: `src/auto_reply/sources/wiki_loader.py`
- Create: `tests/test_wiki_loader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_loader.py
from pathlib import Path

import pytest

from auto_reply.sources.wiki_loader import WikiLoader


def test_loads_all_md_files(tmp_path: Path):
    (tmp_path / "alpha.md").write_text("# Alpha\n\nAlpha body.\n", encoding="utf-8")
    (tmp_path / "beta.md").write_text("# Beta\n\nBeta body.\n", encoding="utf-8")

    loader = WikiLoader(tmp_path)
    out = loader.load_all()

    assert set(out.keys()) == {"alpha", "beta"}
    assert "Alpha body" in out["alpha"]
    assert "Beta body" in out["beta"]


def test_concatenated_uses_horizontal_rule_separators(tmp_path: Path):
    (tmp_path / "alpha.md").write_text("Alpha", encoding="utf-8")
    (tmp_path / "beta.md").write_text("Beta", encoding="utf-8")

    loader = WikiLoader(tmp_path)
    text = loader.concatenated()
    # Both bodies appear; product ids are visible as headings.
    assert "Alpha" in text
    assert "Beta" in text
    # Has some separator between them.
    assert "---" in text or "\n\n" in text


def test_missing_directory_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        WikiLoader(tmp_path / "nope").load_all()


def test_empty_directory_returns_empty_dict(tmp_path: Path):
    loader = WikiLoader(tmp_path)
    assert loader.load_all() == {}
    assert loader.concatenated() == ""
```

- [ ] **Step 2: Run, expect FAIL.**

Run: `uv run pytest tests/test_wiki_loader.py -v`

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/sources/wiki_loader.py
from __future__ import annotations

from pathlib import Path


class WikiLoader:
    """Reads wiki/*.md files into memory.

    Phase 2 uses the full concatenated wiki as a cached system block (Sonnet's
    200K context comfortably holds ~20 products at ~1500 words each).
    """

    def __init__(self, wiki_dir: Path) -> None:
        self._wiki_dir = Path(wiki_dir)

    def load_all(self) -> dict[str, str]:
        """Map product_id (filename stem) → markdown body."""
        if not self._wiki_dir.exists():
            raise FileNotFoundError(f"wiki dir not found: {self._wiki_dir}")
        out: dict[str, str] = {}
        for path in sorted(self._wiki_dir.glob("*.md")):
            out[path.stem] = path.read_text(encoding="utf-8")
        return out

    def concatenated(self) -> str:
        """All wiki docs joined, with product-id headers and separators."""
        docs = self.load_all() if self._wiki_dir.exists() else {}
        if not docs:
            return ""
        parts: list[str] = []
        for product_id, body in docs.items():
            parts.append(f"## Product: {product_id}\n\n{body.strip()}")
        return "\n\n---\n\n".join(parts)
```

- [ ] **Step 4: Tests pass.** `uv run pytest tests/test_wiki_loader.py -v` → 4 passed.

- [ ] **Step 5: Lint.** `uv run ruff check src/auto_reply/sources/wiki_loader.py tests/test_wiki_loader.py`.

- [ ] **Step 6: Commit.**

```bash
git add src/auto_reply/sources/wiki_loader.py tests/test_wiki_loader.py
git commit -m "feat(sources): WikiLoader reads wiki/*.md into memory"
```

---

## Task 3: Short-circuit reply templates

**Files:**
- Create: `src/auto_reply/pipeline/templates.py`
- Create: `tests/test_templates.py`

Greeting and `other` intents short-circuit the Drafter (no Sonnet call). They use deterministic templates. The text is dull on purpose — these are stopgaps that go to human review by default.

- [ ] **Step 1: Test**

```python
# tests/test_templates.py
from auto_reply.pipeline.templates import (
    GREETING_REPLY,
    OTHER_REPLY,
    short_circuit_reply,
)


def test_greeting_template_is_friendly_and_short():
    assert isinstance(GREETING_REPLY, str)
    assert 10 <= len(GREETING_REPLY) <= 400


def test_other_template_is_a_polite_handoff():
    assert "team" in OTHER_REPLY.lower() or "help" in OTHER_REPLY.lower()


def test_short_circuit_reply_for_greeting():
    assert short_circuit_reply("greeting") == GREETING_REPLY


def test_short_circuit_reply_for_other():
    assert short_circuit_reply("other") == OTHER_REPLY


def test_short_circuit_reply_for_non_short_circuit_returns_none():
    assert short_circuit_reply("pricing") is None
    assert short_circuit_reply("technical") is None
    assert short_circuit_reply("integration") is None
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implementation**

```python
# src/auto_reply/pipeline/templates.py
from __future__ import annotations

GREETING_REPLY = (
    "Hi! Thanks for reaching out — happy to help. "
    "What can we do for you today?"
)

OTHER_REPLY = (
    "Thanks for the message — I want to make sure I route this to the right "
    "place. Could you share a bit more about what you're trying to do, or "
    "which of our products this is about? Our team will follow up shortly."
)

_TABLE: dict[str, str] = {
    "greeting": GREETING_REPLY,
    "other": OTHER_REPLY,
}


def short_circuit_reply(intent: str) -> str | None:
    """Return a templated reply for intents that bypass the Drafter, else None."""
    return _TABLE.get(intent)
```

- [ ] **Step 4: Tests pass.** 5 passed.

- [ ] **Step 5: Lint.**

- [ ] **Step 6: Commit.**

```bash
git add src/auto_reply/pipeline/templates.py tests/test_templates.py
git commit -m "feat(pipeline): templated greeting/other short-circuit replies"
```

---

## Task 4: ContextBuilder

**Files:**
- Create: `src/auto_reply/pipeline/context_builder.py`
- Create: `tests/test_context_builder.py`

Returns a typed `DraftContext` containing two ready-to-send pieces: a `system_blocks` list (with `cache_control` on the wiki block) and a `messages` list. Also returns a JSON-serialisable snapshot for the `drafts.context_json` audit column.

- [ ] **Step 1: Test**

```python
# tests/test_context_builder.py
import json

from auto_reply.pipeline.context_builder import ContextBuilder, DraftContext


def _thread(thread_id: str = "t1") -> dict:
    return {
        "thread": {"id": thread_id, "username": "alice"},
        "messages": [
            {"role": "customer", "text": "Hi, I have a question"},
            {"role": "admin", "text": "Sure, what's up?"},
            {"role": "customer", "text": "How much is the Pro plan?"},
        ],
    }


def test_returns_draft_context_with_system_messages_and_snapshot():
    builder = ContextBuilder(wiki_text="WIKI BODY HERE")
    ctx = builder.build(thread=_thread(), intent="pricing")

    assert isinstance(ctx, DraftContext)
    # Two system blocks: persona, then wiki.
    assert len(ctx.system_blocks) == 2
    assert ctx.system_blocks[0]["type"] == "text"
    assert ctx.system_blocks[1]["type"] == "text"
    # The wiki block is cache-able.
    assert ctx.system_blocks[1].get("cache_control") == {"type": "ephemeral"}
    assert "WIKI BODY HERE" in ctx.system_blocks[1]["text"]
    # messages has the thread transcript and ends on the latest customer turn.
    assert isinstance(ctx.messages, list)
    assert ctx.messages[-1]["role"] == "user"
    assert "How much is the Pro plan" in ctx.messages[-1]["content"]
    # snapshot is JSON-serialisable and round-trips.
    s = json.loads(ctx.snapshot_json)
    assert s["intent"] == "pricing"
    assert s["thread_id"] == "t1"


def test_system_persona_block_mentions_anti_hallucination():
    builder = ContextBuilder(wiki_text="x")
    ctx = builder.build(thread=_thread(), intent="technical")
    persona = ctx.system_blocks[0]["text"].lower()
    assert "don't" in persona or "do not" in persona
    assert "i don't have" in persona or "i do not have" in persona


def test_thread_transcript_is_in_order():
    builder = ContextBuilder(wiki_text="x")
    ctx = builder.build(thread=_thread(), intent="technical")
    # All but the final customer message become prior turns in a single
    # transcript user/assistant trail (assistant = admin in our domain).
    roles = [m["role"] for m in ctx.messages]
    assert roles[0] == "user"  # first customer message
    assert roles[-1] == "user"  # latest customer message
    # No system role in messages list (those belong in system_blocks).
    assert "system" not in roles


def test_empty_thread_messages_raises():
    builder = ContextBuilder(wiki_text="x")
    import pytest

    with pytest.raises(ValueError):
        builder.build(thread={"thread": {"id": "t"}, "messages": []}, intent="technical")
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implementation**

```python
# src/auto_reply/pipeline/context_builder.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PERSONA_SYSTEM = """You are a customer-support agent for the LumenX platform (20 SaaS products).

Voice: warm, professional, concise. Plain English. No marketing tone.

Truthfulness rules (HARD):
- Use ONLY facts from the per-product wiki you are given in this conversation.
- Do not invent prices, refund windows, SLAs, integrations, or features.
- If the customer asks about something not in the wiki, say:
  "I don't have that information handy — let me check with the team and get back to you."
- Never quote a number, percentage, or duration that isn't already in the wiki.

Formatting:
- 1–3 short paragraphs. Lists are fine for steps. No emojis.
"""


@dataclass(frozen=True)
class DraftContext:
    system_blocks: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    snapshot_json: str  # for drafts.context_json audit column


class ContextBuilder:
    """Assemble the Drafter prompt.

    Phase 2 scope: persona + full wiki (cache_control=ephemeral on the wiki
    block) as system; current-thread transcript as messages. Per-customer
    cross-thread summary and feedback-log retrieval are deferred to Phase 3.
    """

    def __init__(self, wiki_text: str) -> None:
        self._wiki_text = wiki_text

    def build(self, *, thread: dict[str, Any], intent: str) -> DraftContext:
        messages = thread.get("messages", [])
        if not messages:
            raise ValueError("thread has no messages")

        # Map our roles to Anthropic's user/assistant turns.
        # customer → user, admin (or our agent) → assistant.
        api_messages: list[dict[str, Any]] = []
        for m in messages:
            role = "user" if m.get("role") == "customer" else "assistant"
            api_messages.append({"role": role, "content": str(m.get("text", ""))})

        # Ensure the final turn is from the customer (else there's nothing to reply to).
        if api_messages[-1]["role"] != "user":
            raise ValueError("last message is not from the customer")

        system_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": PERSONA_SYSTEM},
            {
                "type": "text",
                "text": "# Product wiki\n\n" + self._wiki_text,
                "cache_control": {"type": "ephemeral"},
            },
        ]

        snapshot = {
            "intent": intent,
            "thread_id": thread.get("thread", {}).get("id"),
            "username": thread.get("thread", {}).get("username"),
            "system_blocks": system_blocks,
            "messages": api_messages,
        }

        return DraftContext(
            system_blocks=system_blocks,
            messages=api_messages,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        )
```

- [ ] **Step 4: Tests pass.** 4 passed.

- [ ] **Step 5: Lint.**

- [ ] **Step 6: Commit.**

```bash
git add src/auto_reply/pipeline/context_builder.py tests/test_context_builder.py
git commit -m "feat(pipeline): ContextBuilder — persona + wiki + thread transcript"
```

---

## Task 5: Drafter

**Files:**
- Create: `src/auto_reply/pipeline/drafter.py`
- Create: `tests/test_drafter.py`

Thin wrapper around `LLMClient.complete` that:
- Uses Sonnet 4.6.
- Passes `system_blocks` as the cacheable system payload.
- Records `purpose='draft'` in `cost_log` (already done by LLMClient).

- [ ] **Step 1: Test**

```python
# tests/test_drafter.py
from unittest.mock import MagicMock

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.context_builder import DraftContext
from auto_reply.pipeline.drafter import Drafter


def _ctx() -> DraftContext:
    return DraftContext(
        system_blocks=[
            {"type": "text", "text": "PERSONA"},
            {"type": "text", "text": "WIKI", "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": "How much is Pro?"}],
        snapshot_json='{"x": 1}',
    )


def _make_llm(db, text: str = "Sure — the Pro plan is $25/month.") -> LLMClient:
    sdk = MagicMock()
    resp = MagicMock()
    resp.id = "msg_draft"
    resp.usage.input_tokens = 1000
    resp.usage.output_tokens = 40
    resp.usage.cache_read_input_tokens = 0
    resp.usage.cache_creation_input_tokens = 800
    resp.content = [MagicMock(text=text)]
    sdk.messages.create.return_value = resp
    return LLMClient(sdk=sdk, conn=db)


def test_drafter_returns_text(db):
    llm = _make_llm(db)
    drafter = Drafter(llm=llm)
    text = drafter.draft(_ctx())
    assert "Pro plan is $25" in text


def test_drafter_passes_system_blocks_to_llm(db):
    llm = _make_llm(db)
    drafter = Drafter(llm=llm)
    drafter.draft(_ctx())
    call = llm.sdk.messages.create.call_args
    kwargs = call.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    # system was passed as the list of blocks (NOT a string).
    assert isinstance(kwargs["system"], list)
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}


def test_drafter_writes_cost_row_with_purpose_draft(db):
    llm = _make_llm(db)
    drafter = Drafter(llm=llm)
    drafter.draft(_ctx())
    rows = db.execute(
        "SELECT purpose, model, cache_write_tokens FROM cost_log"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["purpose"] == "draft"
    assert rows[0]["model"] == "claude-sonnet-4-6"
    assert rows[0]["cache_write_tokens"] == 800
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implementation**

```python
# src/auto_reply/pipeline/drafter.py
from __future__ import annotations

from dataclasses import dataclass

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.context_builder import DraftContext

DRAFT_MODEL = "claude-sonnet-4-6"


@dataclass
class Drafter:
    """Produces a draft reply from a DraftContext via Sonnet, cost-logged."""

    llm: LLMClient
    model: str = DRAFT_MODEL

    def draft(self, ctx: DraftContext, *, max_tokens: int = 800) -> str:
        return self.llm.complete(
            model=self.model,
            system=ctx.system_blocks,
            messages=ctx.messages,
            purpose="draft",
            max_tokens=max_tokens,
        )
```

- [ ] **Step 4: Tests pass.** 3 passed.

- [ ] **Step 5: Lint.**

- [ ] **Step 6: Commit.**

```bash
git add src/auto_reply/pipeline/drafter.py tests/test_drafter.py
git commit -m "feat(pipeline): Drafter — Sonnet wrapper with cacheable system blocks"
```

---

## Task 6: Orchestrator — `process_message`

**Files:**
- Create: `src/auto_reply/pipeline/process_message.py`
- Create: `tests/test_process_message.py`

`process_message` ties it all together: classify intent → if short-circuit, use template; else build context + draft → write a row to `drafts`. Always sets `status='pending'`, `auto_sent=0`.

- [ ] **Step 1: Test**

```python
# tests/test_process_message.py
from unittest.mock import MagicMock

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.context_builder import ContextBuilder
from auto_reply.pipeline.drafter import Drafter
from auto_reply.pipeline.intent_router import IntentRouter
from auto_reply.pipeline.process_message import process_message


def _llm_with_responses(db, *texts: str) -> LLMClient:
    """LLMClient whose sdk returns each `text` in order on successive calls."""
    sdk = MagicMock()
    responses = []
    for t in texts:
        r = MagicMock()
        r.id = f"msg_{len(responses)}"
        r.usage.input_tokens = 50
        r.usage.output_tokens = 10
        r.usage.cache_read_input_tokens = 0
        r.usage.cache_creation_input_tokens = 0
        r.content = [MagicMock(text=t)]
        responses.append(r)
    sdk.messages.create.side_effect = responses
    return LLMClient(sdk=sdk, conn=db)


def _thread(text: str, intent_hint: str = "") -> dict:
    return {
        "thread": {"id": "t1", "username": "alice"},
        "messages": [{"role": "customer", "text": text}],
    }


def test_pricing_message_runs_full_pipeline(db):
    # Two LLM calls expected: intent (haiku) then draft (sonnet).
    llm = _llm_with_responses(
        db,
        '{"intent": "pricing"}',
        "The Pro plan is $25/month.",
    )
    intent_router = IntentRouter(llm=llm)
    drafter = Drafter(llm=llm)
    ctx_builder = ContextBuilder(wiki_text="WIKI")

    draft_id = process_message(
        thread=_thread("How much is Pro?"),
        conn=db,
        intent_router=intent_router,
        context_builder=ctx_builder,
        drafter=drafter,
    )

    row = db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row is not None
    assert row["intent"] == "pricing"
    assert row["sensitive"] == 1
    assert row["status"] == "pending"
    assert row["auto_sent"] == 0
    assert "$25" in row["draft_text"]
    assert row["customer_msg"] == "How much is Pro?"
    assert row["thread_id"] == "t1"


def test_greeting_short_circuits_no_draft_call(db):
    # Only ONE LLM call expected — the intent classifier. Drafter is never invoked.
    llm = _llm_with_responses(db, '{"intent": "greeting"}')
    intent_router = IntentRouter(llm=llm)
    drafter = Drafter(llm=llm)
    ctx_builder = ContextBuilder(wiki_text="WIKI")

    draft_id = process_message(
        thread=_thread("hi there"),
        conn=db,
        intent_router=intent_router,
        context_builder=ctx_builder,
        drafter=drafter,
    )

    row = db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row["intent"] == "greeting"
    assert row["sensitive"] == 0
    assert row["draft_text"].startswith("Hi!")
    # Only the intent classifier call hit the SDK.
    assert llm.sdk.messages.create.call_count == 1


def test_refund_marks_sensitive(db):
    llm = _llm_with_responses(
        db,
        '{"intent": "refund"}',
        "I'm sorry to hear that. I'll connect you with the team.",
    )
    intent_router = IntentRouter(llm=llm)
    drafter = Drafter(llm=llm)
    ctx_builder = ContextBuilder(wiki_text="WIKI")

    draft_id = process_message(
        thread=_thread("I want a refund"),
        conn=db,
        intent_router=intent_router,
        context_builder=ctx_builder,
        drafter=drafter,
    )
    row = db.execute("SELECT sensitive, intent FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row["sensitive"] == 1
    assert row["intent"] == "refund"
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implementation**

```python
# src/auto_reply/pipeline/process_message.py
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from auto_reply.pipeline.context_builder import ContextBuilder
from auto_reply.pipeline.drafter import Drafter
from auto_reply.pipeline.intent_router import IntentRouter
from auto_reply.pipeline.templates import short_circuit_reply
from auto_reply.store.db import transaction


def process_message(
    *,
    thread: dict[str, Any],
    conn: sqlite3.Connection,
    intent_router: IntentRouter,
    context_builder: ContextBuilder,
    drafter: Drafter,
) -> int:
    """Run the pipeline for one thread and write one row to `drafts`.

    Returns the new drafts.id.
    """
    messages = thread.get("messages", [])
    customer_msgs = [m for m in messages if m.get("role") == "customer"]
    if not customer_msgs:
        raise ValueError("thread has no customer messages")
    latest_customer = customer_msgs[-1]
    customer_text = str(latest_customer.get("text", ""))

    intent_result = intent_router.classify(customer_text)
    intent = intent_result.intent
    sensitive = intent_result.sensitive

    short = short_circuit_reply(intent)
    if short is not None:
        draft_text = short
        context_json = json.dumps(
            {
                "intent": intent,
                "thread_id": thread.get("thread", {}).get("id"),
                "short_circuit": True,
            },
            ensure_ascii=False,
        )
    else:
        ctx = context_builder.build(thread=thread, intent=intent)
        draft_text = drafter.draft(ctx)
        context_json = ctx.snapshot_json

    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO drafts
              (thread_id, customer_msg, draft_text, intent, sensitive,
               confidence, context_json, status, auto_sent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)
            """,
            (
                thread.get("thread", {}).get("id"),
                customer_text,
                draft_text,
                intent,
                1 if sensitive else 0,
                None,  # confidence is set in Phase 4
                context_json,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        draft_id = cursor.lastrowid

    assert draft_id is not None
    return draft_id
```

- [ ] **Step 4: Tests pass.** 3 passed.

- [ ] **Step 5: Lint.**

- [ ] **Step 6: Commit.**

```bash
git add src/auto_reply/pipeline/process_message.py tests/test_process_message.py
git commit -m "feat(pipeline): process_message orchestrator (intent -> context -> draft -> store)"
```

---

## Task 7: Poller

**Files:**
- Create: `src/auto_reply/sources/poller.py`
- Create: `tests/test_poller.py`

The Poller is an `async` loop that:
1. Calls `LumenXClient.get_inbox(since=<token>)`.
2. For each `entry` where `awaiting_admin` is true, fetches the full thread and runs `process_message`.
3. Records a marker in `threads_seen` so we don't re-process the same `last_customer_msg_id`.
4. Persists the server-time cursor for the next poll.
5. Sleeps `poll_interval_seconds`.

We pass `LumenXClient` and a `process_one(thread) -> int` callback in by reference so tests don't need to wire the whole pipeline.

- [ ] **Step 1: Test**

```python
# tests/test_poller.py
import asyncio
from unittest.mock import MagicMock

import pytest

from auto_reply.sources.poller import Poller


def _inbox_payload(server_time: str, entries: list[dict]) -> dict:
    return {"server_time": server_time, "awaiting_count": len(entries), "entries": entries}


@pytest.mark.asyncio
async def test_poller_processes_each_awaiting_entry_once(db):
    # First poll returns two entries; both are awaiting_admin.
    inbox_calls = [
        _inbox_payload("2026-05-27T10:00:00Z", [
            {"thread": {"id": "t1"}, "last_customer_message": {"id": "m1"}, "awaiting_admin": True},
            {"thread": {"id": "t2"}, "last_customer_message": {"id": "m2"}, "awaiting_admin": True},
        ]),
        _inbox_payload("2026-05-27T10:00:10Z", []),  # second poll: nothing new
    ]

    lumenx = MagicMock()
    lumenx.get_inbox.side_effect = inbox_calls
    lumenx.get_thread.side_effect = lambda tid: {
        "thread": {"id": tid, "username": "u"},
        "messages": [{"role": "customer", "text": f"hi from {tid}"}],
    }

    processed: list[str] = []

    def fake_process(thread: dict) -> int:
        processed.append(thread["thread"]["id"])
        return 999

    poller = Poller(
        lumenx=lumenx,
        conn=db,
        process_thread=fake_process,
        poll_interval_seconds=0.01,
    )
    # Run only two ticks then stop.
    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.05)
    poller.stop()
    await task

    assert sorted(processed) == ["t1", "t2"]


@pytest.mark.asyncio
async def test_poller_dedups_same_last_msg(db):
    # Both polls return the same entry (same last_customer_message.id).
    payload = _inbox_payload("2026-05-27T10:00:00Z", [
        {"thread": {"id": "t1"}, "last_customer_message": {"id": "m1"}, "awaiting_admin": True},
    ])
    lumenx = MagicMock()
    lumenx.get_inbox.return_value = payload
    lumenx.get_thread.return_value = {
        "thread": {"id": "t1", "username": "u"},
        "messages": [{"role": "customer", "text": "hi"}],
    }

    processed: list[str] = []
    def fake_process(thread: dict) -> int:
        processed.append(thread["thread"]["id"])
        return 1

    poller = Poller(
        lumenx=lumenx, conn=db,
        process_thread=fake_process, poll_interval_seconds=0.01,
    )
    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.05)
    poller.stop()
    await task

    # Even though we polled multiple times, t1's m1 was processed once.
    assert processed.count("t1") == 1


@pytest.mark.asyncio
async def test_poller_skips_not_awaiting_admin(db):
    payload = _inbox_payload("t0", [
        {"thread": {"id": "t1"}, "last_customer_message": {"id": "m1"}, "awaiting_admin": False},
    ])
    lumenx = MagicMock()
    lumenx.get_inbox.return_value = payload

    processed: list[str] = []
    def fake_process(thread: dict) -> int:
        processed.append(thread["thread"]["id"])
        return 1

    poller = Poller(
        lumenx=lumenx, conn=db,
        process_thread=fake_process, poll_interval_seconds=0.01,
    )
    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.03)
    poller.stop()
    await task

    assert processed == []


@pytest.mark.asyncio
async def test_poller_continues_after_process_failure(db, caplog):
    payload = _inbox_payload("t0", [
        {"thread": {"id": "good"}, "last_customer_message": {"id": "m1"}, "awaiting_admin": True},
        {"thread": {"id": "bad"}, "last_customer_message": {"id": "m2"}, "awaiting_admin": True},
    ])
    lumenx = MagicMock()
    lumenx.get_inbox.return_value = payload
    lumenx.get_thread.side_effect = lambda tid: {
        "thread": {"id": tid, "username": "u"},
        "messages": [{"role": "customer", "text": tid}],
    }

    def fake_process(thread: dict) -> int:
        if thread["thread"]["id"] == "bad":
            raise RuntimeError("draft failed")
        return 1

    poller = Poller(
        lumenx=lumenx, conn=db,
        process_thread=fake_process, poll_interval_seconds=0.01,
    )
    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.05)
    poller.stop()
    await task

    # "good" still got processed; the failure on "bad" did not crash the loop.
    # The bad thread's marker should NOT be written (so it can retry next time).
    seen = {r["thread_id"] for r in db.execute("SELECT thread_id FROM threads_seen")}
    assert "good" in seen
    assert "bad" not in seen
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implementation**

```python
# src/auto_reply/sources/poller.py
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

from auto_reply.sources.lumenx import LumenXClient
from auto_reply.store.db import transaction

log = logging.getLogger(__name__)


class Poller:
    """Polls /api/admin/inbox and dispatches awaiting threads.

    The pipeline (intent → context → draft → store) is provided as a callback
    so tests can swap it out cheaply.
    """

    def __init__(
        self,
        *,
        lumenx: LumenXClient,
        conn: sqlite3.Connection,
        process_thread: Callable[[dict[str, Any]], int],
        poll_interval_seconds: float = 10.0,
    ) -> None:
        self._lumenx = lumenx
        self._conn = conn
        self._process_thread = process_thread
        self._interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._since: str | None = self._load_since()

    # ── state helpers ────────────────────────────────────────────────────
    def _load_since(self) -> str | None:
        row = self._conn.execute(
            "SELECT last_seen_at FROM threads_seen WHERE thread_id = '__cursor__'"
        ).fetchone()
        return row["last_seen_at"] if row else None

    def _save_since(self, value: str) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO threads_seen (thread_id, last_msg_id, last_seen_at) "
                "VALUES ('__cursor__', NULL, ?)",
                (value,),
            )

    def _already_seen(self, thread_id: str, last_msg_id: str | None) -> bool:
        row = self._conn.execute(
            "SELECT last_msg_id FROM threads_seen WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return row is not None and row["last_msg_id"] == last_msg_id

    def _mark_seen(self, thread_id: str, last_msg_id: str | None) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO threads_seen (thread_id, last_msg_id, last_seen_at) "
                "VALUES (?, ?, ?)",
                (thread_id, last_msg_id, datetime.now(timezone.utc).isoformat()),
            )

    # ── public API ───────────────────────────────────────────────────────
    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._tick)
            except Exception:
                log.exception("poller tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    # ── one cycle ────────────────────────────────────────────────────────
    def _tick(self) -> None:
        payload = self._lumenx.get_inbox(since=self._since)
        for entry in payload.get("entries", []) or []:
            if not entry.get("awaiting_admin"):
                continue
            thread_id = entry.get("thread", {}).get("id")
            last_msg = entry.get("last_customer_message") or {}
            last_msg_id = last_msg.get("id")
            if thread_id is None:
                continue
            if self._already_seen(thread_id, last_msg_id):
                continue
            try:
                full = self._lumenx.get_thread(thread_id)
                self._process_thread(full)
            except Exception:
                log.exception("process failed for thread %s", thread_id)
                continue  # do NOT mark seen — try again next poll
            self._mark_seen(thread_id, last_msg_id)

        server_time = payload.get("server_time")
        if server_time:
            self._since = server_time
            self._save_since(server_time)
```

- [ ] **Step 4: Tests pass.** 4 passed.

- [ ] **Step 5: Lint.**

- [ ] **Step 6: Commit.**

```bash
git add src/auto_reply/sources/poller.py tests/test_poller.py
git commit -m "feat(sources): async Poller with dedup + cursor persistence + per-thread isolation"
```

---

## Task 8: Dashboard `/agent/queue` (read-only)

**Files:**
- Create: `src/auto_reply/web/dashboard.py`
- Create: `src/auto_reply/web/templates/base.html`
- Create: `src/auto_reply/web/templates/queue.html`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Test**

```python
# tests/test_dashboard.py
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auto_reply.web.dashboard import make_router


def _app(db, password: str = "pw") -> FastAPI:
    app = FastAPI()
    router = make_router(conn=db, password=password)
    app.include_router(router)
    return app


def _seed_drafts(db) -> None:
    db.execute(
        "INSERT INTO drafts (thread_id, customer_msg, draft_text, intent, sensitive, "
        "status, auto_sent, created_at) VALUES "
        "('t1', 'How much is Pro?', 'It is $25', 'pricing', 1, 'pending', 0, '2026-05-27T10:00:00+00:00'),"
        "('t2', 'hi there',          'Hi!',       'greeting',0, 'pending', 0, '2026-05-27T10:00:01+00:00'),"
        "('t3', 'old one',           'whatever',  'technical',0,'sent',    0, '2026-05-27T09:00:00+00:00')"
    )


def test_queue_requires_auth(db):
    _seed_drafts(db)
    client = TestClient(_app(db))
    r = client.get("/agent/queue")
    assert r.status_code == 401


def test_queue_rejects_wrong_password(db):
    client = TestClient(_app(db, password="correct"))
    r = client.get("/agent/queue", auth=("admin", "wrong"))
    assert r.status_code == 401


def test_queue_shows_only_pending_drafts(db):
    _seed_drafts(db)
    client = TestClient(_app(db, password="pw"))
    r = client.get("/agent/queue", auth=("admin", "pw"))
    assert r.status_code == 200
    body = r.text
    # Pending drafts visible.
    assert "How much is Pro?" in body
    assert "hi there" in body
    # Already-sent drafts NOT visible.
    assert "old one" not in body


def test_queue_shows_intent_and_sensitive_flag(db):
    _seed_drafts(db)
    client = TestClient(_app(db, password="pw"))
    r = client.get("/agent/queue", auth=("admin", "pw"))
    body = r.text
    assert "pricing" in body
    assert "sensitive" in body.lower()  # the pricing row has the sensitive badge somewhere
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implementations**

`src/auto_reply/web/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}auto-reply{% endblock %}</title>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; color: #222; }
    h1 { font-size: 1.4rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #eee; vertical-align: top; }
    th { background: #fafafa; font-weight: 600; }
    .pill { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 1rem; font-size: 0.75rem; }
    .pill-sensitive { background: #fee; color: #900; }
    .pill-intent    { background: #eef; color: #225; }
    pre.context { white-space: pre-wrap; max-height: 14rem; overflow: auto; background: #f7f7f7; padding: 0.5rem; border-radius: 4px; font-size: 0.75rem; }
    .meta { color: #777; font-size: 0.8rem; }
  </style>
</head>
<body>
  <header><h1>auto-reply / {% block heading %}{% endblock %}</h1></header>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

`src/auto_reply/web/templates/queue.html`:

```html
{% extends "base.html" %}
{% block title %}queue · auto-reply{% endblock %}
{% block heading %}queue ({{ drafts|length }} pending){% endblock %}

{% block content %}
{% if not drafts %}
  <p>Nothing pending. The poller will queue new customer messages here.</p>
{% else %}
  <table>
    <thead>
      <tr>
        <th>When</th>
        <th>Thread</th>
        <th>Intent</th>
        <th>Customer message</th>
        <th>Draft reply</th>
      </tr>
    </thead>
    <tbody>
      {% for d in drafts %}
      <tr>
        <td class="meta">{{ d.created_at }}</td>
        <td><code>{{ d.thread_id }}</code></td>
        <td>
          <span class="pill pill-intent">{{ d.intent }}</span>
          {% if d.sensitive %}<span class="pill pill-sensitive">sensitive</span>{% endif %}
        </td>
        <td>{{ d.customer_msg }}</td>
        <td>{{ d.draft_text }}</td>
      </tr>
      <tr>
        <td colspan="5">
          <details>
            <summary class="meta">show context</summary>
            <pre class="context">{{ d.context_json }}</pre>
          </details>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
{% endif %}
{% endblock %}
```

`src/auto_reply/web/dashboard.py`:

```python
# src/auto_reply/web/dashboard.py
from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"


def make_router(*, conn: sqlite3.Connection, password: str) -> APIRouter:
    router = APIRouter(prefix="/agent", tags=["agent"])
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    security = HTTPBasic()

    def require_admin(creds: HTTPBasicCredentials = Depends(security)) -> None:
        # Constant-time compare to avoid timing oracle.
        if not secrets.compare_digest(creds.password, password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bad credentials",
                headers={"WWW-Authenticate": "Basic"},
            )

    @router.get("/queue")
    def queue(request: Request, _: None = Depends(require_admin)):
        rows = conn.execute(
            "SELECT id, thread_id, customer_msg, draft_text, intent, sensitive, "
            "context_json, created_at "
            "FROM drafts WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        drafts = [dict(r) for r in rows]
        return templates.TemplateResponse(
            request, "queue.html", {"drafts": drafts}
        )

    return router
```

- [ ] **Step 4: Tests pass.** 4 passed.

- [ ] **Step 5: Lint.** `uv run ruff check src/auto_reply/web/dashboard.py tests/test_dashboard.py`.

- [ ] **Step 6: Commit.**

```bash
git add src/auto_reply/web/dashboard.py src/auto_reply/web/templates tests/test_dashboard.py
git commit -m "feat(web): /agent/queue read-only dashboard with HTTP Basic auth"
```

---

## Task 9: Wire it all in `web/app.py` (lifespan + dashboard + smoke test)

**Files:**
- Modify: `src/auto_reply/web/app.py`
- Modify: `tests/test_web_health.py` (add a test for the queue route registration)

`create_app()` builds the pipeline pieces once, starts the Poller on FastAPI lifespan startup, stops it on shutdown, and mounts the dashboard router.

- [ ] **Step 1: Replace `src/auto_reply/web/app.py`**

```python
# src/auto_reply/web/app.py
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import Anthropic
from fastapi import FastAPI

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.context_builder import ContextBuilder
from auto_reply.pipeline.drafter import Drafter
from auto_reply.pipeline.intent_router import IntentRouter
from auto_reply.pipeline.process_message import process_message
from auto_reply.settings import get_settings
from auto_reply.sources.lumenx import LumenXClient
from auto_reply.sources.poller import Poller
from auto_reply.sources.wiki_loader import WikiLoader
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations, current_version
from auto_reply.tls import enable_system_certs
from auto_reply.web.dashboard import make_router

WIKI_DIR = Path(__file__).resolve().parents[3] / "wiki"

log = logging.getLogger(__name__)


def create_app(*, run_poller: bool = True) -> FastAPI:
    enable_system_certs()
    settings = get_settings()
    conn = connect(settings.agent_db_path)
    apply_migrations(conn)

    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)
    intent_router = IntentRouter(llm=llm)
    wiki_text = WikiLoader(WIKI_DIR).concatenated()
    ctx_builder = ContextBuilder(wiki_text=wiki_text)
    drafter = Drafter(llm=llm)
    lumenx = LumenXClient(settings.lumenx_base, settings.lumenx_admin_token)

    def _process(thread):
        return process_message(
            thread=thread,
            conn=conn,
            intent_router=intent_router,
            context_builder=ctx_builder,
            drafter=drafter,
        )

    poller = Poller(
        lumenx=lumenx,
        conn=conn,
        process_thread=_process,
        poll_interval_seconds=10.0,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task: asyncio.Task | None = None
        if run_poller:
            task = asyncio.create_task(poller.run())
            log.info("poller started")
        try:
            yield
        finally:
            if task is not None:
                poller.stop()
                await task
                log.info("poller stopped")
            lumenx.close()

    app = FastAPI(title="auto-reply-agent", version="0.0.0", lifespan=lifespan)
    app.state.db = conn
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "schema_version": current_version(conn)}

    app.include_router(make_router(conn=conn, password=settings.agent_dashboard_password))
    return app
```

Note: the wiki path goes UP four levels from `web/app.py` because the file lives at `src/auto_reply/web/app.py` and the repo root is four parents up. Verify by running `python -c "from pathlib import Path; print(Path('src/auto_reply/web/app.py').resolve().parents[3])"` — adjust the index if wrong.

- [ ] **Step 2: Update `tests/test_web_health.py`**

Append a new test:

```python
def test_queue_route_registered(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMENX_ADMIN_TOKEN", "lmx_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_DASHBOARD_PASSWORD", "pw")
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent.db"))

    from auto_reply.settings import get_settings
    get_settings.cache_clear()

    from auto_reply.web.app import create_app
    app = create_app(run_poller=False)  # don't start the poller in tests
    client = TestClient(app)
    # /agent/queue is mounted (returns 401 without auth, not 404).
    r = client.get("/agent/queue")
    assert r.status_code == 401
```

Also confirm the existing `test_health_endpoint` still passes after the lifespan change. If it calls `create_app()`, change it to `create_app(run_poller=False)`.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -v`
Expected: everything green. New count target: 39 (Phase 1 baseline) + this phase's tests (~22) = **~61 passing**.

- [ ] **Step 4: Lint**

Run: `uv run ruff check src tests scripts`
Expected: no errors.

- [ ] **Step 5: Manual smoke test (real LumenX + Anthropic)**

a) Start the app:
```
uv run uvicorn auto_reply.web.app:create_app --factory --port 8000
```
You should see log lines from the poller as it polls every 10s.

b) In another shell, send a fake customer message to LumenX:
```
TOKEN=$(grep LUMENX_ADMIN_TOKEN .env | cut -d= -f2)
BASE=https://lumenx-demo.up.railway.app
# Pick any seed thread; or create a new one via /api/threads.
# Easiest: use a known live thread and post a customer message.
# Inspect /api/admin/threads first to find one without seeded=1.
```
   Alternative: open `https://lumenx-demo.up.railway.app/chat` in a browser, start a chat, and ask a pricing question.

c) Wait up to 15 seconds. Open `http://127.0.0.1:8000/agent/queue` (Basic Auth: any username, password from your `.env`). You should see the new draft with intent, sensitive flag, customer message, draft text, and an expandable "show context" panel.

d) Stop the server with Ctrl+C — you should see `poller stopped` in the log.

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/web/app.py tests/test_web_health.py
git commit -m "feat(web): lifespan starts/stops Poller; dashboard router mounted"
```

---

## Task 10: Final lint + suite + milestone

**Files:** none

- [ ] **Step 1: Full suite**

Run: `uv run pytest -v`
Expected: target ~61 tests passing, 0 failed.

- [ ] **Step 2: Ruff**

Run: `uv run ruff check src tests scripts`

- [ ] **Step 3: Milestone commit**

```bash
git commit --allow-empty -m "chore: phase 2 green — draft pipeline + queue dashboard, no auto-send"
```

---

## Self-review notes

- **Spec coverage**
  - §5.1 Poller — Task 7 (with persistence, dedup, error isolation, configurable interval).
  - §5.2 IntentRouter integration + short-circuit — Tasks 3, 6.
  - §5.3 ContextBuilder — Task 4 (persona + wiki). Cross-thread summary & feedback retrieval **deferred** to Phase 3; documented above.
  - §5.4 Drafter with prompt caching — Task 5 (cache_control on the wiki block).
  - §5.9 dashboard Queue tab (read-only) — Task 8. Activity/Costs tabs are Phase 3.
  - Cost logging via Phase 0 `LLMClient` — every Sonnet draft + Haiku intent call writes a `cost_log` row.
- **Placeholders:** none — every code/SQL/template/command step shows the full content.
- **Type consistency:** `IntentRouter.classify` → `IntentResult`, consumed by `process_message`. `ContextBuilder.build` → `DraftContext`, consumed by `Drafter.draft`. `Poller.process_thread` callback is `Callable[[dict], int]` and is satisfied by the `_process` closure in `create_app`.
- **Risk callouts**
  - `process_message` runs synchronously inside `asyncio.to_thread` to avoid blocking the event loop on Anthropic calls. Sqlite with WAL is happy with this; tests confirm.
  - The Poller deduplicates by `(thread_id, last_customer_message.id)`. If LumenX ever changes that ID's shape (e.g., uses `last_customer_at` instead), dedup degrades. Phase 5 will revisit when adding the kill-switch + rate limiter.
  - The dashboard's Basic Auth is fine for a single-admin tool over HTTPS; over plain HTTP it leaks the password. Deployment on Railway is HTTPS-only by default.
- **Open question parked for Phase 3**
  - Per-customer cross-thread summary: when re-enabled, use a cheap Haiku call cached per username (TTL ~24h). Place behind a `ContextBuilder` constructor flag rather than a separate class.
