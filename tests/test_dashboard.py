from fastapi import FastAPI
from fastapi.testclient import TestClient

from auto_reply.web.dashboard import make_router


def _app(db, password: str = "pw") -> FastAPI:
    app = FastAPI()
    router = make_router(conn=db, password=password)
    app.include_router(router)
    return app


def _seed_drafts(db) -> None:
    db.execute(
        "INSERT INTO drafts (thread_id, customer_msg, draft_text, intent, sensitive, "
        "status, auto_sent, created_at) VALUES "
        "('t1', 'How much is Pro?', 'It is $25', 'pricing', 1, 'pending', 0, '2026-05-27T10:00:00+00:00'),"
        "('t2', 'hi there',          'Hi!',       'greeting',0, 'pending', 0, '2026-05-27T10:00:01+00:00'),"
        "('t3', 'old one',           'whatever',  'technical',0,'sent',    0, '2026-05-27T09:00:00+00:00')"
    )


def test_queue_requires_auth(db):
    _seed_drafts(db)
    client = TestClient(_app(db))
    r = client.get("/agent/queue")
    assert r.status_code == 401


def test_queue_rejects_wrong_password(db):
    client = TestClient(_app(db, password="correct"))
    r = client.get("/agent/queue", auth=("admin", "wrong"))
    assert r.status_code == 401


def test_queue_shows_only_pending_drafts(db):
    _seed_drafts(db)
    client = TestClient(_app(db, password="pw"))
    r = client.get("/agent/queue", auth=("admin", "pw"))
    assert r.status_code == 200
    body = r.text
    assert "How much is Pro?" in body
    assert "hi there" in body
    assert "old one" not in body


def test_queue_shows_intent_and_sensitive_flag(db):
    _seed_drafts(db)
    client = TestClient(_app(db, password="pw"))
    r = client.get("/agent/queue", auth=("admin", "pw"))
    body = r.text
    assert "pricing" in body
    assert "sensitive" in body.lower()
