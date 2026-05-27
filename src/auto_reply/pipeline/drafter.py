from __future__ import annotations

from dataclasses import dataclass

from auto_reply.llm.client import LLMClient
from auto_reply.pipeline.context_builder import DraftContext

DRAFT_MODEL = "claude-sonnet-4-6"


@dataclass
class Drafter:
    """Produces a draft reply from a DraftContext via Sonnet, cost-logged."""

    llm: LLMClient
    model: str = DRAFT_MODEL

    def draft(self, ctx: DraftContext, *, max_tokens: int = 800) -> str:
        return self.llm.complete(
            model=self.model,
            system=ctx.system_blocks,
            messages=ctx.messages,
            purpose="draft",
            max_tokens=max_tokens,
        )
