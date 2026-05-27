from pathlib import Path

import pytest

from auto_reply.store.db import connect, transaction


def test_connect_creates_parent_dir(tmp_path: Path):
    db_path = tmp_path / "nested" / "agent.db"
    conn = connect(db_path)
    assert db_path.exists()
    assert db_path.parent.is_dir()
    conn.close()


def test_connect_enables_foreign_keys(tmp_path: Path):
    conn = connect(tmp_path / "a.db")
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
    conn.close()


def test_transaction_commits_on_success(tmp_path: Path):
    conn = connect(tmp_path / "b.db")
    conn.execute("CREATE TABLE t (x INTEGER)")
    with transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
    rows = [tuple(r) for r in conn.execute("SELECT x FROM t").fetchall()]
    assert rows == [(1,)]
    conn.close()


def test_connect_returns_row_factory(tmp_path: Path):
    conn = connect(tmp_path / "row.db")
    conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'x')")
    row = conn.execute("SELECT a, b FROM t").fetchone()
    assert row["a"] == 1
    assert row["b"] == "x"
    conn.close()


def test_transaction_rolls_back_on_exception(tmp_path: Path):
    conn = connect(tmp_path / "c.db")
    conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")
    rows = conn.execute("SELECT x FROM t").fetchall()
    assert rows == []
    conn.close()
