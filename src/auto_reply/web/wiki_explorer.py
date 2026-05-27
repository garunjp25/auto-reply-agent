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

# Hand-curated category for each of the 20 LumenX products. The graph display
# uses these to colour nodes by domain. "Hub" is reserved for the synthetic
# central LumenX node.
PRODUCT_CATEGORIES: dict[str, str] = {
    "emailpilot":   "Communication",
    "chatrelay":    "Communication",
    "inboxclean":   "Communication",
    "invoiceflow":  "Finance",
    "receiptvault": "Finance",
    "billsplit":    "Finance",
    "taskgrid":     "Tasks & Projects",
    "kanbanlite":   "Tasks & Projects",
    "documerge":    "Documents",
    "signpath":     "Documents",
    "linkvault":    "Documents",
    "audittrail":   "Documents",
    "calendarsync": "Productivity",
    "timemark":     "Productivity",
    "meetminutes":  "Productivity",
    "teampulse":    "Productivity",
    "pollwise":     "Productivity",
    "notehub":      "Core Pages",
    "formcraft":    "Core Pages",
    "pixeldeck":    "Core Pages",
}

HUB_ID = "lumenx"
HUB_NODE = {
    "id": HUB_ID,
    "label": "LumenX",
    "tagline": "central hub",
    "summary": "LumenX Knowledge Universe — every product orbits this hub.",
    "category": "Hub",
}
HUB_DOC_MARKDOWN = """# LumenX Knowledge Universe

The central hub of the LumenX product knowledge base. Every product in the
catalog is one click away. Click any orbiting planet to read its full wiki,
or use the **Ask the Wiki** tab to query the entire corpus with sourced
citations.

## What lives here

- **20 SaaS products** spanning Communication, Finance, Tasks & Projects,
  Documents, Productivity, and Core Pages.
- **Semantic cross-links** between products (shared audiences, shared
  integrations, similar functions).
- **Grounded Q&A** powered by Claude Sonnet 4.6 — every answer cites the
  exact wiki it came from.
"""


def _categorize(product_id: str) -> str:
    return PRODUCT_CATEGORIES.get(product_id, "Productivity")


def _augment_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Add `category` to every node and inject the synthetic LumenX hub.

    The hub is connected to every product node so the layout naturally puts
    it at the centre.
    """
    nodes_raw = graph.get("nodes", []) or []
    edges_raw = graph.get("edges", []) or []

    nodes: list[dict[str, Any]] = []
    product_ids: list[str] = []
    for n in nodes_raw:
        if not isinstance(n, dict) or "id" not in n:
            continue
        product_ids.append(n["id"])
        nodes.append({**n, "category": _categorize(n["id"])})

    # Hub node + spoke edges.
    nodes.insert(0, HUB_NODE)
    hub_edges = [
        {"source": HUB_ID, "target": pid, "relation": "hub", "reason": "hub spoke"}
        for pid in product_ids
    ]

    edges: list[dict[str, Any]] = []
    for e in edges_raw:
        if isinstance(e, dict) and e.get("source") and e.get("target"):
            edges.append(e)

    return {"nodes": nodes, "edges": hub_edges + edges}


class _AskBody(BaseModel):
    question: str = Field(min_length=1)


def _related_for(product_id: str, graph_path: Path) -> list[dict[str, str]]:
    """Return up to 8 related products derived from the graph's edges.

    Edges are treated as undirected; the partner endpoint becomes the relation
    target. The graph JSON has been validated by the build script so missing
    endpoints are rare, but we defensively filter them anyway.
    """
    if not graph_path.exists():
        return []
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    label_by_id: dict[str, str] = {
        n["id"]: n.get("label") or n["id"]
        for n in graph.get("nodes", [])
        if isinstance(n, dict) and "id" in n
    }
    related: list[dict[str, str]] = []
    seen: set[str] = set()
    for e in graph.get("edges", []) or []:
        if not isinstance(e, dict):
            continue
        src = e.get("source")
        tgt = e.get("target")
        partner = tgt if src == product_id else (src if tgt == product_id else None)
        if partner is None or partner in seen or partner not in label_by_id:
            continue
        seen.add(partner)
        related.append({
            "id": partner,
            "label": label_by_id[partner],
            "relation": str(e.get("relation") or ""),
            "reason": str(e.get("reason") or ""),
        })
    return related[:8]


def _format_related_section(related: list[dict[str, str]]) -> str:
    """Render the related-products block as a markdown section.

    Links use the `product:<id>` scheme so the SPA can intercept clicks and
    navigate within the wiki instead of letting the browser follow the link.
    """
    if not related:
        return ""
    lines = ["\n\n---\n\n## Related Products\n"]
    for r in related:
        reason = f" — _{r['reason']}_" if r["reason"] else ""
        lines.append(f"- [{r['label']}](product:{r['id']}){reason}")
    return "\n".join(lines) + "\n"


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
        raw: dict[str, Any] = json.loads(graph_path.read_text(encoding="utf-8"))
        return JSONResponse(_augment_graph(raw))

    @router.get("/doc/{product_id}")
    def doc(product_id: str) -> dict[str, Any]:
        if not product_id.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(status_code=404)
        # The synthetic hub has no .md file — serve a hand-written intro.
        if product_id == HUB_ID:
            related = [
                {"id": pid, "label": pid, "relation": "hub", "reason": _categorize(pid)}
                for pid in PRODUCT_CATEGORIES.keys()
            ]
            return {
                "product_id": HUB_ID,
                "markdown": HUB_DOC_MARKDOWN + _format_related_section(related),
                "related": related,
                "category": "Hub",
            }
        path = wiki_dir / f"{product_id}.md"
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404)
        markdown = path.read_text(encoding="utf-8")
        related = _related_for(product_id, graph_path)
        markdown += _format_related_section(related)
        return {
            "product_id": product_id,
            "markdown": markdown,
            "related": related,
            "category": _categorize(product_id),
        }

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
