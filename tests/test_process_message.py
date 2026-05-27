from unittest.mock import MagicMock

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.context_builder import ContextBuilder
from auto_reply.pipeline.drafter import Drafter
from auto_reply.pipeline.intent_router import IntentRouter
from auto_reply.pipeline.process_message import process_message


def _llm_with_responses(db, *texts: str) -> LLMClient:
    sdk = MagicMock()
    responses = []
    for t in texts:
        r = MagicMock()
        r.id = f"msg_{len(responses)}"
        r.usage.input_tokens = 50
        r.usage.output_tokens = 10
        r.usage.cache_read_input_tokens = 0
        r.usage.cache_creation_input_tokens = 0
        r.content = [MagicMock(text=t)]
        responses.append(r)
    sdk.messages.create.side_effect = responses
    return LLMClient(sdk=sdk, conn=db)


def _thread(text: str) -> dict:
    return {
        "thread": {"id": "t1", "username": "alice"},
        "messages": [{"role": "customer", "text": text}],
    }


def test_pricing_message_runs_full_pipeline(db):
    llm = _llm_with_responses(
        db,
        '{"intent": "pricing"}',
        "The Pro plan is $25/month.",
    )
    intent_router = IntentRouter(llm=llm)
    drafter = Drafter(llm=llm)
    ctx_builder = ContextBuilder(wiki_text="WIKI")

    draft_id = process_message(
        thread=_thread("How much is Pro?"),
        conn=db,
        intent_router=intent_router,
        context_builder=ctx_builder,
        drafter=drafter,
    )

    row = db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row is not None
    assert row["intent"] == "pricing"
    assert row["sensitive"] == 1
    assert row["status"] == "pending"
    assert row["auto_sent"] == 0
    assert "$25" in row["draft_text"]
    assert row["customer_msg"] == "How much is Pro?"
    assert row["thread_id"] == "t1"


def test_greeting_short_circuits_no_draft_call(db):
    llm = _llm_with_responses(db, '{"intent": "greeting"}')
    intent_router = IntentRouter(llm=llm)
    drafter = Drafter(llm=llm)
    ctx_builder = ContextBuilder(wiki_text="WIKI")

    draft_id = process_message(
        thread=_thread("hi there"),
        conn=db,
        intent_router=intent_router,
        context_builder=ctx_builder,
        drafter=drafter,
    )

    row = db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row["intent"] == "greeting"
    assert row["sensitive"] == 0
    assert row["draft_text"].startswith("Hi!")
    assert llm.sdk.messages.create.call_count == 1


def test_nested_thread_shape_from_real_lumenx_api(db):
    """Real /api/admin/threads/{id} returns {thread: {..., messages: [...]}}."""
    llm = _llm_with_responses(
        db,
        '{"intent": "pricing"}',
        "The Pro plan is $25/month.",
    )
    intent_router = IntentRouter(llm=llm)
    drafter = Drafter(llm=llm)
    ctx_builder = ContextBuilder(wiki_text="WIKI")

    nested_thread = {
        "thread": {
            "id": "live-abc",
            "customer_username": "alice",
            "messages": [
                {"role": "customer", "text": "How much is Pro?"},
            ],
        }
    }
    draft_id = process_message(
        thread=nested_thread,
        conn=db,
        intent_router=intent_router,
        context_builder=ctx_builder,
        drafter=drafter,
    )
    row = db.execute("SELECT thread_id, customer_msg FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row["thread_id"] == "live-abc"
    assert "How much is Pro?" in row["customer_msg"]


def test_cancellation_marks_sensitive(db):
    llm = _llm_with_responses(
        db,
        '{"intent": "cancellation"}',
        "I'm sorry to hear that. I'll connect you with the team.",
    )
    intent_router = IntentRouter(llm=llm)
    drafter = Drafter(llm=llm)
    ctx_builder = ContextBuilder(wiki_text="WIKI")

    draft_id = process_message(
        thread=_thread("I want to cancel my subscription"),
        conn=db,
        intent_router=intent_router,
        context_builder=ctx_builder,
        drafter=drafter,
    )
    row = db.execute("SELECT sensitive, intent FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    assert row["sensitive"] == 1
    assert row["intent"] == "cancellation"
