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
    snapshot_json: str


class ContextBuilder:
    """Assemble the Drafter prompt.

    Phase 2 scope: persona + full wiki (cache_control=ephemeral on the wiki
    block) as system; current-thread transcript as messages.
    """

    def __init__(self, wiki_text: str) -> None:
        self._wiki_text = wiki_text

    def build(self, *, thread: dict[str, Any], intent: str) -> DraftContext:
        # Real LumenX nests messages inside `thread`; some test fixtures put them at root.
        messages = thread.get("thread", {}).get("messages") or thread.get("messages") or []
        if not messages:
            raise ValueError("thread has no messages")

        api_messages: list[dict[str, Any]] = []
        for m in messages:
            role = "user" if m.get("role") == "customer" else "assistant"
            api_messages.append({"role": role, "content": str(m.get("text", ""))})

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
