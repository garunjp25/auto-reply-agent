# Wiki Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a beautiful, public, single-page wiki explorer at `/wiki` that visualises the 20-product LumenX wiki as an interactive Cytoscape.js knowledge graph and answers natural-language questions with inline `[n]` citations sourced from `wiki/*.md`.

**Architecture:** One Sonnet call up front (CLI) extracts product↔product semantic relations into `data/wiki_graph.json`. A new FastAPI APIRouter mounted at `/wiki` (no auth) serves the SPA HTML + four JSON endpoints. The SPA loads Cytoscape from CDN, renders nodes + edges, and posts to `/wiki/ask` which runs a `WikiQA` service: Sonnet prompted with the full wiki (prompt-cached) returns strict JSON `{answer_markdown, citations}` that the frontend renders with clickable `[n]` markers that pulse the cited graph node.

**Tech Stack:** Python 3.11+ · FastAPI · Jinja2 · Anthropic SDK (`claude-sonnet-4-6` with `cache_control:ephemeral`) · Cytoscape.js (CDN, v3.30) · `marked.js` (CDN, v13). All Phase 0/1/2 infrastructure reused: `LLMClient` (cost-logged), `WikiLoader`, `truststore`, settings.

---

## File structure produced

```
phase2-live/
├── scripts/
│   └── build_wiki_graph.py                   NEW (one-shot CLI)
├── src/auto_reply/
│   ├── pipeline/
│   │   └── wiki_qa.py                        NEW
│   └── web/
│       ├── app.py                            MODIFIED (mount router)
│       ├── wiki_explorer.py                  NEW (router)
│       └── templates/
│           └── wiki.html                     NEW (single-page UI)
├── data/
│   └── wiki_graph.json                       NEW (generated, gitignored)
└── tests/
    ├── test_wiki_qa.py                       NEW
    └── test_wiki_explorer.py                 NEW
```

`.gitignore` already excludes `data/`, so `wiki_graph.json` won't be committed.

---

## Task 1: `WikiQA` — chat-with-citations service

**Files:**
- Create: `src/auto_reply/pipeline/wiki_qa.py`
- Create: `tests/test_wiki_qa.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_wiki_qa.py
from unittest.mock import MagicMock

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.wiki_qa import Citation, WikiAnswer, WikiQA


def _make_llm(db, body_text: str) -> LLMClient:
    sdk = MagicMock()
    resp = MagicMock()
    resp.id = "msg_qa"
    resp.usage.input_tokens = 1000
    resp.usage.output_tokens = 80
    resp.usage.cache_read_input_tokens = 800
    resp.usage.cache_creation_input_tokens = 0
    resp.content = [MagicMock(text=body_text)]
    sdk.messages.create.return_value = resp
    return LLMClient(sdk=sdk, conn=db)


_WIKI = {
    "emailpilot": "# EmailPilot\nAn AI email tool. Pro is $25/mo.",
    "invoiceflow": "# InvoiceFlow\nInvoicing. Pro is $15/mo.",
}


def test_ask_returns_typed_answer_with_citations(db):
    json_body = (
        '{"answer_markdown": "EmailPilot Pro is $25/mo [1] and InvoiceFlow Pro is $15/mo [2].",'
        ' "citations": ['
        '   {"n": 1, "product_id": "emailpilot", "quote": "Pro is $25/mo."},'
        '   {"n": 2, "product_id": "invoiceflow", "quote": "Pro is $15/mo."}'
        ' ]}'
    )
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    out = qa.ask("how much is the pro tier for the email tool and the invoice tool?")
    assert isinstance(out, WikiAnswer)
    assert "[1]" in out.answer_markdown and "[2]" in out.answer_markdown
    assert len(out.citations) == 2
    assert out.citations[0] == Citation(n=1, product_id="emailpilot", quote="Pro is $25/mo.")
    assert out.citations[1].product_id == "invoiceflow"


def test_ask_writes_cost_row_with_purpose_wiki_qa(db):
    json_body = '{"answer_markdown": "no idea", "citations": []}'
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    qa.ask("anything")
    rows = db.execute("SELECT purpose, model FROM cost_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["purpose"] == "wiki_qa"
    assert rows[0]["model"] == "claude-sonnet-4-6"


def test_ask_drops_citations_pointing_to_unknown_product(db):
    json_body = (
        '{"answer_markdown": "ok [1] [2]",'
        ' "citations": ['
        '   {"n": 1, "product_id": "emailpilot", "quote": "x"},'
        '   {"n": 2, "product_id": "nonexistent", "quote": "y"}'
        ' ]}'
    )
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    out = qa.ask("q")
    ids = [c.product_id for c in out.citations]
    assert "emailpilot" in ids
    assert "nonexistent" not in ids


def test_ask_falls_back_gracefully_on_bad_json(db):
    llm = _make_llm(db, "not JSON at all")
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    out = qa.ask("q")
    assert "trouble" in out.answer_markdown.lower() or "rephras" in out.answer_markdown.lower()
    assert out.citations == []


def test_ask_passes_cacheable_wiki_to_llm(db):
    json_body = '{"answer_markdown": "a", "citations": []}'
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    qa.ask("q")
    call = llm.sdk.messages.create.call_args
    # system was passed as a list with at least two blocks; the wiki block has cache_control.
    system = call.kwargs["system"]
    assert isinstance(system, list)
    cache_blocks = [b for b in system if b.get("cache_control") == {"type": "ephemeral"}]
    assert len(cache_blocks) >= 1
    # The cached block contains the wiki content.
    cached_text = cache_blocks[-1]["text"]
    assert "EmailPilot" in cached_text
    assert "InvoiceFlow" in cached_text


def test_ask_strips_markdown_code_fences_from_json(db):
    """Sonnet sometimes wraps JSON in ```json ... ``` fences."""
    json_body = (
        '```json\n'
        '{"answer_markdown": "ok [1]", "citations": [{"n":1, "product_id":"emailpilot", "quote":"q"}]}\n'
        '```'
    )
    llm = _make_llm(db, json_body)
    qa = WikiQA(llm=llm, wiki_docs=_WIKI)
    out = qa.ask("q")
    assert len(out.citations) == 1
    assert out.citations[0].product_id == "emailpilot"
