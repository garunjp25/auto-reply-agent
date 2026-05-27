# Wiki Explorer — Design Spec

**Date:** 2026-05-27
**Status:** Approved for planning
**Owner:** Arun Jayaprakash

## 1. Purpose

A standalone, beautiful web page at `/wiki` that lets anyone (no auth)
explore the 20-product LumenX wiki as an interactive knowledge graph **and**
ask natural-language questions answered with inline source citations.

This is a side feature of the auto-reply project — it sits alongside the
agent and dashboard, sharing the same `wiki/*.md` corpus. It is NOT part of
the auto-reply pipeline.

## 2. Success criteria

- Pan/zoom/click an interactive force-directed graph of 20 product nodes,
  with semantic edges (relation type + reason on hover).
- Click any node → see that product's wiki content rendered as markdown.
- Type a question → receive a Sonnet answer with inline `[1]`, `[2]` markers;
  click a marker → the cited product node pulses on the graph.
- "Sources" panel under each answer lists the cited product IDs with quoted
  snippets.
- Loads in under 2 seconds; runs on commodity laptop without lag at 20 nodes.
- Per-question cost ≤ $0.01 (prompt caching of wiki body).

## 3. Non-goals

- No auth or per-user state.
- No graph editing — graph is read-only, derived from the wiki.
- No conversation history — every question is one-shot.
- No "regenerate graph" UI button — operator re-runs the CLI when wiki
  changes.
- No multi-language support.

## 4. Architecture

```
┌──────────────────── browser ────────────────────┐
│  /wiki (single-page, no auth)                   │
│  ├─ Cytoscape.js (left,  ~60% width)            │
│  └─ Side panel  (right, ~40% width)             │
│     ├─ Chat: question → answer w/ [1] markers   │
│     │   + sources panel below                   │
│     └─ Node detail: render selected product .md │
└──────────────────────────┬──────────────────────┘
                           │
┌──────────────────────────┴────────── FastAPI ───┐
│  GET  /wiki                   → wiki.html       │
│  GET  /wiki/graph.json        → graph data      │
│  GET  /wiki/doc/{product_id}  → markdown        │
│  POST /wiki/ask  {question}   → answer+sources  │
└─────────────────────────────────────────────────┘
                           │
                  data/wiki_graph.json
                  (built once by Sonnet via
                  scripts/build_wiki_graph.py)
```

## 5. Components

### 5.1 `scripts/build_wiki_graph.py` (one-shot CLI)

Sends all 20 `wiki/*.md` as a single Sonnet message, requests a JSON
response of:

```json
{
  "nodes": [
    {
      "id": "emailpilot",
      "label": "EmailPilot",
      "tagline": "AI email-draft tool",
      "target_audience": "founders, consultants",
      "summary": "≤ 30 words"
    }
  ],
  "edges": [
    {
      "source": "emailpilot",
      "target": "inboxclean",
      "relation": "similar_audience",
      "reason": "Both target inbox-heavy professionals"
    }
  ]
}
```

Validates the JSON, writes to `data/wiki_graph.json` (gitignored). Cost
logged with `purpose='wiki_graph_build'`.

Re-run whenever wiki changes (after `build_wiki.py`).

### 5.2 `src/auto_reply/pipeline/wiki_qa.py`

`WikiQA(llm, wiki_text)` with method `ask(question: str) -> WikiAnswer`,
where:

```python
@dataclass(frozen=True)
class Citation:
    n: int               # 1-based footnote number
    product_id: str
    quote: str           # short snippet (≤ 240 chars)

@dataclass(frozen=True)
class WikiAnswer:
    answer_markdown: str # contains [1], [2] etc.
    citations: list[Citation]
```

Prompt:
- System block 1 (persona): "Answer using ONLY the wiki. If the answer is not
  in the wiki, say so. Use inline `[1]`, `[2]` markers tied to the `citations`
  array. Each citation cites a single product_id with a quote from that
  product's doc."
- System block 2 (cache_control:ephemeral): the full concatenated wiki.
- User message: the question + "Reply ONLY as a JSON object …"

Parses JSON, validates each citation's `product_id` exists in the wiki dict.
Falls back to a polite "I don't have that information" answer if Sonnet
fails JSON validation. Cost-logged with `purpose='wiki_qa'`.

### 5.3 `src/auto_reply/web/wiki_explorer.py`

FastAPI APIRouter, **no auth**, prefix `/wiki`. Endpoints:

