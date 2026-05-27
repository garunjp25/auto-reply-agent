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
