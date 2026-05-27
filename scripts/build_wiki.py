"""Build the LLM Wiki end-to-end.

Steps:
1. Fetch products from LumenX.
2. For each product, ask Sonnet to author wiki/<id>.md.

Embeddings/RAG are intentionally skipped for the current 20-product corpus —
the whole wiki fits in Sonnet's context. WikiStore stays in place for future
scale, but no chunks are persisted by this script.

Run:
    uv run python scripts/build_wiki.py
"""
from __future__ import annotations

from pathlib import Path

from anthropic import Anthropic

from auto_reply.llm.client import LLMClient
from auto_reply.tls import enable_system_certs
from auto_reply.settings import get_settings
from auto_reply.sources.lumenx import LumenXClient
from auto_reply.sources.wiki_builder import WikiBuilder
from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations

WIKI_DIR = Path(__file__).resolve().parents[1] / "wiki"


def main() -> None:
    enable_system_certs()
    settings = get_settings()
    conn = connect(settings.agent_db_path)
    apply_migrations(conn)

    sdk = Anthropic(api_key=settings.anthropic_api_key)
    llm = LLMClient(sdk=sdk, conn=conn)

    with LumenXClient(settings.lumenx_base, settings.lumenx_admin_token) as lx:
        payload = lx.get_products()

    products = payload.get("products", payload if isinstance(payload, list) else [])
    builder = WikiBuilder(llm=llm, wiki_dir=WIKI_DIR, conn=conn)  # no embedder

    for i, product in enumerate(products, start=1):
        pid = product.get("id", "<unknown>")
        print(f"[{i}/{len(products)}] {pid} ...")
        builder.build_one(product)

    total_cost = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_log WHERE purpose='wiki_build'"
    ).fetchone()[0]
    print(f"Done. Wrote {len(products)} docs to {WIKI_DIR}. Total cost: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
