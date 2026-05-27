"""Build the wiki knowledge graph.

Reads every wiki/*.md, asks Sonnet to extract product nodes and semantic
product↔product edges, writes data/wiki_graph.json.

    uv run python scripts/build_wiki_graph.py

Cost: roughly $0.10 per run.
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
    print(f"Found {len(docs)} products. Asking Sonnet to extract graph...")

    conn = connect(settings.agent_db_path)
    apply_migrations(conn)
    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)

    raw = llm.complete(
        model="claude-sonnet-4-6",
        system=SYSTEM,
        messages=[{"role": "user", "content": build_user_message(docs)}],
        purpose="wiki_graph_build",
        max_tokens=8192,
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
    print(f"Wrote {OUT_PATH} - {len(nodes)} nodes, {len(clean_edges)} edges. Cost: ${cost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