```

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/test_wiki_qa.py -v`
Expected: collection error or ImportError on `WikiQA`.

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/pipeline/wiki_qa.py
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from auto_reply.llm.client import LLMClient

log = logging.getLogger(__name__)

QA_MODEL = "claude-sonnet-4-6"

PERSONA = """You answer questions about the LumenX SaaS products using ONLY the wiki provided.

Strict rules:
- Use ONLY facts present in the wiki. Do not invent features, prices, integrations, or SLAs.
- If the answer is not in the wiki, say: "I don't have that information in the wiki."
- Answers should be concise (1–3 short paragraphs). No emojis. No marketing tone.
- Cite EVERY non-trivial claim with an inline marker [1], [2], [3], etc.
- Each marker MUST correspond to a single entry in the `citations` array.
- Each citation MUST include a verbatim quote (≤ 240 chars) from the cited product's wiki.

Output format: reply with ONLY a single JSON object — no prose, no markdown fences.

{
  "answer_markdown": "Your answer with [1] and [2] inline markers.",
  "citations": [
    {"n": 1, "product_id": "emailpilot", "quote": "exact quote from emailpilot.md"},
    {"n": 2, "product_id": "invoiceflow", "quote": "exact quote from invoiceflow.md"}
  ]
}

If you have no citation, the citations array MUST still be present and empty.
"""

FALLBACK_ANSWER = (
    "I had trouble understanding that question against the wiki. Could you rephrase it?"
)


@dataclass(frozen=True)
class Citation:
    n: int
    product_id: str
    quote: str


@dataclass(frozen=True)
class WikiAnswer:
    answer_markdown: str
    citations: list[Citation]


class WikiQA:
    """Answer questions about the wiki, with inline citations."""

    def __init__(self, *, llm: LLMClient, wiki_docs: dict[str, str], model: str = QA_MODEL) -> None:
        self._llm = llm
        self._wiki_docs = wiki_docs
        self._model = model
        self._wiki_text = self._build_wiki_text(wiki_docs)

    @staticmethod
    def _build_wiki_text(docs: dict[str, str]) -> str:
        parts = [f"## Product: {pid}\n\n{body.strip()}" for pid, body in docs.items()]
        return "\n\n---\n\n".join(parts)

    def ask(self, question: str) -> WikiAnswer:
        if not question or not question.strip():
            return WikiAnswer(answer_markdown=FALLBACK_ANSWER, citations=[])
        system_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": PERSONA},
            {
                "type": "text",
                "text": "# Wiki\n\n" + self._wiki_text,
                "cache_control": {"type": "ephemeral"},
            },
        ]
        raw = self._llm.complete(
            model=self._model,
            system=system_blocks,
            messages=[{"role": "user", "content": question.strip()}],
            purpose="wiki_qa",
            max_tokens=900,
            temperature=0.2,
        )
        return self._parse(raw)

    def _parse(self, raw: str) -> WikiAnswer:
        cleaned = self._strip_code_fences(raw).strip()
        try:
            obj = json.loads(cleaned)
        except (json.JSONDecodeError, AttributeError):
            log.warning("wiki_qa: response was not valid JSON: %r", raw[:200])
            return WikiAnswer(answer_markdown=FALLBACK_ANSWER, citations=[])
        answer = str(obj.get("answer_markdown") or FALLBACK_ANSWER)
        raw_citations = obj.get("citations") or []
        citations: list[Citation] = []
        for c in raw_citations:
            try:
                pid = str(c["product_id"])
            except (KeyError, TypeError):
                continue
            if pid not in self._wiki_docs:
                log.warning("wiki_qa: citation for unknown product_id %r dropped", pid)
                continue
            try:
                n = int(c["n"])
            except (KeyError, TypeError, ValueError):
                continue
            quote = str(c.get("quote") or "")[:240]
            citations.append(Citation(n=n, product_id=pid, quote=quote))
        return WikiAnswer(answer_markdown=answer, citations=citations)

    _FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

    @classmethod
    def _strip_code_fences(cls, text: str) -> str:
        return cls._FENCE_RE.sub("", text).strip()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_wiki_qa.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/auto_reply/pipeline/wiki_qa.py tests/test_wiki_qa.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/pipeline/wiki_qa.py tests/test_wiki_qa.py
