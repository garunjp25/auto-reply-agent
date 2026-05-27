"""Tests for Phase 3 dashboard routes: feedback actions, activity tab, costs tab."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auto_reply.web.dashboard import make_router


def _app(db, password: str = "pw") -> FastAPI:
    app = FastAPI()
    app.include_router(make_router(conn=db, password=password))
    return app


def _seed(db) -> int:
    """Insert one pending draft, return its id."""
    cur = db.execute(
        "INSERT INTO drafts (thread_id, customer_msg, draft_text, intent, sensitive, "
        "status, auto_sent, created_at) VALUES "
        "('t1', 'How much is Pro?', 'It is $25/mo.', 'pricing', 1, 'pending', 0, '2026-05-27T10:00:00+00:00')"
    )
    db.commit()
    return cur.lastrowid


def _seed_cost(db) -> None:
    db.execute(
        "INSERT INTO cost_log (call_id, model, input_tokens, output_tokens, "
        "cache_read_tokens, cache_write_tokens, cost_usd, purpose, at) VALUES "
        "('c1','claude-haiku-4-5-20251001',100,20,0,0,0.000150,'intent','2026-05-27T10:00:00+00:00'),"
        "('c2','claude-sonnet-4-6',400,80,0,0,0.003200,'draft','2026-05-27T10:01:00+00:00')"
    )
    db.commit()


# ------------------------------------------------------------------
# Approve / Reject / Edit
# ------------------------------------------------------------------

def test_approve_updates_status(db):
    draft_id = _seed(db)
    client = TestClient(_app(db))
    r = client.post(f"/agent/drafts/{draft_id}/approve", auth=("admin", "pw"))
    assert r.status_code == 200
    row = db.execute("SELECT status FROM drafts WHERE id=?", (draft_id,)).fetchone()
    assert row["status"] == "approved"


def test_approve_writes_feedback_row(db):
    draft_id = _seed(db)
    client = TestClient(_app(db))
    client.post(f"/agent/drafts/{draft_id}/approve", auth=("admin", "pw"))
    fb = db.execute("SELECT action FROM feedback WHERE draft_id=?", (draft_id,)).fetchone()
    assert fb["action"] == "approve"


def test_reject_updates_status(db):
    draft_id = _seed(db)
    client = TestClient(_app(db))
    r = client.post(f"/agent/drafts/{draft_id}/reject", auth=("admin", "pw"))
    assert r.status_code == 200
    row = db.execute("SELECT status FROM drafts WHERE id=?", (draft_id,)).fetchone()
    assert row["status"] == "rejected"


def test_edit_stores_edited_reply(db):
    draft_id = _seed(db)
    client = TestClient(_app(db))
    r = client.post(
        f"/agent/drafts/{draft_id}/edit",
        data={"reply": "Updated reply text."},
        auth=("admin", "pw"),
    )
    assert r.status_code == 200
    fb = db.execute("SELECT action, edited_reply FROM feedback WHERE draft_id=?", (draft_id,)).fetchone()
    assert fb["action"] == "edit"
    assert fb["edited_reply"] == "Updated reply text."


def test_double_action_returns_409(db):
    draft_id = _seed(db)
    client = TestClient(_app(db))
    client.post(f"/agent/drafts/{draft_id}/approve", auth=("admin", "pw"))
    r = client.post(f"/agent/drafts/{draft_id}/reject", auth=("admin", "pw"))
    assert r.status_code == 409


def test_action_on_missing_draft_returns_404(db):
    client = TestClient(_app(db))
    r = client.post("/agent/drafts/9999/approve", auth=("admin", "pw"))
    assert r.status_code == 404


# ------------------------------------------------------------------
# Activity tab
# ------------------------------------------------------------------

def test_activity_returns_200(db):
    _seed(db)
    client = TestClient(_app(db))
    r = client.get("/agent/activity", auth=("admin", "pw"))
    assert r.status_code == 200


def test_activity_shows_intent(db):
    _seed(db)
    client = TestClient(_app(db))
    r = client.get("/agent/activity", auth=("admin", "pw"))
    assert "pricing" in r.text


# ------------------------------------------------------------------
# Costs tab
# ------------------------------------------------------------------

def test_costs_returns_200(db):
    _seed_cost(db)
    client = TestClient(_app(db))
    r = client.get("/agent/costs", auth=("admin", "pw"))
    assert r.status_code == 200


def test_costs_shows_total(db):
    _seed_cost(db)
    client = TestClient(_app(db))
    r = client.get("/agent/costs", auth=("admin", "pw"))
    assert "total spend" in r.text.lower()
    assert "0.003" in r.text  # cost_usd from seeded data
