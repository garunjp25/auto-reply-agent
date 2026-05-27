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
