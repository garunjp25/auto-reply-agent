import asyncio
from unittest.mock import MagicMock

import pytest

from auto_reply.sources.poller import Poller


def _inbox_payload(server_time: str, entries: list[dict]) -> dict:
    return {"server_time": server_time, "awaiting_count": len(entries), "entries": entries}


@pytest.mark.asyncio
async def test_poller_processes_each_awaiting_entry_once(db):
    inbox_calls = [
        _inbox_payload("2026-05-27T10:00:00Z", [
            {"thread": {"id": "t1"}, "last_customer_message": {"id": "m1"}, "awaiting_admin": True},
            {"thread": {"id": "t2"}, "last_customer_message": {"id": "m2"}, "awaiting_admin": True},
        ]),
        _inbox_payload("2026-05-27T10:00:10Z", []),
    ]

    lumenx = MagicMock()
    lumenx.get_inbox.side_effect = inbox_calls
    lumenx.get_thread.side_effect = lambda tid: {
        "thread": {"id": tid, "username": "u"},
        "messages": [{"role": "customer", "text": f"hi from {tid}"}],
    }

    processed: list[str] = []

    def fake_process(thread: dict) -> int:
        processed.append(thread["thread"]["id"])
        return 999

    poller = Poller(
        lumenx=lumenx,
        conn=db,
        process_thread=fake_process,
        poll_interval_seconds=0.01,
    )
    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.05)
    poller.stop()
    await task

    assert sorted(processed) == ["t1", "t2"]


@pytest.mark.asyncio
async def test_poller_dedups_same_last_msg(db):
    payload = _inbox_payload("2026-05-27T10:00:00Z", [
        {"thread": {"id": "t1"}, "last_customer_message": {"id": "m1"}, "awaiting_admin": True},
    ])
    lumenx = MagicMock()
    lumenx.get_inbox.return_value = payload
    lumenx.get_thread.return_value = {
        "thread": {"id": "t1", "username": "u"},
        "messages": [{"role": "customer", "text": "hi"}],
    }

    processed: list[str] = []
    def fake_process(thread: dict) -> int:
        processed.append(thread["thread"]["id"])
        return 1

    poller = Poller(
        lumenx=lumenx, conn=db,
        process_thread=fake_process, poll_interval_seconds=0.01,
    )
    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.05)
    poller.stop()
    await task

    assert processed.count("t1") == 1


@pytest.mark.asyncio
async def test_poller_skips_not_awaiting_admin(db):
    payload = _inbox_payload("t0", [
        {"thread": {"id": "t1"}, "last_customer_message": {"id": "m1"}, "awaiting_admin": False},
    ])
    lumenx = MagicMock()
    lumenx.get_inbox.return_value = payload

    processed: list[str] = []
    def fake_process(thread: dict) -> int:
        processed.append(thread["thread"]["id"])
        return 1

    poller = Poller(
        lumenx=lumenx, conn=db,
        process_thread=fake_process, poll_interval_seconds=0.01,
    )
    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.03)
    poller.stop()
    await task

    assert processed == []


@pytest.mark.asyncio
async def test_poller_continues_after_process_failure(db):
    payload = _inbox_payload("t0", [
        {"thread": {"id": "good"}, "last_customer_message": {"id": "m1"}, "awaiting_admin": True},
        {"thread": {"id": "bad"}, "last_customer_message": {"id": "m2"}, "awaiting_admin": True},
    ])
    lumenx = MagicMock()
    lumenx.get_inbox.return_value = payload
    lumenx.get_thread.side_effect = lambda tid: {
        "thread": {"id": tid, "username": "u"},
        "messages": [{"role": "customer", "text": tid}],
    }

    def fake_process(thread: dict) -> int:
        if thread["thread"]["id"] == "bad":
            raise RuntimeError("draft failed")
        return 1

    poller = Poller(
        lumenx=lumenx, conn=db,
        process_thread=fake_process, poll_interval_seconds=0.01,
    )
    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.05)
    poller.stop()
    await task

    seen = {r["thread_id"] for r in db.execute("SELECT thread_id FROM threads_seen")}
    assert "good" in seen
    assert "bad" not in seen
