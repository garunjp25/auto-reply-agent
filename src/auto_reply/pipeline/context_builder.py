from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from auto_reply.llm.client import LLMClient
    from auto_reply.sources.lumenx import LumenXClient

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

_SUMMARY_PROMPT = (
    "Summarise the following prior support thread(s) from this customer in ONE short paragraph "
    "(3–5 sentences). Focus on: what products they asked about, any issues resolved, and any "
    "open items. Be factual — do not invent details.\n\n"
)

_PRIOR_THREAD_MODEL = "claude-haiku-4-5-20251001"
_MAX_PRIOR_MESSAGES = 50  # cost guard


@dataclass(frozen=True)
class DraftContext:
    system_blocks: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    snapshot_json: str


class ContextBuilder:
    """Assemble the Drafter prompt.

    Phase 3 addition: optional `llm` + `lumenx` enable per-customer cross-thread
    summary. Pass both to activate; omit either to skip (safe default).
    """

    def __init__(
        self,
        wiki_text: str,
        *,
        llm: LLMClient | None = None,
        lumenx: LumenXClient | None = None,
    ) -> None:
        self._wiki_text = wiki_text
        self._llm = llm
        self._lumenx = lumenx

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

        # Cross-thread summary (Phase 3 — only when llm + lumenx provided)
        current_thread_id = thread.get("thread", {}).get("id")
        username = thread.get("thread", {}).get("username")
        prior_summary = self._get_prior_summary(username, current_thread_id)
        if prior_summary:
            system_blocks.append({
                "type": "text",
                "text": f"# Prior context for customer '{username}'\n\n{prior_summary}",
            })

        snapshot = {
            "intent": intent,
            "thread_id": current_thread_id,
            "username": username,
            "system_blocks": system_blocks,
            "messages": api_messages,
        }

        return DraftContext(
            system_blocks=system_blocks,
            messages=api_messages,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        )

    def _get_prior_summary(
        self, username: str | None, current_thread_id: str | None
    ) -> str | None:
        """Fetch prior threads for username and summarise with Haiku. Returns None on any failure."""
        if not username or not self._llm or not self._lumenx:
            return None
        try:
            all_threads = self._lumenx.get_threads().get("threads", [])
        except Exception:
            return None

        prior = [
            t for t in all_threads
            if t.get("username") == username
            and t.get("id") != current_thread_id
            and t.get("messages")
        ]
        if not prior:
            return None

        # Cost guard: total messages across prior threads
        total_msgs = sum(len(t.get("messages", [])) for t in prior)
        if total_msgs > _MAX_PRIOR_MESSAGES:
            prior = prior[:3]  # cap to 3 most recent threads

        thread_text = ""
        for t in prior:
            thread_text += f"\n--- Thread {t.get('id')} ---\n"
            for m in t.get("messages", []):
                role = m.get("role", "?")
                thread_text += f"{role}: {m.get('text', '')}\n"

        try:
            return self._llm.complete(
                model=_PRIOR_THREAD_MODEL,
                system=_SUMMARY_PROMPT,
                messages=[{"role": "user", "content": thread_text}],
                purpose="prior_summary",
                max_tokens=200,
                temperature=0.0,
            )
        except Exception:
            return None
