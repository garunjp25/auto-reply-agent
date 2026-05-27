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
