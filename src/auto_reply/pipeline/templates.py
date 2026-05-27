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
    return _TABLE.get(intent)
