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
