from auto_reply.pipeline.templates import (
    GREETING_REPLY,
    OTHER_REPLY,
    short_circuit_reply,
)


def test_greeting_template_is_friendly_and_short():
    assert isinstance(GREETING_REPLY, str)
    assert 10 <= len(GREETING_REPLY) <= 400


def test_other_template_is_a_polite_handoff():
    assert "team" in OTHER_REPLY.lower() or "help" in OTHER_REPLY.lower()


def test_short_circuit_reply_for_greeting():
    assert short_circuit_reply("greeting") == GREETING_REPLY


def test_short_circuit_reply_for_other():
    assert short_circuit_reply("other") == OTHER_REPLY


def test_short_circuit_reply_for_non_short_circuit_returns_none():
    assert short_circuit_reply("pricing") is None
    assert short_circuit_reply("technical") is None
    assert short_circuit_reply("integration") is None
