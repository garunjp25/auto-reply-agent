import os
from pathlib import Path

import pytest

from auto_reply.settings import Settings


def test_settings_reads_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LUMENX_BASE", "https://example.test")
    monkeypatch.setenv("LUMENX_ADMIN_TOKEN", "lmx_abc")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xyz")
    monkeypatch.setenv("AGENT_DASHBOARD_PASSWORD", "hunter2")
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("THRESHOLD", "0.9")
    monkeypatch.setenv("AUTO_SEND_ENABLED", "true")
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "2.50")

    s = Settings()

    assert s.lumenx_base == "https://example.test"
    assert s.lumenx_admin_token == "lmx_abc"
    assert s.anthropic_api_key == "sk-ant-xyz"
    assert s.threshold == 0.9
    assert s.auto_send_enabled is True
    assert s.daily_spend_cap_usd == 2.50
    assert s.agent_db_path == tmp_path / "agent.db"


def test_settings_missing_required(monkeypatch):
    for var in ("LUMENX_ADMIN_TOKEN", "ANTHROPIC_API_KEY", "AGENT_DASHBOARD_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LUMENX_BASE", "x")
    with pytest.raises(Exception):
        Settings()
