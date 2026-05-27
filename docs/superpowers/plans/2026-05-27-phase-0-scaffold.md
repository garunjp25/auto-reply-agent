# Phase 0 — Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the empty `auto_reply` Python package with a runnable FastAPI app, a SQLite store with migrations, a typed settings layer, and a cost-logging wrapper around the Anthropic SDK. No business logic yet — every later phase plugs into these foundations.

**Architecture:** Single Python 3.11+ package under `src/auto_reply/` with subpackages for `pipeline`, `sources`, `store`, `web`, `training`. SQLite via stdlib `sqlite3` with a hand-rolled migration runner (no SQLAlchemy in Phase 0 — keep dependencies minimal). FastAPI app exposes `/health` only. Anthropic calls flow through `auto_reply.llm.client.LLMClient`, which writes one `cost_log` row per call.

**Tech Stack:** Python 3.11+ · `uv` for env/lockfile · FastAPI · `pydantic-settings` · `anthropic` SDK · stdlib `sqlite3` · `pytest` + `pytest-asyncio` · `httpx` (FastAPI test client)

---

## File structure produced by this phase

```
phase2-live/
├── pyproject.toml
├── .python-version
├── .gitignore
├── .env.example
├── src/
│   └── auto_reply/
│       ├── __init__.py
│       ├── settings.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── pricing.py
│       │   └── client.py
│       ├── store/
│       │   ├── __init__.py
│       │   ├── db.py
│       │   ├── migrations.py
│       │   └── migrations_sql/
│       │       └── 0001_initial.sql
│       ├── pipeline/__init__.py
│       ├── sources/__init__.py
│       ├── training/__init__.py
│       └── web/
│           ├── __init__.py
│           └── app.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_settings.py
    ├── test_store.py
    ├── test_llm_client.py
    └── test_web_health.py
```

Each module has one clear responsibility:
- `settings.py` — typed env config
- `store/db.py` — connection factory + transaction helper
- `store/migrations.py` — discover & apply SQL files in order
- `llm/pricing.py` — model→USD-per-MTok table, pure data
- `llm/client.py` — wraps `anthropic.Anthropic`, writes `cost_log` rows
- `web/app.py` — FastAPI app, `/health` only in this phase

---

## Task 1: Initialize project and tooling

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `.env.example`

- [ ] **Step 1: Verify `uv` is installed**

Run: `uv --version`
Expected: prints a version number (e.g. `uv 0.5.x`). If missing, install from https://docs.astral.sh/uv/.

- [ ] **Step 2: Write `.python-version`**

```
3.11
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "auto-reply"
version = "0.0.0"
description = "Auto-reply LLM agent for LumenX"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "anthropic>=0.40",
  "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "ruff>=0.7",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/auto_reply"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 4: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
data/
.env
*.egg-info/
dist/
build/
wiki/
```

- [ ] **Step 5: Write `.env.example`**

```
# LumenX integration
LUMENX_BASE=https://lumenx-demo.up.railway.app
LUMENX_ADMIN_TOKEN=lmx_replace_me

# Anthropic
ANTHROPIC_API_KEY=sk-ant-replace_me

# Agent behavior
THRESHOLD=0.85
AUTO_SEND_ENABLED=false
DAILY_SPEND_CAP_USD=5.00

# Dashboard
AGENT_DASHBOARD_PASSWORD=change_me

# Storage
AGENT_DB_PATH=./data/agent.db
```

- [ ] **Step 6: Install dependencies**

Run: `uv sync --extra dev`
Expected: creates `.venv`, writes `uv.lock`, installs all deps without error.

- [ ] **Step 7: Commit**

```bash
git init
git add pyproject.toml .python-version .gitignore .env.example uv.lock
git commit -m "chore: bootstrap project with uv, FastAPI, pydantic-settings, anthropic"
```

> Note: this is the first commit. If `git init` fails because there is already
> a repo, skip it.

---

## Task 2: Package skeleton

