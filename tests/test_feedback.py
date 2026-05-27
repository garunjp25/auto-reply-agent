"""Tests for store/feedback.py — approve/edit/reject actions."""
from __future__ import annotations

import pytest

from auto_reply.store.feedback import record_feedback_with_label


def _insert_draft(db) -> int:
    from datetime import datetime, timezone
    cur = db.execute(
        """
        INSERT INTO drafts
            (thread_id, customer_msg, draft_text, intent, sensitive, status, created_at)
        VALUES ('t1', 'hi', 'Hello!', 'greeting', 0, 'pending', ?)
        """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    db.commit()
    return cur.lastrowid


def test_approve_writes_feedback_and_label(db):
    draft_id = _insert_draft(db)
    record_feedback_with_label(db, draft_id, "approve")

    row = db.execute("SELECT action, thumb FROM feedback WHERE draft_id=?", (draft_id,)).fetchone()
    assert row["action"] == "approve"
    assert row["thumb"] == 1

    label = db.execute("SELECT label_float FROM training_labels WHERE draft_id=?", (draft_id,)).fetchone()
    assert label["label_float"] == 1.0

    status = db.execute("SELECT status FROM drafts WHERE id=?", (draft_id,)).fetchone()
    assert status["status"] == "approved"


def test_reject_writes_feedback_and_label(db):
    draft_id = _insert_draft(db)
    record_feedback_with_label(db, draft_id, "reject")

    row = db.execute("SELECT action, thumb FROM feedback WHERE draft_id=?", (draft_id,)).fetchone()
    assert row["action"] == "reject"
    assert row["thumb"] == 0

    label = db.execute("SELECT label_float FROM training_labels WHERE draft_id=?", (draft_id,)).fetchone()
    assert label["label_float"] == 0.0

    status = db.execute("SELECT status FROM drafts WHERE id=?", (draft_id,)).fetchone()
    assert status["status"] == "rejected"


def test_edit_stores_edited_reply(db):
    draft_id = _insert_draft(db)
    record_feedback_with_label(db, draft_id, "edit", edited_reply="Better reply text.")

    row = db.execute("SELECT action, edited_reply, thumb FROM feedback WHERE draft_id=?", (draft_id,)).fetchone()
    assert row["action"] == "edit"
    assert row["edited_reply"] == "Better reply text."
    assert row["thumb"] == 1

    label = db.execute("SELECT label_float FROM training_labels WHERE draft_id=?", (draft_id,)).fetchone()
    assert label["label_float"] == 0.5

    status = db.execute("SELECT status FROM drafts WHERE id=?", (draft_id,)).fetchone()
    assert status["status"] == "edited"


def test_invalid_action_raises(db):
    draft_id = _insert_draft(db)
    with pytest.raises(ValueError, match="Unknown action"):
        record_feedback_with_label(db, draft_id, "maybe")
