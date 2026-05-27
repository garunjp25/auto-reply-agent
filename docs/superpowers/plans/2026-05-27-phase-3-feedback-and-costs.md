# Phase 3 Plan — Feedback Loop + Cost Dashboard

**Date:** 2026-05-27  
**Status:** Ready to implement  
**Depends on:** Phase 2 complete (84 tests passing), IntentRouter v2 (88 tests passing)

---

## Goal

Close the human-in-the-loop cycle: reviewers can approve, edit, or reject drafts
from the dashboard. Every action writes `feedback` + `training_labels` rows.
Two new dashboard tabs — Activity and Costs — make the agent observable.
Per-customer cross-thread summary added to ContextBuilder (deferred from Phase 2).

---

## Deliverables

| # | Deliverable | File(s) |
|---|---|---|
| 1 | Approve / Edit / Reject endpoints | `web/app.py` + `web/templates/queue.html` |
| 2 | `feedback` + `training_labels` writes | `pipeline/orchestrator.py` or new `store/feedback.py` |
| 3 | Activity tab | `web/templates/activity.html` + GET `/agent/activity` |
| 4 | Costs tab | `web/templates/costs.html` + GET `/agent/costs` |
| 5 | Per-customer cross-thread summary | `pipeline/context_builder.py` |
| 6 | Tests (target: ~110 total) | `tests/test_feedback.py`, `tests/test_dashboard_tabs.py` |

---

## Task Breakdown

### Task 1 — Feedback endpoints (web layer)

Add three POST routes behind HTTP Basic auth:

```
POST /agent/drafts/{draft_id}/approve
POST /agent/drafts/{draft_id}/edit      body: {"reply": "<edited text>"}
POST /agent/drafts/{draft_id}/reject
```

Each endpoint:
1. Validates `draft_id` exists and is in `status=pending`.
2. Writes a `feedback` row (`draft_id`, `action`, `edited_reply`, `ts`).
3. Writes a `training_labels` row (`draft_id`, `label`: 1/0.5/0 for approve/edit/reject).
4. Updates `drafts.status` → `approved` / `edited` / `rejected`.
5. Returns HTMX fragment to swap the row in the queue table (no full-page reload).

**Sensitive safeguard:** approve/edit on `sensitive=1` drafts still allowed — human
reviewer has made the call. Auto-send gate is Phase 5 concern.

### Task 2 — `store/feedback.py`

New module, thin wrapper around SQLite writes:

```python
def record_feedback(conn, draft_id, action, edited_reply=None) -> None
def record_training_label(conn, draft_id, label: float) -> None
```

Label mapping: `approve=1.0`, `edit=0.5`, `reject=0.0`.

### Task 3 — Activity tab

Route: `GET /agent/activity`  
Template: `web/templates/activity.html`

Metrics (all from SQLite, no LLM calls):
- Total drafts processed (last 7 days)
- Breakdown by intent (bar chart via inline SVG or simple HTML table)
- Approval rate: `approved / (approved + rejected + edited)`
- Avg drafts/hour over last 24h

Query pattern:
```sql
SELECT intent, status, COUNT(*) as n, DATE(created_at) as day
FROM drafts
WHERE created_at >= datetime('now', '-7 days')
GROUP BY intent, status, day
```

### Task 4 — Costs tab

Route: `GET /agent/costs`  
Template: `web/templates/costs.html`

Metrics from `cost_log`:
- Running total spend (all time)
- Per-day spend (last 14 days, table + simple bar)
- Per-purpose breakdown: `intent` vs `draft` vs `wiki_qa`
- Top 5 most expensive individual calls

Query pattern:
```sql
SELECT DATE(ts) as day, purpose, SUM(cost_usd) as spend
FROM cost_log
WHERE ts >= datetime('now', '-14 days')
GROUP BY day, purpose
ORDER BY day DESC
```

### Task 5 — Cross-thread customer summary in ContextBuilder

Currently `ContextBuilder.build()` only uses the current thread.  
Add: if the customer (`username`) has prior threads (other than the current one),
fetch them from LumenX via `LumenXClient.get_threads_for_user(username)`,
summarise with a single Haiku call (cached), and inject as a `<prior_context>`
block before the current thread.

```python
# context_builder.py addition
def _summarise_prior_threads(self, username: str, current_thread_id: str) -> str | None:
    """Single Haiku call → 1-paragraph summary of prior threads, or None."""
```

Cap: only if prior thread count ≥ 1 and total message count ≤ 50 (avoid runaway cost).

### Task 6 — Dashboard nav

Add tab links to the base layout:
```
[Queue]  [Activity]  [Costs]
```
Active tab highlighted. HTMX-free (simple `<a>` links, full navigation).

---

## File-by-file changes

| File | Change |
|---|---|
| `web/app.py` | Add 3 feedback routes + 2 tab routes |
| `web/templates/queue.html` | Add Approve / Edit / Reject buttons + HTMX attrs |
| `web/templates/activity.html` | New — activity metrics |
| `web/templates/costs.html` | New — cost metrics |
| `web/templates/base.html` | Add tab nav (create if not exists) |
| `store/feedback.py` | New — `record_feedback`, `record_training_label` |
| `pipeline/context_builder.py` | Add cross-thread summary method |
| `sources/lumenx_client.py` | Add `get_threads_for_user` if not present |
| `tests/test_feedback.py` | New — unit tests for store functions + endpoints |
| `tests/test_dashboard_tabs.py` | New — route 200s, correct template rendering |
| `tests/test_context_builder.py` | Extend with cross-thread summary test |

---

## Acceptance criteria

- [ ] Approve/Edit/Reject buttons visible on queue page; clicking updates row in-place
- [ ] `feedback` and `training_labels` rows written correctly for each action
- [ ] `/agent/activity` returns 200, shows intent breakdown and approval rate
- [ ] `/agent/costs` returns 200, shows per-day spend from `cost_log`
- [ ] Cross-thread summary appears in Drafter context when prior threads exist
- [ ] All existing 88 tests still pass; total ≥ 110 tests at phase end
- [ ] `uv run ruff check src tests scripts` clean

---

## Sequence

1. `store/feedback.py` + tests → foundation, no UI needed
2. Feedback endpoints in `web/app.py` + queue template buttons
3. Activity tab
4. Costs tab
5. Cross-thread summary in ContextBuilder
6. Final test pass + ruff clean
