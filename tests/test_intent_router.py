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
        "greeting", "pricing", "refund", "technical",
        "feature_question", "integration", "other",
    }
    assert SENSITIVE_INTENTS == {"pricing", "refund"}


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


def test_sensitive_flag_set_for_refund(db):
    llm = _make_llm(db, "refund")
    router = IntentRouter(llm=llm)
    result = router.classify("I want my money back")
    assert result.intent == "refund"
    assert result.sensitive is True


def test_unknown_label_falls_back_to_other(db):
    llm = _make_llm(db, "completely_made_up")
    router = IntentRouter(llm=llm)
    result = router.classify("???")
    assert result.intent == "other"
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


def test_malformed_json_falls_back_to_other(db):
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
    assert result.intent == "other"
    assert result.sensitive is False