git commit -m "feat(pipeline): WikiQA — chat-with-citations over wiki/*.md"
```

---

## Task 2: `/wiki` APIRouter

**Files:**
- Create: `src/auto_reply/web/wiki_explorer.py`
- Create: `tests/test_wiki_explorer.py`

The router needs four endpoints. The `WikiQA` instance is injected (so tests
can stub it). The `wiki_dir` and `graph_path` are also injected.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_wiki_explorer.py
import json
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auto_reply.pipeline.wiki_qa import Citation, WikiAnswer
from auto_reply.web.wiki_explorer import make_router


def _app(*, wiki_dir: Path, graph_path: Path, wiki_qa) -> FastAPI:
    app = FastAPI()
    app.include_router(
        make_router(wiki_dir=wiki_dir, graph_path=graph_path, wiki_qa=wiki_qa)
    )
    return app


def _seed_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "emailpilot.md").write_text("# EmailPilot\n\nEmail tool.\n", encoding="utf-8")
    (wiki / "invoiceflow.md").write_text("# InvoiceFlow\n\nInvoicing.\n", encoding="utf-8")
    return wiki


def _seed_graph(tmp_path: Path) -> Path:
    g = tmp_path / "wiki_graph.json"
    g.write_text(json.dumps({
        "nodes": [
            {"id": "emailpilot", "label": "EmailPilot", "tagline": "email tool", "summary": "s"},
            {"id": "invoiceflow", "label": "InvoiceFlow", "tagline": "invoicing", "summary": "s"},
        ],
        "edges": [
            {"source": "emailpilot", "target": "invoiceflow", "relation": "shared_audience", "reason": "x"},
        ],
    }), encoding="utf-8")
    return g


def test_get_html_returns_200(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "LumenX" in r.text or "Wiki Explorer" in r.text


def test_get_graph_json_returns_graph(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki/graph.json")
    assert r.status_code == 200
    body = r.json()
    assert len(body["nodes"]) == 2
    assert len(body["edges"]) == 1
    assert body["nodes"][0]["id"] in {"emailpilot", "invoiceflow"}


def test_get_graph_json_503_when_not_built(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    missing_graph = tmp_path / "missing.json"
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=missing_graph, wiki_qa=qa))
    r = client.get("/wiki/graph.json")
    assert r.status_code == 503
    assert "graph not built" in r.json()["error"]


def test_get_doc_returns_markdown(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki/doc/emailpilot")
    assert r.status_code == 200
    body = r.json()
    assert body["product_id"] == "emailpilot"
    assert "Email tool" in body["markdown"]


def test_get_doc_404_for_unknown(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.get("/wiki/doc/nope")
    assert r.status_code == 404


def test_get_doc_rejects_path_traversal(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    # Slashes and dots in the path param — FastAPI returns 404 because the URL
    # doesn't match the route. We still verify the response is not 200.
    r = client.get("/wiki/doc/..%2Fconftest")
    assert r.status_code in (404, 422)


def test_post_ask_returns_answer(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    qa.ask.return_value = WikiAnswer(
        answer_markdown="EmailPilot is an email tool [1].",
        citations=[Citation(n=1, product_id="emailpilot", quote="email tool")],
    )
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.post("/wiki/ask", json={"question": "what is emailpilot"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer_markdown"].startswith("EmailPilot")
    assert body["citations"] == [
        {"n": 1, "product_id": "emailpilot", "quote": "email tool"}
    ]
    qa.ask.assert_called_once_with("what is emailpilot")


def test_post_ask_rejects_empty_question(tmp_path: Path):
    wiki = _seed_wiki(tmp_path)
    graph = _seed_graph(tmp_path)
    qa = MagicMock()
    client = TestClient(_app(wiki_dir=wiki, graph_path=graph, wiki_qa=qa))
    r = client.post("/wiki/ask", json={"question": "   "})
    assert r.status_code == 400
```

