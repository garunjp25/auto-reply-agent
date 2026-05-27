from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass

from auto_reply.llm.client import LLMClient

# ---------------------------------------------------------------------------
# Intent taxonomy (11 intents)
# ---------------------------------------------------------------------------
INTENTS: tuple[str, ...] = (
    "greeting",
    "pricing",
    "discount",
    "billing",
    "features",
    "technical",
    "integration",
    "multi_product",
    "cancellation",
    "competitor_comparison",
    "conversational",
)

SENSITIVE_INTENTS: frozenset[str] = frozenset({
    "pricing",
    "discount",
    "billing",
    "cancellation",
    "competitor_comparison",
})

INTENT_MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# LumenX product name set — auto-loaded from wiki/ filenames at import time.
# Falls back to a hardcoded set if wiki/ doesn't exist yet (e.g. CI without
# generated artefacts).
# ---------------------------------------------------------------------------
def _load_product_names() -> frozenset[str]:
    wiki_dir = pathlib.Path(__file__).resolve().parents[3] / "wiki"
    if wiki_dir.is_dir():
        return frozenset(
            p.stem.lower().replace("-", "").replace("_", "")
            for p in wiki_dir.glob("*.md")
            if p.stem.lower() != "index"
        )
    # Hardcoded fallback
    return frozenset({
        "emailpilot", "pollwise", "chatrelay", "invoiceflow",
        "notehub", "inboxclean", "pixeldeck", "documerge",
        "calendarsync", "payce",
    })


LUMENX_PRODUCTS: frozenset[str] = _load_product_names()

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You classify a single customer-support message into ONE intent.

Valid intents (read definitions carefully — they are mutually exclusive):

- greeting           — pure social with NO product question ("hi", "thanks", "see you").
- pricing            — asking what a product costs, which plan/tier to choose.
- discount           — asking for a deal, coupon, non-profit rate, or volume break.
- billing            — invoice PDF, payment history, billing details, charge on statement.
- features           — "does X support Y?", "how do I do Z?", capability or how-to question.
- technical          — bug reports, errors, broken behaviour, performance issues.
- integration        — connecting a LumenX product to an EXTERNAL third-party tool
                       (Slack, Zapier, Stripe, QuickBooks, Obsidian, etc.).
- multi_product      — two or more LumenX products mentioned together (bundle, comparison,
                       or compatibility between LumenX products). Takes priority over
                       features and integration when multiple internal products appear.
- cancellation       — ending or pausing a subscription or account.
- competitor_comparison — mentions a rival/external product and asks why to choose LumenX
                          over it, or compares LumenX unfavourably.
- conversational     — unclear, vague, or does not fit any category above.

Reply with ONLY a single JSON object: {"intent": "<one of the above>"}.
No prose, no markdown fences, no explanation.
"""

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntentResult:
    intent: str
    sensitive: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_product_mentions(message: str) -> int:
    """Count distinct LumenX product names in message (case-insensitive)."""
    lower = message.lower().replace("-", "").replace("_", "").replace(" ", "")
    return sum(1 for p in LUMENX_PRODUCTS if p in lower)


def _parse_intent(text: str) -> str:
    try:
        data = json.loads(text.strip())
        candidate = str(data.get("intent", "")).strip().lower()
        if candidate in INTENTS:
            return candidate
    except (json.JSONDecodeError, AttributeError):
        pass
    for intent in INTENTS:
        if re.search(rf"\b{re.escape(intent)}\b", text, re.IGNORECASE):
            return intent
    return "conversational"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class IntentRouter:
    """Classify a single customer message into one of the 11 canonical intents."""

    def __init__(self, *, llm: LLMClient, model: str = INTENT_MODEL) -> None:
        self._llm = llm
        self._model = model

    def classify(self, customer_message: str) -> IntentResult:
        # Deterministic pre-check: 2+ LumenX products → multi_product
        if _count_product_mentions(customer_message) >= 2:
            return IntentResult(intent="multi_product", sensitive=False)

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
