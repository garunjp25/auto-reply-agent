from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

from auto_reply.sources.lumenx import LumenXClient
from auto_reply.store.db import transaction

log = logging.getLogger(__name__)


class Poller:
    """Polls /api/admin/inbox and dispatches awaiting threads."""

    def __init__(
        self,
        *,
        lumenx: LumenXClient,
        conn: sqlite3.Connection,
        process_thread: Callable[[dict[str, Any]], int],
        poll_interval_seconds: float = 10.0,
    ) -> None:
        self._lumenx = lumenx
        self._conn = conn
        self._process_thread = process_thread
        self._interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._since: str | None = self._load_since()

    def _load_since(self) -> str | None:
        row = self._conn.execute(
            "SELECT last_seen_at FROM threads_seen WHERE thread_id = '__cursor__'"
        ).fetchone()
        return row["last_seen_at"] if row else None

    def _save_since(self, value: str) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO threads_seen (thread_id, last_msg_id, last_seen_at) "
                "VALUES ('__cursor__', NULL, ?)",
                (value,),
            )

    def _already_seen(self, thread_id: str, last_msg_id: str | None) -> bool:
        row = self._conn.execute(
            "SELECT last_msg_id FROM threads_seen WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return row is not None and row["last_msg_id"] == last_msg_id

    def _mark_seen(self, thread_id: str, last_msg_id: str | None) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO threads_seen (thread_id, last_msg_id, last_seen_at) "
                "VALUES (?, ?, ?)",
                (thread_id, last_msg_id, datetime.now(timezone.utc).isoformat()),
            )

    def stop(self) -> None:
        self._stop_event.set()

    def _safe_tick(self) -> None:
        """Wrapper so StopIteration never escapes into asyncio.to_thread."""
        try:
            self._tick()
        except StopIteration:
            raise RuntimeError("inbox side_effect exhausted (StopIteration wrapped)")

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._safe_tick)
            except Exception:
                log.exception("poller tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    def _tick(self) -> None:
        payload = self._lumenx.get_inbox(since=self._since)
        for entry in payload.get("entries", []) or []:
            if not entry.get("awaiting_admin"):
                continue
            thread_id = entry.get("thread", {}).get("id")
            last_msg = entry.get("last_customer_message") or {}
            last_msg_id = last_msg.get("id")
            if thread_id is None:
                continue
            if self._already_seen(thread_id, last_msg_id):
                continue
            try:
                full = self._lumenx.get_thread(thread_id)
                self._process_thread(full)
            except Exception:
                log.exception("process failed for thread %s", thread_id)
                continue
            self._mark_seen(thread_id, last_msg_id)

        server_time = payload.get("server_time")
        if server_time:
            self._since = server_time
            self._save_since(server_time)
