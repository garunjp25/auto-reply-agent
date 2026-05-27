# Auto-Reply Agent for LumenX — Design Spec

**Date:** 2026-05-27
**Status:** Approved for planning
**Owner:** Arun Jayaprakash

## 1. Purpose

Build an LLM auto-reply agent that drafts customer-support replies for the LumenX
demo platform (https://lumenx-demo.up.railway.app). Drafts are scored by a small
trained neural network (ConfidenceNet); high-confidence drafts auto-send,
low-confidence drafts queue for a human reviewer. The agent never modifies
LumenX itself — it integrates only through LumenX's admin API.

## 2. Success criteria

- End-to-end: a customer message on LumenX produces an agent draft within ~15s.
- ≥70% of non-sensitive drafts can be auto-sent at threshold 0.85 without edits
  after 2 weeks of human-in-the-loop training.
- Pricing and refund replies never auto-send.
- Per-reply cost (tokens × price) is visible in the dashboard for every reply.
- Re-running the agent is cheap: prompt caching for static system prompt and
  products section.

## 3. Non-goals

- No changes to the LumenX repository.
- No multi-tenant support; single LumenX deployment, single admin token.
- No voice / multimodal input.
- No customer-facing UI (customers continue using `/chat` on LumenX).

## 4. Architecture

```
┌────────────── auto-reply-agent (Python FastAPI service) ──────────────┐
│                                                                       │
│  Poller ──► IntentRouter ──► ContextBuilder ──► Drafter ──► ConfNet ──┤
│   (10s)      (Haiku 4.5)     (assembles)       (Sonnet)    (MLP, 0-1) │
│                                                                       │
│              Sources                       Router                     │
│              ├ Products JSON               ├ sensitive → review       │
│              ├ Per-customer history        ├ conf ≥ thr → auto-send   │
│              ├ Global past threads         └ else → review            │
│              ├ LLM Wiki (md + FAISS)                                  │
│              └ Feedback log                                           │
│                                                                       │
│  SQLite (./data/agent.db)   Dashboard at /agent (HTMX)                │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
       ▲ GET inbox/threads/products/export        ▼ POST /threads/{id}/reply
                          LumenX admin API
```

## 5. Components

### 5.1 Poller
Async loop, every 10s calls `/api/admin/inbox?since=<last_server_time>`.
For each entry with `awaiting_admin=true`, enqueues a `DraftJob(thread_id)`.
`last_server_time` persisted in SQLite (`threads_seen`).
Idempotent: if a draft already exists for `(thread_id, last_customer_msg_id)`,
skip.

### 5.2 IntentRouter
- Model: `claude-haiku-4-5-20251001`.
- Output: `{intent: greeting|pricing|refund|technical|feature_question|integration|other, sensitive: bool}`.
- `pricing` and `refund` are always `sensitive=true`.
- Short-circuit: `greeting` and `other` use a templated reply and skip the Drafter
  entirely (still recorded for cost accounting, zero output tokens).

### 5.3 ContextBuilder
Assembles the Drafter prompt:

1. **System** (cached): persona, anti-hallucination rules, format rules.
2. **Products section** (cached): full products JSON from `/api/admin/products`,
   refreshed nightly.
3. **LLM Wiki retrieval**: top-3 FAISS chunks for the customer message.
4. **Per-customer history**: full message list of the current thread, plus a
   one-paragraph LLM-generated summary of any other threads from the same
   `username`.
5. **Global retrieval**: top-3 similar `(customer_msg, final_reply)` pairs from
   the feedback log where `thumb=+1` or `edit_distance < 0.2`.
6. **User turn**: the latest customer message.

### 5.4 Drafter
- Model: `claude-sonnet-4-6`.
- Prompt caching enabled on system + products section.
- Output: plain reply text + a self-rated `internal_confidence` (used as one
  feature in ConfidenceNet, not as the final score).

### 5.5 ConfidenceNet
- PyTorch MLP: input ~16-dim feature vector → 64 → 64 → 1 (sigmoid).
- Loss: BCE. Optimizer: Adam, lr 1e-3.
- Features:
  - `len_ratio` (draft tokens / customer-msg tokens, log-scaled)
  - `intent_onehot` (7 dims)
  - `sensitive_flag`
  - `wiki_hit_count` (0–3)
  - `feedback_hit_count` (0–3)
  - `top_feedback_similarity` (cosine)
  - `draft_context_overlap` (cosine of draft embedding vs. retrieved chunks)
  - `has_numeric_claim` (regex on currency/percent/duration)
  - `has_policy_claim` (regex on refund/cancel/sla keywords)
  - `internal_confidence` (Drafter self-rating)

### 5.6 Router
```
if sensitive:                       → queue_for_review
elif confidence ≥ THRESHOLD:        → auto_send
else:                               → queue_for_review
```
THRESHOLD is an env var (default `0.85`). A kill-switch env var
`AUTO_SEND_ENABLED=false` forces everything to review.

### 5.7 LLM Wiki
- Built from `/api/admin/products` by a build script:
  one `wiki/<product_id>.md` per product, plus `wiki/_policies.md` for company-wide
  policies (refund window, free trial, discounts).
- Generated by Sonnet from the raw product JSON using a Karpathy-style prompt
  (see: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) —
  one structured doc per product, written for an LLM reader.
- Chunked (~400 tokens) and embedded with `text-embedding-3-small`. Index
  persisted via FAISS on disk.
- Nightly cron refresh.

### 5.8 Feedback log
Every interaction writes one row. The reviewer's action on the dashboard
(approve / edit-and-send / reject) determines the label:
- approve as-is, no edit → `label=1`
- edit-then-send with `edit_distance < 0.2` → `label=1`
- edit-then-send with `edit_distance ≥ 0.2` → `label=0`
- reject → `label=0`
- thumb-down on a sent reply → flips label to `0`

### 5.9 Dashboard (`/agent`)
- Auth: single env-var password, cookie session.
- Tabs:
  - **Queue** — drafts awaiting review, editable textarea, approve / edit-and-send / reject buttons, shows intent, confidence, and an expandable "Show context" panel rendering the exact prompt sent to Sonnet.
  - **Activity** — sent replies, filterable by intent / auto-sent / date. Expandable context per row.
  - **Costs** — per-day spend chart, per-model + per-intent breakdown, total tokens in/out incl. cache reads/writes.

## 6. Storage schema (SQLite)

```sql
CREATE TABLE threads_seen (
  thread_id TEXT PRIMARY KEY,
  last_msg_id TEXT,
  last_seen_at DATETIME
);

CREATE TABLE drafts (
  id INTEGER PRIMARY KEY,
  thread_id TEXT, customer_msg TEXT, draft_text TEXT,
  intent TEXT, sensitive INTEGER, confidence REAL,
  context_json TEXT,                  -- full prompt for replay/audit
  status TEXT,                        -- pending|sent|rejected|edited
  auto_sent INTEGER,
  created_at DATETIME
);

CREATE TABLE sent_replies (
  draft_id INTEGER PRIMARY KEY REFERENCES drafts(id),
  final_text TEXT, edit_distance REAL, sent_at DATETIME
);

CREATE TABLE feedback (
  draft_id INTEGER REFERENCES drafts(id),
  thumb INTEGER, notes TEXT, created_at DATETIME
);

CREATE TABLE training_labels (
  draft_id INTEGER PRIMARY KEY REFERENCES drafts(id),
  label INTEGER, source TEXT,         -- synthetic|human
  features_json TEXT
);

CREATE TABLE cost_log (
  id INTEGER PRIMARY KEY,
  call_id TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER,
  cache_read_tokens INTEGER, cache_write_tokens INTEGER,
  cost_usd REAL,
  purpose TEXT,                       -- intent|draft|wiki_build|embed|judge
  draft_id INTEGER,
  at DATETIME
);

CREATE TABLE wiki_index (
  product_id TEXT, chunk_id INTEGER,
  text TEXT, embedding BLOB,
  PRIMARY KEY (product_id, chunk_id)
);
```

## 7. ConfidenceNet training-data bootstrap

**Phase A — synthetic (target ~500 labels):**
- For each of the 100 demo threads from `/api/admin/export`, take the customer's
  last message and the admin's final reply. Treat that pair as `label=1`.
- For ~250 of them, ask Claude to generate a *plausibly-wrong* alternative
  reply (mispriced, wrong product, refund hallucination). Treat as `label=0`.
- For ~150, generate edge cases: half-correct, vague, overly verbose. Have
  Claude rate them as judge; bucket to 0/1 by threshold.
- Featurize, train, hold out 20% for eval.

**Phase B — real (target ~100 labels):**
- Use approve/edit/reject signals from the dashboard. Retrain weekly via cron
  once `count(training_labels where source='human') >= 100`.
- Compare v1 vs v0 on a held-out human-only set; promote v1 if AUC improves.

## 8. Anti-hallucination policy

System prompt explicitly says:
- "If you do not know a specific price, refund window, or SLA, say: *I don't
  have that information handy — let me check with the team and get back to you.*"
- "Never invent product names, integrations, or features not in the provided
  product cards."
- Pricing/refund intents are always queued for review regardless of confidence.

## 9. Cost controls

- Prompt caching on the largest static blocks (system prompt + products).
- Templated short-circuit for `greeting` / `other` (no Sonnet call).
- Daily spend cap env var; when exceeded, agent pauses and dashboard shows a
  red banner.
- All API calls logged to `cost_log` for per-reply attribution.

## 10. Deployment

- Single Railway service, region `asia-southeast1` (same as LumenX).
- Volume mounted at `/data` for `agent.db` and `wiki/` + FAISS index.
- Env: `ANTHROPIC_API_KEY`, `LUMENX_ADMIN_TOKEN`, `LUMENX_BASE`,
  `AGENT_DASHBOARD_PASSWORD`, `THRESHOLD`, `AUTO_SEND_ENABLED`,
  `DAILY_SPEND_CAP_USD`.

## 11. Phased delivery

| Phase | Goal | Deliverable |
|---|---|---|
| 0 — Scaffold | Repo skeleton | FastAPI app, SQLite migrations, settings, Anthropic cost-logging wrapper |
| 1 — Wiki + IntentRouter | Read-only knowledge | `wiki/*.md` generator, FAISS index, intent classifier + 30-msg eval set |
| 2 — Draft pipeline (no auto-send) | Producer-only | Poller + ContextBuilder + Drafter. Queue tab works. |
| 3 — Feedback + cost view | Close the loop | Approve/edit/reject writes `feedback`+`training_labels`. Activity + Costs tabs. |
| 4 — ConfidenceNet v0 (synthetic) | Train MLP | Synthetic generator, training notebook, wired into Router (auto-send still disabled). |
| 5 — Auto-send + safety gate | Go live | Threshold knob, sensitive hard-gate, kill-switch, rate limit, Railway deploy. |
| 6 — ConfidenceNet v1 (real labels) | Learn from team | Weekly retrain cron, A/B vs v0, promote on AUC win. |

Each phase ships an observable improvement and can be paused on.

## 12. Open questions

None at design time. Implementation-level decisions (e.g. FAISS chunk size,
embedding model fallback) will be made in the per-phase plan documents.

## 13. References

- LumenX repo: https://github.com/VizuaraAI/lumenx
- LumenX deployment: https://lumenx-demo.up.railway.app
- LLM Wiki gist (Karpathy): https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- API contract: `api_description.txt` in this repo
- Architecture sketches: `architecture.jpg`, `confidence-net.jpg`
