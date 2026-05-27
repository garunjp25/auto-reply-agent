from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import Anthropic
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.context_builder import ContextBuilder
from auto_reply.pipeline.drafter import Drafter
from auto_reply.pipeline.intent_router import IntentRouter
from auto_reply.pipeline.process_message import process_message
from auto_reply.pipeline.wiki_qa import WikiQA
from auto_reply.settings import get_settings
from auto_reply.sources.lumenx import LumenXClient
from auto_reply.sources.poller import Poller
from auto_reply.sources.wiki_loader import WikiLoader
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations, current_version
from auto_reply.tls import enable_system_certs
from auto_reply.web.dashboard import make_router
from auto_reply.web.wiki_explorer import make_router as make_wiki_router

WIKI_DIR = Path(__file__).resolve().parents[3] / "wiki"
GRAPH_PATH = Path(__file__).resolve().parents[3] / "data" / "wiki_graph.json"

log = logging.getLogger(__name__)


def create_app(*, run_poller: bool = True) -> FastAPI:
    enable_system_certs()
    settings = get_settings()
    conn = connect(settings.agent_db_path)
    apply_migrations(conn)

    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)
    intent_router = IntentRouter(llm=llm)
    wiki_loader = WikiLoader(WIKI_DIR)
    wiki_available = WIKI_DIR.exists() and any(WIKI_DIR.glob("*.md"))
    if not wiki_available:
        log.warning("wiki/ not found or empty — wiki Q&A disabled, agent still runs")
    wiki_text = wiki_loader.concatenated() if wiki_available else ""
    wiki_docs = wiki_loader.load_all() if wiki_available else {}
    ctx_builder = ContextBuilder(wiki_text=wiki_text)
    drafter = Drafter(llm=llm)
    wiki_qa = WikiQA(llm=llm, wiki_docs=wiki_docs)
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

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>auto-reply agent</title>
<style>
  body{font-family:-apple-system,system-ui,sans-serif;max-width:520px;margin:4rem auto;padding:0 1rem;color:#222}
  h1{font-size:1.5rem;margin-bottom:0.25rem}p.sub{color:#666;margin-bottom:2rem}
  .cards{display:flex;gap:1rem;flex-wrap:wrap}
  .card{flex:1;min-width:200px;border:1px solid #dde;border-radius:8px;padding:1.25rem 1.5rem;text-decoration:none;color:inherit}
  .card:hover{background:#f5f7ff;border-color:#aac}
  .card h2{font-size:1rem;margin:0 0 0.4rem}
  .card p{font-size:0.85rem;color:#556;margin:0}
</style></head>
<body>
  <h1>🤖 auto-reply agent</h1>
  <p class="sub">LumenX customer-support automation</p>
  <div class="cards">
    <a class="card" href="/wiki">
      <h2>📚 Wiki Explorer</h2>
      <p>Interactive knowledge graph + AI-powered Q&amp;A across all product docs</p>
    </a>
    <a class="card" href="/agent/queue">
      <h2>🗂 Agent Dashboard</h2>
      <p>Review and action pending draft replies (Queue · Activity · Costs)</p>
    </a>
  </div>
</body></html>"""

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "schema_version": current_version(conn)}

    app.include_router(make_router(conn=conn, password=settings.agent_dashboard_password))
    app.include_router(
        make_wiki_router(wiki_dir=WIKI_DIR, graph_path=GRAPH_PATH, wiki_qa=wiki_qa)
    )
    return app
