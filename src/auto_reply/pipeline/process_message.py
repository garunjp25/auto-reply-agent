from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from auto_reply.pipeline.context_builder import ContextBuilder
from auto_reply.pipeline.drafter import Drafter
from auto_reply.pipeline.intent_router import IntentRouter
from auto_reply.pipeline.templates import short_circuit_reply
from auto_reply.store.db import transaction


def process_message(
    *,
    thread: dict[str, Any],
    conn: sqlite3.Connection,
    intent_router: IntentRouter,
    context_builder: ContextBuilder,
    drafter: Drafter,
) -> int:
    """Run the pipeline for one thread and write one row to `drafts`."""
    messages = thread.get("messages", [])
    customer_msgs = [m for m in messages if m.get("role") == "customer"]
    if not customer_msgs:
        raise ValueError("thread has no customer messages")
    latest_customer = customer_msgs[-1]
    customer_text = str(latest_customer.get("text", ""))

    intent_result = intent_router.classify(customer_text)
    intent = intent_result.intent
    sensitive = intent_result.sensitive

    short = short_circuit_reply(intent)
    if short is not None:
        draft_text = short
        context_json = json.dumps(
            {
                "intent": intent,
                "thread_id": thread.get("thread", {}).get("id"),
                "short_circuit": True,
            },
            ensure_ascii=False,
        )
    else:
        ctx = context_builder.build(thread=thread, intent=intent)
        draft_text = drafter.draft(ctx)
        context_json = ctx.snapshot_json

    with transaction(conn):
        cursor = conn.execute(
            """
            INSERT INTO drafts
              (thread_id, customer_msg, draft_text, intent, sensitive,
               confidence, context_json, status, auto_sent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)
            """,
            (
                thread.get("thread", {}).get("id"),
                customer_text,
                draft_text,
                intent,
                1 if sensitive else 0,
                None,
                context_json,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        draft_id = cursor.lastrowid

    assert draft_id is not None
    return draft_id
