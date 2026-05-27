import httpx
import pytest

from auto_reply.sources.lumenx import LumenXClient


def test_get_products_uses_admin_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/admin/products"
        assert request.headers["X-Admin-Token"] == "lmx_test"
        return httpx.Response(200, json={"products": [{"id": "emailpilot"}]})

    transport = httpx.MockTransport(handler)
    client = LumenXClient(
        base_url="https://lumenx.test",
        admin_token="lmx_test",
        transport=transport,
    )
    data = client.get_products()
    assert data == {"products": [{"id": "emailpilot"}]}
    client.close()


def test_get_thread_by_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/admin/threads/abc-123"
        return httpx.Response(200, json={"thread": {"id": "abc-123"}})

    transport = httpx.MockTransport(handler)
    client = LumenXClient("https://lumenx.test", "lmx_test", transport=transport)
    data = client.get_thread("abc-123")
    assert data == {"thread": {"id": "abc-123"}}
    client.close()


def test_get_export():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/admin/export"
        return httpx.Response(200, json={"threads": [], "products": []})

    transport = httpx.MockTransport(handler)
    client = LumenXClient("https://lumenx.test", "lmx_test", transport=transport)
    data = client.get_export()
    assert "threads" in data and "products" in data
    client.close()


def test_raises_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad token"})

    transport = httpx.MockTransport(handler)
    client = LumenXClient("https://lumenx.test", "wrong", transport=transport)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_products()
    client.close()


def test_post_reply():
    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        posted["url"] = str(request.url.path)
        posted["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = LumenXClient("https://lumenx.test", "lmx_test", transport=transport)
    res = client.post_reply(
        thread_id="abc",
        text="hello",
        draft_source="agent",
        confidence=0.92,
    )
    assert res == {"ok": True}
    assert posted["url"] == "/api/admin/threads/abc/reply"
    body = posted["body"].decode()
    assert '"text":"hello"' in body or '"text": "hello"' in body
    assert '"draft_source":"agent"' in body or '"draft_source": "agent"' in body
    client.close()
