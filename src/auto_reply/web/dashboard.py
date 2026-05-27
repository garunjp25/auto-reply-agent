from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"


def make_router(*, conn: sqlite3.Connection, password: str) -> APIRouter:
    router = APIRouter(prefix="/agent", tags=["agent"])
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    security = HTTPBasic()

    def require_admin(creds: HTTPBasicCredentials = Depends(security)) -> None:
        if not secrets.compare_digest(creds.password, password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bad credentials",
                headers={"WWW-Authenticate": "Basic"},
            )

    @router.get("/queue")
    def queue(request: Request, _: None = Depends(require_admin)):
        rows = conn.execute(
            "SELECT id, thread_id, customer_msg, draft_text, intent, sensitive, "
            "context_json, created_at "
            "FROM drafts WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        drafts = [dict(r) for r in rows]
        return templates.TemplateResponse(
            request, "queue.html", {"drafts": drafts}
        )

    return router