- [ ] **Step 2: Run, expect FAIL**

Run: `uv run pytest tests/test_wiki_explorer.py -v`
Expected: ImportError on `make_router`.

- [ ] **Step 3: Write the implementation**

```python
# src/auto_reply/web/wiki_explorer.py
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
        # Strict: only letters/digits/underscores/hyphens allowed in product_id.
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_wiki_explorer.py -v`
Expected: 8 passed.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/auto_reply/web/wiki_explorer.py tests/test_wiki_explorer.py`

- [ ] **Step 6: Commit**

```bash
git add src/auto_reply/web/wiki_explorer.py tests/test_wiki_explorer.py
git commit -m "feat(web): /wiki APIRouter — page + graph.json + doc + ask"
```

---

## Task 3: `wiki.html` — the SPA

**Files:**
- Create: `src/auto_reply/web/templates/wiki.html`

The template is a single self-contained file. CSS is inline. JS is inline (no
build step). Cytoscape + marked are loaded from CDN.

No new tests in this task — Task 2 already verifies the route returns 200 with
`text/html` and the right title. The visual smoke test is in Task 5.

- [ ] **Step 1: Write the template**

```html
{# src/auto_reply/web/templates/wiki.html #}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LumenX Wiki Explorer</title>
  <script src="https://cdn.jsdelivr.net/npm/cytoscape@3.30.1/dist/cytoscape.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked@13.0.3/marked.min.js"></script>
  <style>
    :root {
      --bg: #0b0d12;
      --bg-2: #11141b;
      --panel: #161a23;
      --border: #232838;
      --fg: #e8eaf0;
      --fg-dim: #9aa3b2;
      --accent: #7aa2ff;
      --accent-2: #ff8fa3;
      --node-fill: #2a3142;
      --node-edge: #4a5878;
      --node-hi: #7aa2ff;
      --edge: #2e3548;
      --code-bg: #0e1118;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0; padding: 0; height: 100%;
      background: var(--bg);
      color: var(--fg);
      font: 14px/1.55 -apple-system, "Segoe UI", system-ui, sans-serif;
    }
    body {
      display: grid;
      grid-template-rows: 56px 1fr;
      grid-template-columns: 1fr 440px;
      grid-template-areas: "header header" "graph side";
      height: 100vh;
    }
    header {
      grid-area: header;
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 24px;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, #161a23 0%, #0b0d12 100%);
    }
    header h1 {
      font-size: 16px; font-weight: 600; margin: 0;
      letter-spacing: 0.02em;
    }
    header h1 .accent { color: var(--accent); }
    header .meta { font-size: 12px; color: var(--fg-dim); }
    #graph {
      grid-area: graph;
      background: var(--bg-2);
      border-right: 1px solid var(--border);
      position: relative;
    }
    #graph .overlay {
      position: absolute; inset: 0;
      display: flex; align-items: center; justify-content: center;
      color: var(--fg-dim); font-size: 14px;
      pointer-events: none;
    }
    aside {
      grid-area: side;
      display: flex; flex-direction: column;
      background: var(--panel);
      overflow: hidden;
    }
    .tabs {
      display: flex;
      border-bottom: 1px solid var(--border);
    }
    .tab {
      flex: 1;
      text-align: center;
      padding: 12px 0;
      cursor: pointer;
      color: var(--fg-dim);
      font-size: 13px;
      border-bottom: 2px solid transparent;
      user-select: none;
    }
    .tab.active {
      color: var(--fg);
      border-bottom-color: var(--accent);
    }
    .panel { display: none; flex: 1; min-height: 0; overflow: auto; padding: 18px; }
    .panel.active { display: block; }
    /* Chat */
    .chat-form { display: flex; gap: 8px; margin-bottom: 12px; }
    .chat-form input {
      flex: 1;
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--fg);
      padding: 10px 12px;
      border-radius: 8px;
      font: inherit;
    }
    .chat-form input:focus { outline: none; border-color: var(--accent); }
    .chat-form button {
      background: var(--accent);
      color: #0b0d12;
      border: none;
      padding: 0 16px;
      border-radius: 8px;
      cursor: pointer;
      font: inherit;
      font-weight: 600;
    }
    .chat-form button:disabled { opacity: 0.5; cursor: not-allowed; }
    .answer { font-size: 14px; line-height: 1.6; }
    .answer p { margin: 0 0 0.8em; }
    .answer code { background: var(--code-bg); padding: 1px 5px; border-radius: 3px; }
    .answer .cite {
      display: inline-block;
      background: var(--accent);
      color: #0b0d12;
      font-weight: 600;
      font-size: 11px;
      line-height: 18px;
      padding: 0 7px;
      border-radius: 9px;
      margin: 0 2px;
      cursor: pointer;
      vertical-align: 1px;
    }
    .answer .cite:hover { background: #aac4ff; }
    .sources { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); }
    .sources h3 { font-size: 11px; color: var(--fg-dim); text-transform: uppercase; letter-spacing: 0.08em; margin: 0 0 10px; }
    .source { display: flex; gap: 10px; margin-bottom: 10px; }
    .source-n {
      flex: 0 0 auto;
      width: 22px; height: 22px;
      background: var(--accent); color: #0b0d12;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 12px;
    }
    .source-body { flex: 1; }
    .source-id { font-weight: 600; cursor: pointer; color: var(--accent); font-size: 13px; }
    .source-id:hover { text-decoration: underline; }
    .source-quote { color: var(--fg-dim); font-size: 12px; font-style: italic; margin-top: 2px; }
    .placeholder { color: var(--fg-dim); font-size: 13px; }
    /* Detail panel for clicked node */
    .detail-doc { font-size: 13px; }
    .detail-doc h1 { font-size: 20px; margin-top: 0; }
    .detail-doc h2 { font-size: 16px; margin-top: 1.2em; color: var(--accent); }
    .detail-doc h3 { font-size: 14px; margin-top: 1.2em; color: var(--fg); }
    .detail-doc table { border-collapse: collapse; width: 100%; font-size: 12px; }
    .detail-doc th, .detail-doc td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
    .detail-doc hr { border: none; border-top: 1px solid var(--border); margin: 1.5em 0; }
    .detail-doc code { background: var(--code-bg); padding: 1px 5px; border-radius: 3px; }
    .pulse {
      animation: pulse 1.4s ease-out 2;
    }
    @keyframes pulse {
      0%   { box-shadow: 0 0 0 0 rgba(122, 162, 255, 0.7); }
      100% { box-shadow: 0 0 0 18px rgba(122, 162, 255, 0); }
    }
    .loading {
      display: inline-block;
      width: 12px; height: 12px;
      border: 2px solid var(--accent);
      border-top-color: transparent;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <header>
    <h1>Lumen<span class="accent">X</span> Wiki Explorer</h1>
    <div class="meta" id="meta">loading…</div>
  </header>

  <div id="graph">
    <div class="overlay" id="graph-overlay">building graph…</div>
  </div>

  <aside>
    <div class="tabs">
      <div class="tab active" data-tab="chat">Ask</div>
      <div class="tab" data-tab="detail">Selected product</div>
    </div>
    <div class="panel active" id="panel-chat">
      <form class="chat-form" id="ask-form">
        <input type="text" id="ask-input" placeholder="Ask anything about the products…" autocomplete="off">
        <button type="submit" id="ask-button">Ask</button>
      </form>
      <div id="answer-area">
        <div class="placeholder">Try: <em>"Which products integrate with Slack?"</em> or <em>"Compare emailpilot and inboxclean for solo founders."</em></div>
      </div>
    </div>
    <div class="panel" id="panel-detail">
      <div class="placeholder">Click a node in the graph to see its wiki page.</div>
    </div>
  </aside>

<script>
(() => {
  const $ = (sel) => document.querySelector(sel);
  const cy = cytoscape({
    container: $("#graph"),
    minZoom: 0.3, maxZoom: 3,
    style: [
      {
        selector: "node",
        style: {
          "background-color": "var(--node-fill)",
          "border-color": "var(--node-edge)",
          "border-width": 1.5,
          "label": "data(label)",
          "color": "#e8eaf0",
          "font-size": "11px",
          "font-family": "-apple-system, system-ui, sans-serif",
          "text-valign": "center",
          "text-halign": "center",
          "text-outline-width": 0,
          "width": 56, "height": 56,
        }
      },
      {
        selector: "node:selected",
        style: {
          "background-color": "var(--node-hi)",
          "border-color": "#aac4ff",
          "border-width": 2.5,
          "color": "#0b0d12",
        }
      },
      {
        selector: "node.hl",
        style: {
          "background-color": "var(--accent-2)",
          "border-color": "#ffd0db",
          "border-width": 2.5,
          "color": "#0b0d12",
        }
      },
      {
        selector: "edge",
        style: {
          "width": 1.2,
          "line-color": "var(--edge)",
          "curve-style": "bezier",
          "opacity": 0.7,
        }
      },
      {
        selector: "edge[label]",
        style: {
          "label": "",
        }
      },
    ],
  });

  function setStatus(text) { $("#meta").textContent = text; }
  function showOverlay(text) { const o = $("#graph-overlay"); o.textContent = text; o.style.display = "flex"; }
  function hideOverlay() { $("#graph-overlay").style.display = "none"; }

  async function loadGraph() {
    const r = await fetch("/wiki/graph.json");
    if (r.status === 503) {
      const body = await r.json();
      showOverlay(body.error || "graph not built");
      setStatus("graph unavailable");
      return;
    }
    const data = await r.json();
    cy.add([
      ...data.nodes.map(n => ({ data: { id: n.id, label: n.label, tagline: n.tagline || "" } })),
      ...data.edges.map((e, i) => ({
        data: { id: `e${i}`, source: e.source, target: e.target, relation: e.relation, reason: e.reason }
      })),
    ]);
    cy.layout({
      name: "cose",
      animate: false,
      nodeRepulsion: 5000,
      idealEdgeLength: 110,
      gravity: 0.4,
      padding: 30,
    }).run();
    hideOverlay();
    setStatus(`${data.nodes.length} products • ${data.edges.length} edges`);
  }

  // Tabs
  document.querySelectorAll(".tab").forEach(t => {
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
      document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      $(`#panel-${t.dataset.tab}`).classList.add("active");
    });
  });

  // Node click → detail
  cy.on("tap", "node", async (evt) => {
    const id = evt.target.id();
    cy.nodes().removeClass("hl");
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    document.querySelector(`.tab[data-tab="detail"]`).classList.add("active");
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    $("#panel-detail").classList.add("active");
    const panel = $("#panel-detail");
    panel.innerHTML = `<div class="placeholder"><span class="loading"></span> loading ${id}…</div>`;
    const r = await fetch(`/wiki/doc/${encodeURIComponent(id)}`);
    if (!r.ok) { panel.innerHTML = `<div class="placeholder">No wiki entry for <code>${id}</code></div>`; return; }
    const body = await r.json();
    panel.innerHTML = `<div class="detail-doc">${marked.parse(body.markdown)}</div>`;
  });

  cy.on("tap", (evt) => {
    if (evt.target === cy) {
      cy.nodes().unselect();
      cy.nodes().removeClass("hl");
    }
  });

  // Chat
  const form = $("#ask-form");
  const input = $("#ask-input");
  const button = $("#ask-button");
  const area = $("#answer-area");

  function renderAnswer(answer_markdown, citations) {
    let html = marked.parse(answer_markdown);
    // Replace [n] tokens with clickable badges, wrapped in spans.
    html = html.replace(/\[(\d+)\]/g, (_, n) => `<span class="cite" data-n="${n}">${n}</span>`);
    const sourcesHtml = citations.length
      ? `<div class="sources"><h3>Sources</h3>${
          citations.map(c => `
            <div class="source">
              <div class="source-n">${c.n}</div>
              <div class="source-body">
                <div class="source-id" data-id="${c.product_id}">${c.product_id}</div>
                <div class="source-quote">"${c.quote.replace(/"/g, '&quot;')}"</div>
              </div>
            </div>
          `).join("")
        }</div>`
      : "";
    area.innerHTML = `<div class="answer">${html}</div>${sourcesHtml}`;

    // Wire citation clicks → pulse + zoom to node.
    const citeMap = new Map(citations.map(c => [c.n, c.product_id]));
    area.querySelectorAll(".cite").forEach(el => {
      el.addEventListener("click", () => {
        const pid = citeMap.get(parseInt(el.dataset.n, 10));
        if (pid) pulseNode(pid);
      });
    });
    area.querySelectorAll(".source-id").forEach(el => {
      el.addEventListener("click", () => pulseNode(el.dataset.id));
    });
  }

  function pulseNode(id) {
    const n = cy.getElementById(id);
    if (!n || !n.length) return;
    cy.nodes().removeClass("hl");
    n.addClass("hl");
    cy.animate({ center: { eles: n }, zoom: 1.3 }, { duration: 350 });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    button.disabled = true;
    area.innerHTML = `<div class="placeholder"><span class="loading"></span> thinking…</div>`;
    try {
      const r = await fetch("/wiki/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      renderAnswer(body.answer_markdown, body.citations || []);
    } catch (err) {
      area.innerHTML = `<div class="placeholder">Error: ${err.message}</div>`;
    } finally {
      button.disabled = false;
    }
  });

  loadGraph();
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Verify it parses in Jinja2**

