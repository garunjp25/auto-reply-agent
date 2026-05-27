from unittest.mock import MagicMock

import pytest

from auto_reply.llm.client import LLMClient
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
