"""Build the IntentRouter eval set.

Reads tests/fixtures/lumenx_export.json (refresh with scripts/refresh_fixtures.py).
Samples 30 diverse customer messages and labels them with Opus.
Writes tests/fixtures/intent_eval.jsonl — one {"message": ..., "intent": ...} per line.

Run once, then hand-review the output.

    uv run python scripts/build_intent_eval.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from anthropic import Anthropic

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.intent_router import INTENTS, SYSTEM_PROMPT, _parse_intent
from auto_reply.settings import get_settings
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations
from auto_reply.tls import enable_system_certs

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
EXPORT_PATH = FIXTURE_DIR / "lumenx_export.json"
OUT_PATH = FIXTURE_DIR / "intent_eval.jsonl"

N = 30
LABELLER_MODEL = "claude-opus-4-7"


def collect_customer_messages(export: dict) -> list[str]:
    out: list[str] = []
    for thread in export.get("threads", []):
        for msg in thread.get("messages", []):
            if msg.get("role") == "customer":
                text = (msg.get("text") or "").strip()
                if 4 <= len(text) <= 600:
                    out.append(text)
    return out


def main() -> None:
    enable_system_certs()
    settings = get_settings()
    if not EXPORT_PATH.exists():
        raise SystemExit(
            f"{EXPORT_PATH} not found. Run `uv run python scripts/refresh_fixtures.py` first."
        )
    export = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    messages = collect_customer_messages(export)
    if len(messages) < N:
        raise SystemExit(f"Only {len(messages)} candidates — need >= {N}.")

    random.seed(20260527)
    sample = random.sample(messages, N)

    conn = connect(settings.agent_db_path)
    apply_migrations(conn)
    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for i, msg in enumerate(sample, start=1):
            raw = llm.complete(
                model=LABELLER_MODEL,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": msg}],
                purpose="intent_eval_label",
                max_tokens=64,
                temperature=0.0,
            )
            intent = _parse_intent(raw)
            if intent not in INTENTS:
                intent = "other"
            fh.write(json.dumps({"message": msg, "intent": intent}, ensure_ascii=False) + "\n")
            print(f"[{i}/{N}] {intent:18s} {msg[:60]!r}")

    print(f"\nWrote {OUT_PATH}")
    print("Hand-review the labels and edit any that are wrong.")


if __name__ == "__main__":
    main()
