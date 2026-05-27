"""Fetch live LumenX snapshots and write them to tests/fixtures/.

Run manually whenever LumenX product data changes:
    uv run python scripts/refresh_fixtures.py
"""
import json
from pathlib import Path

from auto_reply.settings import get_settings
from auto_reply.sources.lumenx import LumenXClient
from auto_reply.tls import enable_system_certs

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main() -> None:
    enable_system_certs()
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    with LumenXClient(settings.lumenx_base, settings.lumenx_admin_token) as client:
        products = client.get_products()
        export = client.get_export()

    (FIXTURE_DIR / "lumenx_products.json").write_text(
        json.dumps(products, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (FIXTURE_DIR / "lumenx_export.json").write_text(
        json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote products + export to {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