**Files:**
- Create: `src/auto_reply/__init__.py`
- Create: `src/auto_reply/pipeline/__init__.py`
- Create: `src/auto_reply/sources/__init__.py`
- Create: `src/auto_reply/store/__init__.py`
- Create: `src/auto_reply/training/__init__.py`
- Create: `src/auto_reply/web/__init__.py`
- Create: `src/auto_reply/llm/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create empty `__init__.py` for each package above**

Each file's content:

```python
```

(All eight files are intentionally empty.)

- [ ] **Step 2: Verify import works**

Run: `uv run python -c "import auto_reply; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/auto_reply tests/__init__.py
git commit -m "chore: package skeleton with empty subpackages"
```

---

## Task 3: Settings module

**Files:**
- Create: `src/auto_reply/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
import os
from pathlib import Path

import pytest

from auto_reply.settings import Settings


def test_settings_reads_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LUMENX_BASE", "https://example.test")
    monkeypatch.setenv("LUMENX_ADMIN_TOKEN", "lmx_abc")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xyz")
    monkeypatch.setenv("AGENT_DASHBOARD_PASSWORD", "hunter2")
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("THRESHOLD", "0.9")
    monkeypatch.setenv("AUTO_SEND_ENABLED", "true")
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "2.50")

    s = Settings()

    assert s.lumenx_base == "https://example.test"
    assert s.lumenx_admin_token == "lmx_abc"
    assert s.anthropic_api_key == "sk-ant-xyz"
    assert s.threshold == 0.9
    assert s.auto_send_enabled is True
    assert s.daily_spend_cap_usd == 2.50
    assert s.agent_db_path == tmp_path / "agent.db"


def test_settings_missing_required(monkeypatch):
    for var in ("LUMENX_ADMIN_TOKEN", "ANTHROPIC_API_KEY", "AGENT_DASHBOARD_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LUMENX_BASE", "x")
    with pytest.raises(Exception):
        Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_settings.py -v`
Expected: FAIL with `ImportError: cannot import name 'Settings' from 'auto_reply.settings'` (or module not found).

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/settings.py
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    lumenx_base: str = Field(default="https://lumenx-demo.up.railway.app")
    lumenx_admin_token: str
    anthropic_api_key: str

    threshold: float = 0.85
    auto_send_enabled: bool = False
    daily_spend_cap_usd: float = 5.0

    agent_dashboard_password: str
    agent_db_path: Path = Path("./data/agent.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/auto_reply/settings.py tests/test_settings.py
git commit -m "feat(settings): typed env config via pydantic-settings"
```

---

## Task 4: SQLite store — connection helper

**Files:**
- Create: `src/auto_reply/store/db.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store.py
import sqlite3
from pathlib import Path

import pytest

from auto_reply.store.db import connect, transaction


def test_connect_creates_parent_dir(tmp_path: Path):
    db_path = tmp_path / "nested" / "agent.db"
    conn = connect(db_path)
    assert db_path.exists()
    assert db_path.parent.is_dir()
    conn.close()


def test_connect_enables_foreign_keys(tmp_path: Path):
    conn = connect(tmp_path / "a.db")
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
    conn.close()


def test_transaction_commits_on_success(tmp_path: Path):
    conn = connect(tmp_path / "b.db")
    conn.execute("CREATE TABLE t (x INTEGER)")
    with transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
    rows = conn.execute("SELECT x FROM t").fetchall()
    assert rows == [(1,)]
    conn.close()


def test_transaction_rolls_back_on_exception(tmp_path: Path):
    conn = connect(tmp_path / "c.db")
    conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")
    rows = conn.execute("SELECT x FROM t").fetchall()
    assert rows == []
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL with `ImportError: cannot import name 'connect' from 'auto_reply.store.db'`.

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/store/db.py
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults.

    Creates the parent directory if needed. Enables foreign keys and WAL.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """BEGIN/COMMIT, rolling back on any exception."""
    conn.execute("BEGIN")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/auto_reply/store/db.py tests/test_store.py
git commit -m "feat(store): sqlite connect() + transaction() helpers"
```

---

## Task 5: SQLite store — initial migration

**Files:**
- Create: `src/auto_reply/store/migrations_sql/0001_initial.sql`
- Create: `src/auto_reply/store/migrations.py`
- Modify: `tests/test_store.py` (append migration tests)

