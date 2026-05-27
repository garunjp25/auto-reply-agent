from fastapi import FastAPI

from auto_reply.settings import get_settings
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations, current_version


def create_app() -> FastAPI:
    app = FastAPI(title="auto-reply-agent", version="0.0.0")
    settings = get_settings()

    conn = connect(settings.agent_db_path)
    apply_migrations(conn)
    app.state.db = conn
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "schema_version": current_version(conn),
        }

    return app
