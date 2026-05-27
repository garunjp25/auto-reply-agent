import json
from pathlib import Path

from auto_reply.pipeline.intent_router import INTENTS

FIXTURE = Path(__file__).parent / "fixtures" / "intent_eval.jsonl"


def test_fixture_exists():
    assert FIXTURE.exists(), "Run scripts/build_intent_eval.py to generate it."


def test_fixture_has_33_entries():
    lines = [ln for ln in FIXTURE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 33


def test_every_entry_has_valid_intent_and_nonempty_message():
    seen_intents = set()
    for ln in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        obj = json.loads(ln)
        assert "message" in obj and obj["message"].strip()
        assert obj.get("intent") in INTENTS, f"Bad intent: {obj.get('intent')!r}"
        seen_intents.add(obj["intent"])
    assert len(seen_intents) >= 3