- [ ] **Step 1: Write the initial migration SQL**

```sql
-- src/auto_reply/store/migrations_sql/0001_initial.sql
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS threads_seen (
  thread_id TEXT PRIMARY KEY,
  last_msg_id TEXT,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  customer_msg TEXT NOT NULL,
  draft_text TEXT NOT NULL,
  intent TEXT NOT NULL,
  sensitive INTEGER NOT NULL DEFAULT 0,
  confidence REAL,
  context_json TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  auto_sent INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS drafts_status_idx ON drafts(status);
CREATE INDEX IF NOT EXISTS drafts_thread_idx ON drafts(thread_id);

CREATE TABLE IF NOT EXISTS sent_replies (
  draft_id INTEGER PRIMARY KEY REFERENCES drafts(id),
  final_text TEXT NOT NULL,
  edit_distance REAL NOT NULL DEFAULT 0.0,
  sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  draft_id INTEGER NOT NULL REFERENCES drafts(id),
  thumb INTEGER,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS training_labels (
  draft_id INTEGER PRIMARY KEY REFERENCES drafts(id),
  label INTEGER NOT NULL,
  source TEXT NOT NULL,
  features_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call_id TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0.0,
  purpose TEXT NOT NULL,
  draft_id INTEGER,
  at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS cost_log_at_idx ON cost_log(at);
CREATE INDEX IF NOT EXISTS cost_log_purpose_idx ON cost_log(purpose);

CREATE TABLE IF NOT EXISTS wiki_index (
  product_id TEXT NOT NULL,
  chunk_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  embedding BLOB NOT NULL,
  PRIMARY KEY (product_id, chunk_id)
);
```

- [ ] **Step 2: Append failing migration tests**

Append to `tests/test_store.py`:

```python
from auto_reply.store.migrations import apply_migrations, current_version


def test_apply_migrations_runs_0001(tmp_path: Path):
    conn = connect(tmp_path / "m.db")
    apply_migrations(conn)
    assert current_version(conn) == 1
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    expected = {
        "schema_version", "threads_seen", "drafts", "sent_replies",
        "feedback", "training_labels", "cost_log", "wiki_index",
    }
    assert expected.issubset(tables)
    conn.close()


def test_apply_migrations_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "m.db")
    apply_migrations(conn)
    apply_migrations(conn)
    assert current_version(conn) == 1
    conn.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_store.py -v`
Expected: 2 new tests FAIL with `ImportError`.

- [ ] **Step 4: Write the migration runner**

```python
# src/auto_reply/store/migrations.py
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from auto_reply.store.db import transaction

MIGRATIONS_DIR = Path(__file__).parent / "migrations_sql"


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def apply_migrations(conn: sqlite3.Connection) -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for path in files:
        version = int(path.name.split("_", 1)[0])
        if version <= current_version(conn):
            continue
        sql = path.read_text(encoding="utf-8")
        with transaction(conn):
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: 6 passed (4 from Task 4 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/store/migrations.py src/auto_reply/store/migrations_sql tests/test_store.py
git commit -m "feat(store): initial schema migration + idempotent runner"
```

---

## Task 6: LLM pricing table

**Files:**
- Create: `src/auto_reply/llm/pricing.py`
- Test: `tests/test_llm_client.py` (pricing tests only in this task)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_client.py
import pytest

from auto_reply.llm.pricing import MODEL_PRICES, cost_usd


def test_known_model_prices_loaded():
    assert "claude-haiku-4-5-20251001" in MODEL_PRICES
    assert "claude-sonnet-4-6" in MODEL_PRICES