- `GET /wiki` — returns `wiki.html` rendered with no data (graph fetched
  client-side via XHR).
- `GET /wiki/graph.json` — reads `data/wiki_graph.json`. Returns 503 with a
  helpful message if not built yet.
- `GET /wiki/doc/{product_id}` — returns `{"product_id": "...",
  "markdown": "..."}` from the corresponding `wiki/<id>.md`. 404 if missing.
- `POST /wiki/ask` — body `{"question": "..."}` → calls `WikiQA.ask` →
  returns `{"answer_markdown": "...", "citations": [{"n":1, ...}, ...]}`.
  Returns 400 if question is empty.

The router builds its `WikiQA` once at module load (wiki text concatenated
from `WikiLoader`); endpoints share that instance.

### 5.4 `src/auto_reply/web/templates/wiki.html`

Single self-contained HTML page. **Aesthetic: dark, modern, generous
whitespace, sans-serif, subtle gradients, no emoji.**

Layout (CSS grid):

```
┌─────────────────────────────────────────────────────┐
│  header bar — "LumenX Wiki Explorer"  (left)        │
│                  20 products • <N> edges (right)    │
├──────────────────────────────────┬──────────────────┤
│                                  │  CHAT            │
│         CYTOSCAPE                │  ┌────────────┐  │
│         GRAPH                    │  │ ask…       │  │
│                                  │  └────────────┘  │
│                                  │                  │
│                                  │  ANSWER          │
│                                  │  …with [1] [2]   │
│                                  │                  │
│                                  │  SOURCES         │
│                                  │  [1] emailpilot  │
│                                  │      "quote…"    │
│                                  │  [2] invoiceflow │
│                                  │                  │
│                                  │  ─ or ─          │
│                                  │  PRODUCT DETAIL  │
│                                  │  (when node      │
│                                  │  clicked)        │
└──────────────────────────────────┴──────────────────┘
```

**Interactions:**
- On load: fetch `/wiki/graph.json`, render Cytoscape force-directed (cose layout).
- Hover node → highlight, dim others, show tooltip with `tagline`.
- Click node → fetch `/wiki/doc/{id}` → render markdown in side panel
  (replace any current chat detail). Click background to clear.
- Submit chat → POST `/wiki/ask` → render answer markdown; each `[n]` becomes
  a clickable pill → on click, focus + pulse animation on the cited node.
- Sources panel lists each citation with a quote and a "jump to node" link.

Dependencies (CDN, pinned versions):
- `cytoscape@3.30.x`
- `marked@13.x` (markdown → HTML; we set `breaks:true, gfm:true`; no DOMPurify
  — we trust the model's output since we control the persona; if XSS is a
  concern later, add DOMPurify)
- system fonts only

### 5.5 `web/app.py` (modify)

Mount the new router. No auth wrap (public).

## 6. Cost model

- Graph build: ~$0.10 one-shot (Sonnet, ~50K input tokens, ~3K output).
- Per ask: prompt-cached wiki block. First call after cache miss: ~$0.15.
  Subsequent calls within 5min cache TTL: ~$0.005. Average ~$0.01.
- All logged to `cost_log` with `purpose='wiki_graph_build'` or `'wiki_qa'`.

## 7. Failure modes

- `data/wiki_graph.json` missing → `/wiki/graph.json` returns 503 with body
  `{"error":"graph not built; run scripts/build_wiki_graph.py"}`. The page
  shows an empty graph state with that message.
- Sonnet returns invalid JSON for an ask → return a polite "I had trouble
  understanding that. Try rephrasing?" with zero citations.
- Sonnet cites a non-existent `product_id` → drop that citation, keep the
  rest, log a warning.
- Empty question → 400.

## 8. Storage

- `data/wiki_graph.json` — flat file, gitignored (regenerable).
- `cost_log` rows for every Sonnet call.
- No new SQLite tables.

## 9. Phasing

This is a single small feature; implement all of it in one plan (Phase
"Wiki Explorer" — out-of-band from the auto-reply phases 0–6).

Tasks:
1. `scripts/build_wiki_graph.py` + run it live.
2. `WikiQA` + unit tests.
3. `wiki_explorer.py` router + tests.
4. `wiki.html` template.
5. Mount in `web/app.py` + live smoke test.

## 10. Open questions

None. The two markdown rendering library choices are settled (`marked`);
XSS posture is documented; auth is settled (none).
