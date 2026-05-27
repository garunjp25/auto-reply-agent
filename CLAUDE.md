# CLAUDE.md — Auto-Reply Agent for LumenX

Project-scoped instructions. Loaded automatically into every Claude Code session
in this directory.

## What this project is

A standalone Python (FastAPI) service that drafts customer-support replies for
the LumenX demo platform (https://lumenx-demo.up.railway.app), scores each draft
with a small PyTorch MLP (ConfidenceNet), and either auto-sends or queues for
human review. The agent integrates with LumenX only through its admin HTTP API —
**never modify the LumenX repo from this project.**

Full design: `docs/superpowers/specs/2026-05-27-auto-reply-agent-design.md`.

## Working agreements

- **Phased delivery.** Implement one phase at a time (see spec §11). Do not jump
  ahead. Each phase ends with a working, observable improvement.
- **Spec → plan → code.** Before any phase's code, write a per-phase
  implementation plan under `docs/superpowers/plans/`. Use the
  `superpowers:writing-plans` skill.
- **Don't touch LumenX.** This repo only consumes LumenX's admin API. If a
  feature seems to require LumenX changes, surface that and stop.
- **Cost is a feature.** Every Anthropic call must go through the cost-logging
  wrapper and write a row to `cost_log`. No bare `anthropic.messages.create`
  calls in business code.
- **Prompt caching is default.** Static system prompt + products JSON go in
  cache_control blocks.
- **Safety hard-gates win.** Pricing and refund intents never auto-send,
  regardless of confidence. Encode this at the Router level, not the prompt.
- **No hallucinated specifics.** System prompt must instruct the model to say
  "I don't have that information handy" rather than guess on pricing, refund,
  SLA, or integration availability.

## Stack

- Python 3.11+, FastAPI, pydantic-settings
- SQLite via `sqlalchemy` or `sqlite3` (decide in Phase 0 plan)
- PyTorch for ConfidenceNet
- FAISS (cpu) for LLM Wiki retrieval
- `anthropic` SDK for Claude (use `claude-haiku-4-5-20251001` for intent,
  `claude-sonnet-4-6` for drafts). When building Claude API code, invoke the
  `claude-api` skill.
- HTMX + Jinja2 for the dashboard (no SPA)

## Conventions

- `src/auto_reply/` — package root
- `src/auto_reply/pipeline/` — Poller, IntentRouter, ContextBuilder, Drafter,
  ConfidenceNet, Router (one module each)
- `src/auto_reply/sources/` — LumenX client, wiki, feedback retrieval
- `src/auto_reply/store/` — SQLite models, migrations
- `src/auto_reply/web/` — FastAPI app + dashboard templates
- `src/auto_reply/training/` — synthetic data gen + MLP training
- `tests/` — pytest. Integration tests hit a recorded LumenX export fixture,
  not the live API.
- One module per component. If a file goes past ~250 lines, split it.

## Secrets

Never commit the LumenX admin token or the Anthropic key. Use `.env` locally
and Railway env vars in prod. `.env` is in `.gitignore`.

## When in doubt

- For complex multi-step work: use `superpowers:writing-plans`, then
  `superpowers:executing-plans` or `superpowers:subagent-driven-development`.
- For Claude API code: use `claude-api`.
- For UI work on the dashboard: use `frontend-design`.
- For any bug: use `superpowers:systematic-debugging` before proposing a fix.
- Before claiming "done": use `superpowers:verification-before-completion`.
