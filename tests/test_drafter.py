from unittest.mock import MagicMock

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.context_builder import DraftContext
from auto_reply.pipeline.drafter import Drafter


def _ctx() -> DraftContext:
    return DraftContext(
        system_blocks=[
            {"type": "text", "text": "PERSONA"},
            {"type": "text", "text": "WIKI", "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": "How much is Pro?"}],
        snapshot_json='{"x": 1}',
    )


def _make_llm(db, text: str = "Sure — the Pro plan is $25/month.") -> LLMClient:
    sdk = MagicMock()
    resp = MagicMock()
    resp.id = "msg_draft"
    resp.usage.input_tokens = 1000
    resp.usage.output_tokens = 40
    resp.usage.cache_read_input_tokens = 0
    resp.usage.cache_creation_input_tokens = 800
    resp.content = [MagicMock(text=text)]
    sdk.messages.create.return_value = resp
    return LLMClient(sdk=sdk, conn=db)


def test_drafter_returns_text(db):
    llm = _make_llm(db)
    drafter = Drafter(llm=llm)
    text = drafter.draft(_ctx())
    assert "Pro plan is $25" in text


def test_drafter_passes_system_blocks_to_llm(db):
    llm = _make_llm(db)
    drafter = Drafter(llm=llm)
    drafter.draft(_ctx())
    call = llm.sdk.messages.create.call_args
    kwargs = call.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert isinstance(kwargs["system"], list)
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}


def test_drafter_writes_cost_row_with_purpose_draft(db):
    llm = _make_llm(db)
    drafter = Drafter(llm=llm)
    drafter.draft(_ctx())
    rows = db.execute(
        "SELECT purpose, model, cache_write_tokens FROM cost_log"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["purpose"] == "draft"
    assert rows[0]["model"] == "claude-sonnet-4-6"
    assert rows[0]["cache_write_tokens"] == 800
