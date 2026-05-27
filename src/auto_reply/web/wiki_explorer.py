from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from auto_reply.pipeline.wiki_qa import WikiQA

TEMPLATES_DIR = Path(__file__).parent / "templates"


class _AskBody(BaseModel):
    question: str = Field(min_length=1)


def make_router(
    *,
    wiki_dir: Path,
    graph_path: Path,
    wiki_qa: WikiQA,
) -> APIRouter:
    router = APIRouter(prefix="/wiki", tags=["wiki"])
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @router.get("")
    def page(request: Request):
        return templates.TemplateResponse(request, "wiki.html", {})

    @router.get("/graph.json")
    def graph() -> JSONResponse:
        if not graph_path.exists():
            return JSONResponse(
                {"error": "graph not built; run scripts/build_wiki_graph.py"},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        data: dict[str, Any] = json.loads(graph_path.read_text(encoding="utf-8"))
        return JSONResponse(data)

    @router.get("/doc/{product_id}")
    def doc(product_id: str) -> dict[str, str]:
        if not product_id.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(status_code=404)
        path = wiki_dir / f"{product_id}.md"
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404)
        return {"product_id": product_id, "markdown": path.read_text(encoding="utf-8")}

    @router.post("/ask")
    def ask(body: _AskBody) -> dict[str, Any]:
        q = body.question.strip()
        if not q:
            raise HTTPException(status_code=400, detail="empty question")
        answer = wiki_qa.ask(q)
        return {
            "answer_markdown": answer.answer_markdown,
            "citations": [asdict(c) for c in answer.citations],
        }

    return router