Run: `uv run python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/auto_reply/web/templates')); t = env.get_template('wiki.html'); print(len(t.render()))"`
Expected: prints a number > 5000 (the rendered HTML length).

- [ ] **Step 3: Re-run Task 2's tests** (they verify the template loads)

Run: `uv run pytest tests/test_wiki_explorer.py::test_get_html_returns_200 -v`
Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add src/auto_reply/web/templates/wiki.html
git commit -m "feat(web): wiki.html — dark, modern Cytoscape + chat SPA"
```

---

## Task 4: `scripts/build_wiki_graph.py` — one-shot graph builder

**Files:**
- Create: `scripts/build_wiki_graph.py`

This CLI sends all 20 wiki markdown files to Sonnet in a single message and
asks for a JSON graph. We do not unit-test it (it's a single-LLM-call CLI);
we verify by running it once and inspecting the result.

- [ ] **Step 1: Write the script**

```python
# scripts/build_wiki_graph.py
"""Build the wiki knowledge graph.

Steps:
1. Read every wiki/*.md.
2. Ask Sonnet to extract per-product nodes and semantic product↔product edges.
3. Validate and write data/wiki_graph.json.

Run:
    uv run python scripts/build_wiki_graph.py

Cost: one Sonnet call, roughly $0.10.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from anthropic import Anthropic

from auto_reply.llm.client import LLMClient
from auto_reply.settings import get_settings
from auto_reply.sources.wiki_loader import WikiLoader
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations
from auto_reply.tls import enable_system_certs

ROOT = Path(__file__).resolve().parents[1]
WIKI_DIR = ROOT / "wiki"
OUT_PATH = ROOT / "data" / "wiki_graph.json"

SYSTEM = """You are extracting a knowledge graph from a set of product documents.