def test_cost_usd_computes_correctly():
    # Sonnet 4.6: $3/MTok in, $15/MTok out (per design spec)
    c = cost_usd(
        model="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert c == pytest.approx(3.0 + 15.0)


def test_cost_usd_applies_cache_discount():
    # Cache reads at 10% of input; cache writes at 125% of input (Anthropic standard)
    c = cost_usd(
        model="claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=1_000_000,
        cache_write_tokens=0,
    )
    assert c == pytest.approx(3.0 * 0.10)

    c2 = cost_usd(
        model="claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=1_000_000,
    )
    assert c2 == pytest.approx(3.0 * 1.25)


def test_cost_usd_unknown_model_returns_zero():
    c = cost_usd("nonexistent-model", 100, 100, 0, 0)
    assert c == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/llm/pricing.py
"""USD per million tokens. Adjust if Anthropic pricing changes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float


MODEL_PRICES: dict[str, Price] = {
    # Reference pricing as of 2026-05 — verify before going to production.
    "claude-haiku-4-5-20251001": Price(input_per_mtok=1.0, output_per_mtok=5.0),
    "claude-sonnet-4-6": Price(input_per_mtok=3.0, output_per_mtok=15.0),
    "claude-opus-4-7": Price(input_per_mtok=15.0, output_per_mtok=75.0),
}

CACHE_READ_DISCOUNT = 0.10   # cached input billed at 10% of input rate
CACHE_WRITE_MULTIPLIER = 1.25  # cache writes billed at 125% of input rate


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> float:
    price = MODEL_PRICES.get(model)
    if price is None:
        return 0.0
    return (
        input_tokens * price.input_per_mtok
        + output_tokens * price.output_per_mtok
        + cache_read_tokens * price.input_per_mtok * CACHE_READ_DISCOUNT
        + cache_write_tokens * price.input_per_mtok * CACHE_WRITE_MULTIPLIER
    ) / 1_000_000
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/auto_reply/llm/pricing.py tests/test_llm_client.py
git commit -m "feat(llm): pricing table + cost_usd() with cache discounts"
```

---

## Task 7: Cost-logging LLM client wrapper

**Files:**
- Create: `src/auto_reply/llm/client.py`
- Modify: `tests/test_llm_client.py` (append client tests)
- Create: `tests/conftest.py`

- [ ] **Step 1: Write the shared conftest**

```python
# tests/conftest.py
import sqlite3
from pathlib import Path

import pytest

from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "test.db")
    apply_migrations(conn)
    yield conn
    conn.close()
```

- [ ] **Step 2: Append failing client tests**

Append to `tests/test_llm_client.py`:

```python
from unittest.mock import MagicMock

from auto_reply.llm.client import LLMClient


class _FakeUsage:
    def __init__(self, in_=10, out=20, cr=0, cw=0):
        self.input_tokens = in_
        self.output_tokens = out
        self.cache_read_input_tokens = cr
        self.cache_creation_input_tokens = cw


class _FakeResponse:
    def __init__(self):
        self.id = "msg_test_123"
        self.usage = _FakeUsage(in_=10, out=20)
        self.content = [MagicMock(text="hello world")]


def test_client_logs_cost_row(db):
    sdk = MagicMock()
    sdk.messages.create.return_value = _FakeResponse()

    client = LLMClient(sdk=sdk, conn=db)
    text = client.complete(
        model="claude-sonnet-4-6",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        purpose="draft",
    )

    assert text == "hello world"
    rows = db.execute(
        "SELECT model, input_tokens, output_tokens, cost_usd, purpose FROM cost_log"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["model"] == "claude-sonnet-4-6"
    assert r["input_tokens"] == 10
    assert r["output_tokens"] == 20
    assert r["purpose"] == "draft"
    assert r["cost_usd"] > 0


def test_client_attaches_draft_id_when_given(db):
    sdk = MagicMock()
    sdk.messages.create.return_value = _FakeResponse()

    client = LLMClient(sdk=sdk, conn=db)
    client.complete(
        model="claude-haiku-4-5-20251001",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        purpose="intent",
        draft_id=42,
    )
    row = db.execute("SELECT draft_id, purpose FROM cost_log").fetchone()
    assert row["draft_id"] == 42
    assert row["purpose"] == "intent"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: 2 new tests FAIL with `ImportError`.

- [ ] **Step 4: Write the implementation**

```python
# src/auto_reply/llm/client.py
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from auto_reply.llm.pricing import cost_usd
from auto_reply.store.db import transaction


@dataclass
class LLMClient:
    """Thin wrapper around the Anthropic SDK that records cost per call.

    Every call writes one row to `cost_log`. Business code must not call the
    SDK directly.
    """

    sdk: Anthropic
    conn: sqlite3.Connection

    def complete(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        purpose: str,
        draft_id: int | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        """Call messages.create, log cost, return the assistant text.

        `system` may be a plain string or a list of system blocks (used for
        prompt caching with `cache_control`).
        """
        resp = self.sdk.messages.create(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        usage = resp.usage
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        cr_tok = getattr(usage, "cache_read_input_tokens", 0) or 0
        cw_tok = getattr(usage, "cache_creation_input_tokens", 0) or 0

        usd = cost_usd(model, in_tok, out_tok, cr_tok, cw_tok)

        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO cost_log
                  (call_id, model, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens, cost_usd,
                   purpose, draft_id, at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resp.id,
                    model,
                    in_tok,
                    out_tok,
                    cr_tok,
                    cw_tok,
                    usd,
                    purpose,
                    draft_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

        return resp.content[0].text
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_client.py -v`
Expected: 6 passed (4 pricing + 2 client).

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/llm/client.py tests/test_llm_client.py tests/conftest.py
git commit -m "feat(llm): cost-logging client wrapper around Anthropic SDK"
```

---

## Task 8: FastAPI app with /health

**Files:**
- Create: `src/auto_reply/web/app.py`
- Test: `tests/test_web_health.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_health.py
from fastapi.testclient import TestClient

from auto_reply.web.app import create_app


def test_health_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMENX_ADMIN_TOKEN", "lmx_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_DASHBOARD_PASSWORD", "pw")
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent.db"))

    from auto_reply.settings import get_settings
    get_settings.cache_clear()

    app = create_app()
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == 1
    assert (tmp_path / "agent.db").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_health.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/web/app.py
from fastapi import FastAPI

from auto_reply.settings import get_settings
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations, current_version


def create_app() -> FastAPI:
    app = FastAPI(title="auto-reply-agent", version="0.0.0")
    settings = get_settings()

    # Ensure DB exists and is at latest schema before serving.
    conn = connect(settings.agent_db_path)
    apply_migrations(conn)
    app.state.db = conn
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "schema_version": current_version(conn),
        }

    return app


app = create_app()  # uvicorn entrypoint
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_web_health.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the app manually and hit /health**

Run (in one terminal): `uv run uvicorn auto_reply.web.app:app --reload --port 8000`
Run (in another): `curl http://127.0.0.1:8000/health`
Expected: `{"status":"ok","schema_version":1}`
Stop the server with Ctrl+C.

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/web/app.py tests/test_web_health.py
git commit -m "feat(web): FastAPI app with /health and migration-on-startup"
```

---

## Task 9: Full test suite + smoke check

**Files:** none

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (settings: 2, store: 6, llm: 6, web: 1 — 15 total).

- [ ] **Step 2: Run ruff**

Run: `uv run ruff check src tests`
Expected: no errors. If any, fix and re-run.

- [ ] **Step 3: Verify the app starts cleanly**

Run: `uv run uvicorn auto_reply.web.app:app --port 8000`
Expected: server logs `Uvicorn running on http://127.0.0.1:8000`. Stop with Ctrl+C.

- [ ] **Step 4: Commit any fix-ups**

```bash
git add -A
git status   # should be clean if no fixes needed
git commit -m "chore: phase 0 green — all tests + lint pass" --allow-empty
```

---

## Self-review notes

- **Spec coverage:** Phase 0 only requires scaffold + cost wrapper + DB. All
  spec §6 tables are created in Task 5. The cost wrapper (spec §9) lands in
  Task 7. Settings (§10) lands in Task 3. No business pipeline code yet —
  that is Phase 1 onward.
- **Placeholder scan:** no TBDs, no "add validation later", every code step
  shows the full code.
- **Type consistency:** `LLMClient.complete()` signature in Task 7 matches the
  way Phase 1 will call it (kwargs-only after `*`, named `purpose`,
  optional `draft_id`).
- **Open Anthropic-pricing risk:** the numbers in `pricing.py` are placeholders
  that match the model tier defaults from the spec. Verify against the
  current Anthropic price sheet before Phase 5 (Auto-send).
