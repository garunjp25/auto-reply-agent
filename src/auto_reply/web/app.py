from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import Anthropic
from fastapi import FastAPI

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.context_builder import ContextBuilder
from auto_reply.pipeline.drafter import Drafter
from auto_reply.pipeline.intent_router import IntentRouter
from auto_reply.pipeline.process_message import process_message
from auto_reply.settings import get_settings
from auto_reply.sources.lumenx import LumenXClient
from auto_reply.sources.poller import Poller
from auto_reply.sources.wiki_loader import WikiLoader
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations, current_version
from auto_reply.tls import enable_system_certs
from auto_reply.web.dashboard import make_router

WIKI_DIR = Path(__file__).resolve().parents[3] / "wiki"

log = logging.getLogger(__name__)


def create_app(*, run_poller: bool = True) -> FastAPI:
    enable_system_certs()
    settings = get_settings()
    conn = connect(settings.agent_db_path)
    apply_migrations(conn)

    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)
    intent_router = IntentRouter(llm=llm)
    wiki_text = WikiLoader(WIKI_DIR).concatenated() if WIKI_DIR.exists() else ""
    ctx_builder = ContextBuilder(wiki_text=wiki_text)
    drafter = Drafter(llm=llm)
    lumenx = LumenXClient(settings.lumenx_base, settings.lumenx_admin_token)

    def _process(thread):
        return process_message(
            thread=thread,
            conn=conn,
            intent_router=intent_router,
            context_builder=ctx_builder,
            drafter=drafter,
        )

    poller = Poller(
        lumenx=lumenx,
        conn=conn,
        process_thread=_process,
        poll_interval_seconds=10.0,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task: asyncio.Task | None = None
        if run_poller:
            task = asyncio.create_task(poller.run())
            log.info("poller started")
        try:
            yield
        finally:
            if task is not None:
                poller.stop()
                await task
                log.info("poller stopped")
            lumenx.close()

    app = FastAPI(title="auto-reply-agent", version="0.0.0", lifespan=lifespan)
    app.state.db = conn
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "schema_version": current_version(conn)}

    app.include_router(make_router(conn=conn, password=settings.agent_dashboard_password))
    return app
