from __future__ import annotations

from pathlib import Path


class WikiLoader:
    """Reads wiki/*.md files into memory.

    Phase 2 uses the full concatenated wiki as a cached system block (Sonnet's
    200K context comfortably holds ~20 products at ~1500 words each).
    """

    def __init__(self, wiki_dir: Path) -> None:
        self._wiki_dir = Path(wiki_dir)

    def load_all(self) -> dict[str, str]:
        if not self._wiki_dir.exists():
            raise FileNotFoundError(f"wiki dir not found: {self._wiki_dir}")
        out: dict[str, str] = {}
        for path in sorted(self._wiki_dir.glob("*.md")):
            out[path.stem] = path.read_text(encoding="utf-8")
        return out

    def concatenated(self) -> str:
        docs = self.load_all() if self._wiki_dir.exists() else {}
        if not docs:
            return ""
        parts: list[str] = []
        for product_id, body in docs.items():
            parts.append(f"## Product: {product_id}\n\n{body.strip()}")
        return "\n\n---\n\n".join(parts)
