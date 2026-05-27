# LumenX Auto-Reply Agent

An LLM-powered auto-reply service for the LumenX customer-support demo
platform. Drafts replies with Claude, scores each draft with a small trained
neural network (ConfidenceNet), and either auto-sends high-confidence replies
or queues low-confidence ones for human review through a web dashboard.

> **Status:** design phase. See
> [`docs/superpowers/specs/2026-05-27-auto-reply-agent-design.md`](docs/superpowers/specs/2026-05-27-auto-reply-agent-design.md)
> for the full spec.

## Why

LumenX (https://lumenx-demo.up.railway.app) exposes 20 SaaS products and an
admin inbox of customer conversations. Replying manually doesn't scale. We
want an agent that drafts every reply, learns from human edits, and earns
trust to auto-send the easy ones — without ever hallucinating on pricing or
refund policy.

## Architecture (one-pager)

```
incoming msg ──► Intent Router ──► Context Builder ──► LLM Draft ──► Confidence Net ──► Router
                  (Haiku 4.5)        assembles            (Sonnet 4.6)   (PyTorch MLP)    │
                                     all sources                                          │
                                                                              high ──► auto-send
                                                                              low  ──► human review
```

**Sources fed into Context Builder:**
- Products JSON from LumenX
- Per-customer past conversations
- Global past replies (feedback log)
- LLM Wiki (Karpathy-style markdown + FAISS index)

**Safety:** pricing and refund intents always go to human review.

See `architecture.jpg` and `confidence-net.jpg` for the original sketches.

## Phased delivery

| Phase | Goal |
|---|---|
| 0 | Scaffold: FastAPI, SQLite, cost-logging wrapper |
| 1 | LLM Wiki + Intent Router (read-only) |
| 2 | Draft pipeline, queue-only (no auto-send) |
| 3 | Feedback loop + cost dashboard |
| 4 | ConfidenceNet v0, trained on synthetic data |
| 5 | Auto-send + safety gate, deploy to Railway |
| 6 | ConfidenceNet v1, retrained on real human labels |

Detailed phase plans live in `docs/superpowers/plans/` (added as each phase
begins).

## Repository layout (target)

```
src/auto_reply/
  pipeline/       Poller, IntentRouter, ContextBuilder, Drafter, ConfidenceNet, Router
  sources/        LumenX client, wiki builder, feedback retrieval
  store/          SQLite models, migrations
  web/            FastAPI app + HTMX dashboard
  training/       Synthetic data generator, MLP training
tests/
docs/
  superpowers/specs/   Design specs
  superpowers/plans/   Per-phase implementation plans
wiki/             Generated product markdown + FAISS index
data/             agent.db (gitignored)
```

## Tech stack

Python 3.11+ · FastAPI · PyTorch · FAISS · SQLite · Anthropic SDK
(`claude-haiku-4-5-20251001` for routing, `claude-sonnet-4-6` for drafts) ·
HTMX + Jinja2 for the dashboard.

## Running it (placeholder — populated in Phase 0)

```bash
# install
uv sync

# env
cp .env.example .env   # fill in ANTHROPIC_API_KEY, LUMENX_ADMIN_TOKEN, etc.

# run
uvicorn auto_reply.web.app:app --reload
```

## References

- LumenX repo: https://github.com/VizuaraAI/lumenx
- LumenX deployed: https://lumenx-demo.up.railway.app
- Admin API contract: [`api_description.txt`](api_description.txt)
- LLM Wiki inspiration: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
