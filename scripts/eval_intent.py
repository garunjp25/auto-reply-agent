"""Run the IntentRouter on the eval fixture and print accuracy.

Costs real Anthropic credit (~$0.01 with Haiku).

    uv run python scripts/eval_intent.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from anthropic import Anthropic

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.intent_router import IntentRouter
from auto_reply.settings import get_settings
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations
from auto_reply.tls import enable_system_certs

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "intent_eval.jsonl"
ACCEPTANCE_THRESHOLD = 0.80


def main() -> None:
    enable_system_certs()
    settings = get_settings()
    conn = connect(settings.agent_db_path)
    apply_migrations(conn)
    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)
    router = IntentRouter(llm=llm)

    correct = 0
    total = 0
    confusion: dict[str, Counter] = defaultdict(Counter)
    mistakes: list[tuple[str, str, str]] = []

    with FIXTURE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            gold = obj["intent"]
            pred = router.classify(obj["message"]).intent
            total += 1
            confusion[gold][pred] += 1
            if pred == gold:
                correct += 1
            else:
                mistakes.append((gold, pred, obj["message"][:80]))

    acc = correct / total if total else 0.0
    print(f"\nAccuracy: {correct}/{total} = {acc:.1%}\n")
    print("Confusion (gold -> predicted):")
    for gold, preds in confusion.items():
        print(f"  {gold:18s} {dict(preds)}")
    if mistakes:
        print(f"\nMistakes ({len(mistakes)}):")
        for gold, pred, msg in mistakes:
            print(f"  gold={gold:14s} pred={pred:14s} {msg!r}")

    print(f"\nAcceptance threshold: {ACCEPTANCE_THRESHOLD:.0%}")
    print("PASS" if acc >= ACCEPTANCE_THRESHOLD else "FAIL")


if __name__ == "__main__":
    main()
