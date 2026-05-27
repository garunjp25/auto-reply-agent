import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations_sql"


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def apply_migrations(conn: sqlite3.Connection) -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for path in files:
        version = int(path.name.split("_", 1)[0])
        if version <= current_version(conn):
            continue
        sql = path.read_text(encoding="utf-8")
        # executescript() issues an implicit COMMIT before running, so we
        # cannot wrap it in transaction(). Instead we embed a final
        # BEGIN/COMMIT around the version-stamp INSERT directly in the script.
        stamp = (
            "\nBEGIN;\n"
            "INSERT INTO schema_version (version, applied_at) VALUES "
            f"({version}, '{datetime.now(timezone.utc).isoformat()}');\n"
            "COMMIT;\n"
        )
        conn.executescript(sql + stamp)
