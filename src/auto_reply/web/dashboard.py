from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from auto_reply.store.feedback import record_feedback_with_label

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

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Feedback actions
    # ------------------------------------------------------------------

    def _get_pending_draft(draft_id: int) -> dict:
        row = conn.execute(
            "SELECT id, status FROM drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="Draft already actioned")
        return dict(row)

    @router.post("/drafts/{draft_id}/approve")
    def approve_draft(
        draft_id: int,
        request: Request,
        _: None = Depends(require_admin),
    ):
        _get_pending_draft(draft_id)
        record_feedback_with_label(conn, draft_id, "approve")
        if request.headers.get("HX-Request"):
            return HTMLResponse(_actioned_row_html(draft_id, "approved"))
        return HTMLResponse(_redirect_queue())

    @router.post("/drafts/{draft_id}/reject")
    def reject_draft(
        draft_id: int,
        request: Request,
        _: None = Depends(require_admin),
    ):
        _get_pending_draft(draft_id)
        record_feedback_with_label(conn, draft_id, "reject")
        if request.headers.get("HX-Request"):
            return HTMLResponse(_actioned_row_html(draft_id, "rejected"))
        return HTMLResponse(_redirect_queue())

    @router.post("/drafts/{draft_id}/edit")
    def edit_draft(
        draft_id: int,
        request: Request,
        reply: str = Form(...),
        _: None = Depends(require_admin),
    ):
        _get_pending_draft(draft_id)
        record_feedback_with_label(conn, draft_id, "edit", edited_reply=reply)
        if request.headers.get("HX-Request"):
            return HTMLResponse(_actioned_row_html(draft_id, "edited"))
        return HTMLResponse(_redirect_queue())

    # ------------------------------------------------------------------
    # Activity tab
    # ------------------------------------------------------------------

    @router.get("/activity")
    def activity(request: Request, _: None = Depends(require_admin)):
        intent_rows = conn.execute(
            """
            SELECT intent, COUNT(*) as n
            FROM drafts
            WHERE created_at >= datetime('now', '-7 days')
            GROUP BY intent
            ORDER BY n DESC
            """
        ).fetchall()
        status_rows = conn.execute(
            """
            SELECT status, COUNT(*) as n
            FROM drafts
            WHERE created_at >= datetime('now', '-7 days')
            GROUP BY status
            """
        ).fetchall()
        total = sum(r["n"] for r in status_rows)
        approved = next((r["n"] for r in status_rows if r["status"] == "approved"), 0)
        rejected = next((r["n"] for r in status_rows if r["status"] == "rejected"), 0)
        edited = next((r["n"] for r in status_rows if r["status"] == "edited"), 0)
        actioned = approved + rejected + edited
        approval_rate = round(approved / actioned * 100, 1) if actioned else 0.0
        return templates.TemplateResponse(
            request,
            "activity.html",
            {
                "intent_rows": [dict(r) for r in intent_rows],
                "status_rows": [dict(r) for r in status_rows],
                "total": total,
                "approval_rate": approval_rate,
                "approved": approved,
                "rejected": rejected,
                "edited": edited,
            },
        )

    # ------------------------------------------------------------------
    # Costs tab
    # ------------------------------------------------------------------

    @router.get("/costs")
    def costs(request: Request, _: None = Depends(require_admin)):
        daily_rows = conn.execute(
            """
            SELECT DATE(at) as day, purpose, SUM(cost_usd) as spend
            FROM cost_log
            WHERE at >= datetime('now', '-14 days')
            GROUP BY day, purpose
            ORDER BY day DESC, spend DESC
            """
        ).fetchall()
        total_row = conn.execute(
            "SELECT SUM(cost_usd) as total FROM cost_log"
        ).fetchone()
        top_calls = conn.execute(
            """
            SELECT call_id, model, purpose, cost_usd, at
            FROM cost_log
            ORDER BY cost_usd DESC
            LIMIT 5
            """
        ).fetchall()
        return templates.TemplateResponse(
            request,
            "costs.html",
            {
                "daily_rows": [dict(r) for r in daily_rows],
                "total_usd": round(total_row["total"] or 0.0, 6),
                "top_calls": [dict(r) for r in top_calls],
            },
        )

    return router


# ------------------------------------------------------------------
# HTML helpers for HTMX responses
# ------------------------------------------------------------------

def _actioned_row_html(draft_id: int, label: str) -> str:
    colour = {"approved": "#2a7", "edited": "#a72", "rejected": "#999"}[label]
    return (
        f'<tr id="draft-{draft_id}" style="opacity:0.5">'
        f'<td colspan="6" style="color:{colour};font-style:italic">✓ {label}</td>'
        f"</tr>"
    )


def _redirect_queue() -> str:
    return '<meta http-equiv="refresh" content="0;url=/agent/queue">'
