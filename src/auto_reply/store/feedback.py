from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

_LABEL_FLOAT: dict[str, float] = {
    "approve": 1.0,
    "edit": 0.5,
    "reject": 0.0,
}
_THUMB: dict[str, int] = {
    "approve": 1,
    "edit": 1,
    "reject": 0,
}
_STATUS: dict[str, str] = {
    "approve": "approved",
    "edit": "edited",
    "reject": "rejected",
}


def record_feedback_with_label(
    conn: sqlite3.Connection,
    draft_id: int,
    action: str,
    edited_reply: str | None = None,
) -> None:
    """Write a feedback row, a training_labels row, and update draft status."""
    if action not in _LABEL_FLOAT:
        raise ValueError(f"Unknown action {action!r}. Must be approve|edit|reject.")
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO feedback (draft_id, thumb, notes, action, edited_reply, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (draft_id, _THUMB[action], edited_reply, action, edited_reply, ts),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO training_labels
            (draft_id, label, label_float, source, features_json, ts)
        VALUES (?, ?, ?, 'human', '{}', ?)
        """,
        (draft_id, int(_LABEL_FLOAT[action]), _LABEL_FLOAT[action], ts),
    )
    conn.execute(
        "UPDATE drafts SET status = ? WHERE id = ?",
        (_STATUS[action], draft_id),
    )
    conn.commit()
