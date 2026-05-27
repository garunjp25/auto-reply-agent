from unittest.mock import MagicMock

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.intent_router import (
    INTENTS,
    SENSITIVE_INTENTS,
    IntentResult,
    IntentRouter,
)


def _make_llm(db, label: str) -> LLMClient:
    sdk = MagicMock()
    resp = MagicMock()
    resp.id = "msg_intent_test"
    resp.usage.input_tokens = 30
    resp.usage.output_tokens = 5
    resp.usage.cache_read_input_tokens = 0
    resp.usage.cache_creation_input_tokens = 0
    resp.content = [MagicMock(text=f'{{"intent": "{label}"}}')]
    sdk.messages.create.return_value = resp
    return LLMClient(sdk=sdk, conn=db)


def test_intents_constant_matches_spec():
    assert set(INTENTS) == {
        "greeting", "pricing", "discount", "billing",
        "features", "technical", "integration",
        "multi_product", "cancellation",
        "competitor_comparison", "conversational",
    }
    assert SENSITIVE_INTENTS == {
        "pricing", "discount", "billing", "cancellation", "competitor_comparison"
    }


def test_classify_returns_intent_result(db):
    llm = _make_llm(db, "technical")
    router = IntentRouter(llm=llm)
    result = router.classify("My integration with Slack broke yesterday")
    assert isinstance(result, IntentResult)
    assert result.intent == "technical"
    assert result.sensitive is False


def test_sensitive_flag_set_for_pricing(db):
    llm = _make_llm(db, "pricing")
    router = IntentRouter(llm=llm)
    result = router.classify("How much is the Pro plan?")
    assert result.intent == "pricing"
    assert result.sensitive is True


def test_sensitive_flag_set_for_cancellation(db):
    llm = _make_llm(db, "cancellation")
    router = IntentRouter(llm=llm)
    result = router.classify("I want to cancel my subscription")
    assert result.intent == "cancellation"
    assert result.sensitive is True


def test_sensitive_flag_set_for_discount(db):
    llm = _make_llm(db, "discount")
    router = IntentRouter(llm=llm)
    result = router.classify("Any non-profit discounts available?")
    assert result.intent == "discount"
    assert result.sensitive is True


def test_sensitive_flag_set_for_competitor_comparison(db):
    llm = _make_llm(db, "competitor_comparison")
    router = IntentRouter(llm=llm)
    result = router.classify("How do you compare to Intercom?")
    assert result.intent == "competitor_comparison"
    assert result.sensitive is True


def test_multi_product_pre_check_bypasses_llm(db):
    """Two LumenX product names → multi_product without LLM call."""
    llm = _make_llm(db, "integration")  # LLM would say integration — pre-check wins
    router = IntentRouter(llm=llm)
    result = router.classify("How do EmailPilot and PollWise work together?")
    assert result.intent == "multi_product"
    assert result.sensitive is False
    # LLM must NOT have been called
    llm.sdk.messages.create.assert_not_called()


def test_single_product_integration_reaches_llm(db):
    """One LumenX product + external tool → LLM decides → integration."""
    llm = _make_llm(db, "integration")
    router = IntentRouter(llm=llm)
    result = router.classify("Can NoteHub connect to Obsidian?")
    assert result.intent == "integration"
    assert result.sensitive is False


def test_unknown_label_falls_back_to_conversational(db):
    llm = _make_llm(db, "completely_made_up")
    router = IntentRouter(llm=llm)
    result = router.classify("???")
    assert result.intent == "conversational"
    assert result.sensitive is False


def test_classify_writes_cost_row(db):
    llm = _make_llm(db, "greeting")
    router = IntentRouter(llm=llm)
    router.classify("hi there")
    rows = db.execute(
        "SELECT purpose, model FROM cost_log WHERE purpose='intent'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["model"] == "claude-haiku-4-5-20251001"


def test_malformed_json_falls_back_to_conversational(db):
    sdk = MagicMock()
    resp = MagicMock()
    resp.id = "msg_bad"
    resp.usage.input_tokens = 5
    resp.usage.output_tokens = 5
    resp.usage.cache_read_input_tokens = 0
    resp.usage.cache_creation_input_tokens = 0
    resp.content = [MagicMock(text="not json at all")]
    sdk.messages.create.return_value = resp
    llm = LLMClient(sdk=sdk, conn=db)

    router = IntentRouter(llm=llm)
    result = router.classify("anything")
    assert result.intent == "conversational"
    assert result.sensitive is False
