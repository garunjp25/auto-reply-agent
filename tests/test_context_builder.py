import json

import pytest

from auto_reply.pipeline.context_builder import ContextBuilder, DraftContext


def _thread(thread_id: str = "t1") -> dict:
    return {
        "thread": {"id": thread_id, "username": "alice"},
        "messages": [
            {"role": "customer", "text": "Hi, I have a question"},
            {"role": "admin", "text": "Sure, what's up?"},
            {"role": "customer", "text": "How much is the Pro plan?"},
        ],
    }


def test_returns_draft_context_with_system_messages_and_snapshot():
    builder = ContextBuilder(wiki_text="WIKI BODY HERE")
    ctx = builder.build(thread=_thread(), intent="pricing")

    assert isinstance(ctx, DraftContext)
    assert len(ctx.system_blocks) == 2
    assert ctx.system_blocks[0]["type"] == "text"
    assert ctx.system_blocks[1]["type"] == "text"
    assert ctx.system_blocks[1].get("cache_control") == {"type": "ephemeral"}
    assert "WIKI BODY HERE" in ctx.system_blocks[1]["text"]
    assert isinstance(ctx.messages, list)
    assert ctx.messages[-1]["role"] == "user"
    assert "How much is the Pro plan" in ctx.messages[-1]["content"]
    s = json.loads(ctx.snapshot_json)
    assert s["intent"] == "pricing"
    assert s["thread_id"] == "t1"


def test_system_persona_block_mentions_anti_hallucination():
    builder = ContextBuilder(wiki_text="x")
    ctx = builder.build(thread=_thread(), intent="technical")
    persona = ctx.system_blocks[0]["text"].lower()
    assert "don't" in persona or "do not" in persona
    assert "i don't have" in persona or "i do not have" in persona


def test_thread_transcript_is_in_order():
    builder = ContextBuilder(wiki_text="x")
    ctx = builder.build(thread=_thread(), intent="technical")
    roles = [m["role"] for m in ctx.messages]
    assert roles[0] == "user"
    assert roles[-1] == "user"
    assert "system" not in roles


def test_empty_thread_messages_raises():
    builder = ContextBuilder(wiki_text="x")
    with pytest.raises(ValueError):
        builder.build(thread={"thread": {"id": "t"}, "messages": []}, intent="technical")
