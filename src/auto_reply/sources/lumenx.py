from typing import Any

import httpx


class LumenXClient:
    """Sync HTTP client for the LumenX admin API.

    Auth via the X-Admin-Token header on every request. No retries (retries
    belong in the Poller, not here). All errors raise httpx.HTTPStatusError.
    """

    def __init__(
        self,
        base_url: str,
        admin_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-Admin-Token": admin_token},
            transport=transport,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LumenXClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_products(self) -> dict[str, Any]:
        r = self._client.get("/api/admin/products")
        r.raise_for_status()
        return r.json()

    def get_inbox(self, since: str | None = None) -> dict[str, Any]:
        params = {"since": since} if since else None
        r = self._client.get("/api/admin/inbox", params=params)
        r.raise_for_status()
        return r.json()

    def get_threads(self) -> dict[str, Any]:
        r = self._client.get("/api/admin/threads")
        r.raise_for_status()
        return r.json()

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        r = self._client.get(f"/api/admin/threads/{thread_id}")
        r.raise_for_status()
        return r.json()

    def get_export(self) -> dict[str, Any]:
        r = self._client.get("/api/admin/export")
        r.raise_for_status()
        return r.json()

    def post_reply(
        self,
        *,
        thread_id: str,
        text: str,
        draft_source: str = "agent",
        confidence: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text, "draft_source": draft_source}
        if confidence is not None:
            body["confidence"] = confidence
        r = self._client.post(f"/api/admin/threads/{thread_id}/reply", json=body)
        r.raise_for_status()
        return r.json()

    def mark_read(self, thread_id: str) -> dict[str, Any]:
        r = self._client.post(f"/api/admin/threads/{thread_id}/mark-read")
        r.raise_for_status()
        return r.json()
