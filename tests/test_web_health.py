from fastapi.testclient import TestClient


def test_health_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMENX_ADMIN_TOKEN", "lmx_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_DASHBOARD_PASSWORD", "pw")
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent.db"))

    from auto_reply.settings import get_settings  # noqa: E402

    get_settings.cache_clear()

    from auto_reply.web.app import create_app  # noqa: E402

    app = create_app(run_poller=False)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == 2
    assert (tmp_path / "agent.db").exists()


def test_root_landing_page(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMENX_ADMIN_TOKEN", "lmx_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_DASHBOARD_PASSWORD", "pw")
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent.db"))

    from auto_reply.settings import get_settings
    get_settings.cache_clear()

    from auto_reply.web.app import create_app
    app = create_app(run_poller=False)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "wiki" in r.text.lower()
    assert "agent" in r.text.lower()


def test_queue_route_registered(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMENX_ADMIN_TOKEN", "lmx_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_DASHBOARD_PASSWORD", "pw")
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent.db"))

    from auto_reply.settings import get_settings
    get_settings.cache_clear()

    from auto_reply.web.app import create_app
    app = create_app(run_poller=False)
    client = TestClient(app)
    r = client.get("/agent/queue")
    assert r.status_code == 401  # auth required, route exists