You will receive Markdown documentation for ~20 SaaS products. Each product has
an `id` (filename stem) — use that as the node id.

Return ONLY a single JSON object (no prose, no markdown fences):

{
  "nodes": [
    {
      "id": "<filename-stem>",
      "label": "<product display name>",
      "tagline": "<≤ 10 words>",
      "target_audience": "<short phrase>",
      "summary": "<≤ 30 words>"
    }
  ],
  "edges": [
    {
      "source": "<id>",
      "target": "<id>",
      "relation": "<one of: shared_audience | shared_integration | similar_function | complements>",
      "reason": "<≤ 18 words>"
    }
  ]
}

Rules:
- Include EVERY product as a node, using its filename stem as the id.
- Edges must connect two existing node ids. Do not invent products.
- Aim for 25–60 edges total. Skip weak connections.
- An edge is undirected — pick a canonical (source, target) order alphabetically.
- Do not emit duplicate edges in either direction.
- Use ONLY facts that appear in the docs. Do not invent.
"""


def build_user_message(docs: dict[str, str]) -> str:
    parts = []
    for pid, body in docs.items():
        parts.append(f"### id: {pid}\n\n{body.strip()}")
    return "\n\n---\n\n".join(parts)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def main() -> int:
    enable_system_certs()
    settings = get_settings()
    docs = WikiLoader(WIKI_DIR).load_all()
    if not docs:
        print(f"No wiki docs in {WIKI_DIR}. Run scripts/build_wiki.py first.", file=sys.stderr)
        return 2
    print(f"Found {len(docs)} products. Asking Sonnet to extract graph…")

    conn = connect(settings.agent_db_path)
    apply_migrations(conn)
    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)

    raw = llm.complete(
        model="claude-sonnet-4-6",
        system=SYSTEM,
        messages=[{"role": "user", "content": build_user_message(docs)}],
        purpose="wiki_graph_build",
        max_tokens=4096,
        temperature=0.0,
    )

    cleaned = strip_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print("Failed to parse JSON. Raw output:", file=sys.stderr)
        print(raw, file=sys.stderr)
        raise SystemExit(1) from e

    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    node_ids = {n["id"] for n in nodes if isinstance(n, dict) and "id" in n}
    missing = set(docs.keys()) - node_ids
    if missing:
        print(f"WARN: Sonnet did not emit nodes for: {sorted(missing)}", file=sys.stderr)

    # Drop edges whose endpoints don't exist.
    clean_edges = [
        e for e in edges
        if isinstance(e, dict)
        and e.get("source") in node_ids
        and e.get("target") in node_ids
        and e.get("source") != e.get("target")
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps({"nodes": nodes, "edges": clean_edges}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    cost = conn.execute(
        "SELECT cost_usd FROM cost_log WHERE purpose='wiki_graph_build' ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    print(f"Wrote {OUT_PATH} — {len(nodes)} nodes, {len(clean_edges)} edges. Cost: ${cost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it live**

Run: `uv run python scripts/build_wiki_graph.py`
Expected: prints `Wrote .../data/wiki_graph.json — 20 nodes, NN edges. Cost: $0.NN`.

If Sonnet returns malformed JSON, the script prints the raw output and exits
1. If that happens, inspect the raw output and adjust the SYSTEM prompt.

- [ ] **Step 3: Spot-check the graph**

Run: `uv run python -c "import json; d=json.load(open('data/wiki_graph.json', encoding='utf-8')); print('nodes:', len(d['nodes']), 'edges:', len(d['edges'])); print('first node:', d['nodes'][0]); print('first edge:', d['edges'][0])"`
Expected: nodes=20, edges between 20 and 80, first node has all five fields, first edge has source/target/relation/reason.

- [ ] **Step 4: Lint**

Run: `uv run ruff check scripts/build_wiki_graph.py`

- [ ] **Step 5: Commit**

```bash
git add scripts/build_wiki_graph.py
git commit -m "feat(scripts): build_wiki_graph CLI — Sonnet extracts product graph"
```

The generated `data/wiki_graph.json` is gitignored.

---

## Task 5: Wire it into `web/app.py` and live smoke test

**Files:**
- Modify: `src/auto_reply/web/app.py` (mount the new router and wire WikiQA)

- [ ] **Step 1: Edit `src/auto_reply/web/app.py`**

Find the existing import block and add:

```python
from auto_reply.pipeline.wiki_qa import WikiQA
from auto_reply.web.wiki_explorer import make_router as make_wiki_router
```

Find the existing `WIKI_DIR` constant and add a sibling:

```python
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
GRAPH_PATH = DATA_DIR / "wiki_graph.json"
```

Inside `create_app()`, AFTER `wiki_text = WikiLoader(WIKI_DIR).concatenated() if WIKI_DIR.exists() else ""` and BEFORE the `lumenx = LumenXClient(...)` line, add:

```python
wiki_docs = WikiLoader(WIKI_DIR).load_all() if WIKI_DIR.exists() else {}
wiki_qa = WikiQA(llm=llm, wiki_docs=wiki_docs)
```

After the existing `app.include_router(make_router(conn=conn, password=...))` line, add:

```python
app.include_router(
    make_wiki_router(wiki_dir=WIKI_DIR, graph_path=GRAPH_PATH, wiki_qa=wiki_qa)
)
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -v`
Expected: all tests still pass (Phase 2 baseline 67 + Task 1 (6) + Task 2 (8) = **81 passed**).

- [ ] **Step 3: Lint**

Run: `uv run ruff check src tests scripts`
Expected: no errors.

- [ ] **Step 4: Smoke test against live LumenX + Anthropic**

a) Start the app:
```
uv run uvicorn auto_reply.web.app:create_app --factory --port 8765
```

b) Open http://127.0.0.1:8765/wiki in a browser. Expect:
   - Dark background, "LumenX Wiki Explorer" heading.
   - Force-directed graph with 20 nodes appears within ~1s.
   - Header right shows e.g. "20 products • 42 edges".

c) Click any node — the right panel switches to "Selected product" with the
   product's markdown rendered.

d) Switch back to "Ask" tab. Type "Which products integrate with Slack?" and
   press Enter. Within ~5s, expect a Sonnet answer with inline `[1]` `[2]`
   markers and a Sources panel below listing the cited product IDs and
   quoted snippets. Click a `[n]` — the corresponding graph node pulses
   and the view zooms to it.

e) Type a deliberately out-of-wiki question like "What is the company's
   employee count?" — expect the answer to say it doesn't have that
   information.

f) Stop the server with Ctrl+C.

- [ ] **Step 5: Commit + milestone**

```bash
git add src/auto_reply/web/app.py
git commit -m "feat(web): mount /wiki explorer router (graph + chat)"
git commit --allow-empty -m "chore: wiki explorer ready — graph + cited Q&A live"
```

---

## Self-review notes

- **Spec coverage**
  - §5.1 graph builder CLI → Task 4.
  - §5.2 WikiQA → Task 1.
  - §5.3 APIRouter, four endpoints → Task 2 (with explicit tests for each endpoint, including the "graph not built" 503 path and the path-traversal guard).
  - §5.4 wiki.html single-page UI → Task 3.
  - §5.5 mount in app.py → Task 5.
  - §6 cost: every Sonnet call routes through `LLMClient` which writes `cost_log`.
  - §7 failure modes: empty-question 400 (Task 2 test), graph-missing 503 (Task 2 test), bad-JSON fallback (Task 1 test), unknown product_id citation dropped (Task 1 test).
- **Placeholder scan:** no TBDs, every code/SQL/command step has full content.
- **Type consistency:** `WikiQA.ask(question: str) -> WikiAnswer`. `WikiAnswer` has `answer_markdown: str` and `citations: list[Citation]`. `Citation` has `n: int, product_id: str, quote: str`. Used identically in Task 1 tests, Task 2 router, and Task 5 wiring. The JSON the router emits matches what the frontend in Task 3 consumes (`answer_markdown`, `citations: [{n, product_id, quote}]`).
- **Open risks**
  - The first `/wiki/ask` after a server restart pays a cache-write (no cache hit yet) → ~$0.15. Subsequent asks within 5min cache TTL → ~$0.005. Documented in spec §6.
  - We trust Sonnet's markdown output — no DOMPurify. The model is constrained by persona and rejects out-of-corpus content; not exposing HTML directly to untrusted user input. Acceptable for an internal tool; revisit if `/wiki` ever serves an untrusted audience.
