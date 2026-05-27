from pathlib import Path

import pytest

from auto_reply.store.db import connect
from auto_reply.store.migrations import apply_migrations


@pytest.fixture
def db(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    apply_migrations(conn)
    yield conn
    conn.close()
