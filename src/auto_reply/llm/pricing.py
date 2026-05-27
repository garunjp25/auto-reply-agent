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
