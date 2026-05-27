from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    lumenx_base: str = Field(default="https://lumenx-demo.up.railway.app")
    lumenx_admin_token: str
    anthropic_api_key: str

    threshold: float = 0.85
    auto_send_enabled: bool = False
    daily_spend_cap_usd: float = 5.0

    agent_dashboard_password: str
    agent_db_path: Path = Path("./data/agent.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
