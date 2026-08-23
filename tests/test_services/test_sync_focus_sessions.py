"""v3 SyncWorker 对 ``focus_sessions`` 表的双向同步回归测试。

背景（v3.6）：
  focus_sessions 表（番茄钟专注会话）SQLite / MySQL 端 schema 字段一致,
  已在 SYNC_TABLES 中注册（include_id=True, conflict_key=[user_id, id]）。
  本测试验证：
    1. focus_sessions spec 必须存在且配置正确
    2. pull 不会抛 KeyError 'id'（与 grade_history 同源代码路径）
    3. 二次 pull 幂等
    4. 多种 activity 都能正常同步

用 SQLite 双端模拟（远端用 SQLAlchemy engine + 同 schema 的 SQLite 文件）。
push 路径使用 MySQL UPSERT 语法,SQLite 引擎无法执行 ——
本测试只覆盖 pull 路径（与 sync_typing_history 同样的策略）。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine, text

from ielts_buddy.services.sync import SyncWorker


# =============================================================
# Schema（两端一致）
# =============================================================


FOCUS_SCHEMA = """
CREATE TABLE IF NOT EXISTS focus_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    activity TEXT NOT NULL DEFAULT 'other',
    planned_sec INTEGER NOT NULL DEFAULT 1500,
    duration_sec INTEGER NOT NULL DEFAULT 0,
    interrupted INTEGER NOT NULL DEFAULT 0,
    note TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_fs_user_started
    ON focus_sessions(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_fs_user_activity
    ON focus_sessions(user_id, activity);

CREATE TABLE IF NOT EXISTS sync_meta (
    id INTEGER PRIMARY KEY,
    last_pull_at TEXT,
    last_push_at TEXT,
    last_error TEXT,
    last_error_at TEXT
);
INSERT OR IGNORE INTO sync_meta (id, last_pull_at, last_push_at) VALUES (1, NULL, NULL);
"""


# =============================================================
# Fake FallbackContainer
# =============================================================


class _FakeOnline:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._engine = create_engine(
            "sqlite://",
            creator=lambda: sqlite3.connect(str(db_path)),
        )


class _FakeOffline:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _open(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._db_path))
        c.row_factory = sqlite3.Row
        return c

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._open()


class _FakeContainer:
    def __init__(self, tmp_path: Path):
        self._remote_db = tmp_path / "remote.db"
        self._local_db = tmp_path / "local.db"
        self._online_obj = _FakeOnline(self._remote_db)
        self._offline_obj = _FakeOffline(self._local_db)

        self._current_mode = "online"
        self._last_mysql_ok = True

    @property
    def online(self):
        return self._online_obj

    @property
    def offline(self):
        return self._offline_obj

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @property
    def mysql_reachable(self) -> bool:
        return True

    def try_mysql(self) -> bool:
        return True

    def init_schema(self) -> None:
        for db_path in (self._remote_db, self._local_db):
            c = sqlite3.connect(str(db_path))
            c.row_factory = sqlite3.Row
            c.executescript(FOCUS_SCHEMA)
            c.commit()
            c.close()

    def cleanup(self) -> None:
        try:
            self._online_obj._engine.dispose()
        except Exception:
            pass


@pytest.fixture
def fake_container(tmp_path: Path) -> Iterator[_FakeContainer]:
    c = _FakeContainer(tmp_path)
    c.init_schema()
    yield c
    c.cleanup()


# =============================================================
# Tests
# =============================================================


class TestFocusSessionsInSyncTables:
    """focus_sessions spec 必须存在且配置正确。"""

    def test_focus_sessions_is_in_sync_tables(self):
        """契约测试：spec 必须出现在 SYNC_TABLES。"""
        from ielts_buddy.services.sync import SYNC_TABLES

        specs_by_name = {s["name"]: s for s in SYNC_TABLES}
        assert "focus_sessions" in specs_by_name, (
            "focus_sessions 必须出现在 SYNC_TABLES,否则跨设备番茄钟记录不会同步"
        )

    def test_focus_sessions_spec_fields(self):
        """spec 的关键字段必须正确。"""
        from ielts_buddy.services.sync import SYNC_TABLES

        spec = next(s for s in SYNC_TABLES if s["name"] == "focus_sessions")
        assert spec["include_id"] is True
        assert spec["conflict_key"] == ["user_id", "id"]
        assert spec["ts_col"] == "updated_at"
        # 业务列必须覆盖所有关键列
        for col in (
            "user_id", "activity", "planned_sec", "duration_sec",
            "interrupted", "note", "started_at", "ended_at",
            "created_at", "updated_at",
        ):
            assert col in spec["cols"], f"业务列 {col} 缺失"

    def test_pull_focus_sessions_does_not_raise_keyerror_id(
        self, fake_container: _FakeContainer
    ):
        """远端有 focus_sessions 行时,pull 不抛 KeyError 'id'。

        回归场景：与 grade_history 一样,include_id=True 的表如果 SELECT
        不带 id,会因为 conflict_key=["user_id","id"] 而 KeyError。
        """
        ts = datetime.now().isoformat(timespec="seconds")
        with fake_container.online._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO focus_sessions "
                "(user_id, activity, planned_sec, duration_sec, interrupted, "
                " note, started_at, ended_at, created_at, updated_at, sync_status) "
                "VALUES (1, 'vocab', 1500, 1500, 0, '背完 chapter 5', :ts, :ts, "
                " :ts, :ts, 'synced')"
            ), {"ts": ts})
            row = conn.execute(
                text("SELECT id FROM focus_sessions ORDER BY id DESC LIMIT 1")
            ).first()
            remote_id = int(row[0])
        assert remote_id > 0

        worker = SyncWorker(fake_container)  # type: ignore[arg-type]
        result = worker.sync_once()

        # 关键契约:pull focus_sessions 不能抛 KeyError 'id'
        fs_errors = [
            e for e in result.errors
            if "focus_sessions" in e and "'id'" in e
        ]
        assert fs_errors == [], (
            f"pull focus_sessions 仍抛 KeyError 'id': {fs_errors}"
        )

        # 本地应有一行且 id 与远端一致
        local_conn = fake_container.offline._conn
        rows = local_conn.execute(
            "SELECT id, user_id, activity, duration_sec, note "
            "FROM focus_sessions WHERE user_id = 1"
        ).fetchall()
        assert len(rows) == 1, f"本地 focus_sessions 应有 1 行; 实际 {rows!r}"
        assert rows[0]["id"] == remote_id
        assert rows[0]["activity"] == "vocab"
        assert rows[0]["duration_sec"] == 1500
        assert rows[0]["note"] == "背完 chapter 5"

    def test_pull_focus_sessions_is_idempotent(
        self, fake_container: _FakeContainer
    ):
        """二次 pull 不应产生重复行（ON CONFLICT (id) 必须命中）。"""
        ts = datetime.now().isoformat(timespec="seconds")
        with fake_container.online._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO focus_sessions "
                "(user_id, activity, planned_sec, duration_sec, interrupted, "
                " started_at, ended_at, created_at, updated_at, sync_status) "
                "VALUES (1, 'writing', 1500, 1500, 0, "
                " :ts, :ts, :ts, :ts, 'synced')"
            ), {"ts": ts})

        worker = SyncWorker(fake_container)  # type: ignore[arg-type]
        worker.sync_once()
        worker.sync_once()

        local_conn = fake_container.offline._conn
        cnt = local_conn.execute(
            "SELECT COUNT(*) AS cnt FROM focus_sessions WHERE user_id = 1"
        ).fetchone()["cnt"]
        assert cnt == 1, f"二次 pull 应仍只有 1 行,实际 {cnt}"

    def test_pull_focus_sessions_multiple_activities(
        self, fake_container: _FakeContainer
    ):
        """多种 activity 的专注记录都能正常同步。"""
        base = datetime.now()
        activities_payload = [
            ("vocab", 1500, 1500, 0, "背单词"),
            ("writing", 1500, 1450, 0, "写作 Task 2"),
            ("exam", 7200, 7200, 0, "全套模考"),
            ("typing", 600, 580, 0, "练打字"),
            ("reading", 1800, 600, 1, "读到一半被打断"),
            ("other", 300, 300, 0, ""),
        ]
        with fake_container.online._engine.begin() as conn:
            for i, (activity, planned, dur, intr, note) in enumerate(activities_payload):
                ts = (base + timedelta(seconds=i)).isoformat(timespec="seconds")
                conn.execute(text(
                    "INSERT INTO focus_sessions "
                    "(user_id, activity, planned_sec, duration_sec, interrupted, "
                    " note, started_at, ended_at, created_at, updated_at, sync_status) "
                    "VALUES (1, :a, :p, :d, :i, :n, :ts, :ts, :ts, :ts, 'synced')"
                ), {
                    "a": activity, "p": planned, "d": dur, "i": intr,
                    "n": note, "ts": ts,
                })

        SyncWorker(fake_container).sync_once()  # type: ignore[arg-type]

        local_conn = fake_container.offline._conn
        rows = local_conn.execute(
            "SELECT activity, duration_sec, interrupted, note "
            "FROM focus_sessions WHERE user_id = 1 ORDER BY id"
        ).fetchall()
        assert len(rows) == 6, f"应有 6 行; 实际 {len(rows)}"
        assert [r["activity"] for r in rows] == [
            "vocab", "writing", "exam", "typing", "reading", "other",
        ]
        assert rows[4]["interrupted"] == 1       # reading 是放弃的
        assert rows[4]["note"] == "读到一半被打断"
        assert rows[2]["duration_sec"] == 7200   # exam 是 2h