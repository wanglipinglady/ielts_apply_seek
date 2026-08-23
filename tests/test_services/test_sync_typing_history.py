"""v3 SyncWorker 对 ``typing_history`` 表的双向同步回归测试。

背景（v3.6）：
  typing_history 表（机考打字记录）SQLite 端 / MySQL 端 schema 字段一致,
  之前没有被列入 ``SYNC_TABLES``,所以 MySQL 模式下本地打字记录不会
  跨设备同步 —— 在 A 设备练的打字成绩在 B 设备看不到（"跨设备丢分"）。

本测试不依赖真 MySQL —— 用 SQLite 双端（一份本地 + 一份"远端"用
SQLAlchemy engine）模拟 SyncWorker 真实调用链。

注意：SyncWorker 的 push 路径使用 MySQL 的 ``INSERT ... ON DUPLICATE KEY UPDATE``
  语法,SQLite 引擎无法直接执行。本文件因此把测试重点放在：
    1. typing_history 被加入 SYNC_TABLES 后,SyncWorker 在两端都有该表时
       不会抛 KeyError 'id'（pull 路径）
    2. pull 端到端：远端 → 本地,id 保留,二次幂等
    3. push 路径走完 INSERT 阶段（虽然 fake 远端会用 sqlite3 报错,但
       SyncWorker 会把它降级成 warning,不会冒泡成 KeyError 'id'）
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine, text

from ielts_buddy.services.sync import SyncWorker


# =============================================================
# Schema（两端一致）
# =============================================================


TYPING_SCHEMA = """
CREATE TABLE IF NOT EXISTS typing_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    mode TEXT NOT NULL DEFAULT 'words',
    prompt_text TEXT NOT NULL,
    typed_text TEXT DEFAULT '',
    duration_sec INTEGER NOT NULL DEFAULT 0,
    wpm REAL NOT NULL DEFAULT 0,
    accuracy REAL NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    total_chars INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 1,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_th_user_created
    ON typing_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_th_user_mode
    ON typing_history(user_id, mode);

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
# Fake FallbackContainer：满足 SyncWorker 最小接口
# =============================================================


class _FakeOnline:
    """替代远端,包装一个指向独立 SQLite 文件的 SQLAlchemy engine。"""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._engine = create_engine(
            "sqlite://",
            creator=lambda: sqlite3.connect(str(db_path)),
        )


class _FakeOffline:
    """替代本地 SQLite,让 SyncWorker 拿到 sql.Row 风格 ``row["col"]`` 访问。"""

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
    """双 SQLite fallback container,SyncWorker 专属最小实现。"""

    def __init__(self, tmp_path: Path):
        self._remote_db = tmp_path / "remote.db"
        self._local_db = tmp_path / "local.db"
        self._online_obj = _FakeOnline(self._remote_db)
        self._offline_obj = _FakeOffline(self._local_db)

        self._current_mode = "online"
        self._last_mysql_ok = True

    # ---- fallback container 协议的最小实现 ----

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

    # ---- setup ----

    def init_schema(self) -> None:
        for db_path in (self._remote_db, self._local_db):
            c = sqlite3.connect(str(db_path))
            c.row_factory = sqlite3.Row
            c.executescript(TYPING_SCHEMA)
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
# 测试
# =============================================================


class TestTypingHistoryInSyncTables:
    """typing_history 被加入 SYNC_TABLES 后 SyncWorker 的行为契约。"""

    def test_typing_history_is_in_sync_tables(self):
        """typing_history spec 必须存在,且 include_id=True。

        这是修复跨设备丢分隐患的关键契约 —— spec 必须存在才能 sync。
        """
        from ielts_buddy.services.sync import SYNC_TABLES

        specs_by_name = {s["name"]: s for s in SYNC_TABLES}
        assert "typing_history" in specs_by_name, (
            "typing_history 必须出现在 SYNC_TABLES,否则跨设备打字记录不会同步"
        )

        spec = specs_by_name["typing_history"]
        assert spec["include_id"] is True
        assert spec["conflict_key"] == ["user_id", "id"]
        assert spec["ts_col"] == "updated_at"
        # 业务列必须覆盖所有非 id 非同步状态列
        for col in (
            "user_id", "mode", "prompt_text", "typed_text",
            "duration_sec", "wpm", "accuracy", "error_count",
            "total_chars", "completed", "result_json",
            "created_at", "updated_at",
        ):
            assert col in spec["cols"], f"业务列 {col} 缺失"

    def test_pull_typing_history_does_not_raise_keyerror_id(
        self, fake_container: _FakeContainer
    ):
        """远端有 typing_history 行时,pull 不会抛 KeyError 'id'。

        回归场景：和 grade_history 一样,include_id=True 的表如果 SELECT 不带 id
        会因为 conflict_key=["user_id","id"] 而 KeyError。这里必须走通。
        """
        ts = datetime.now().isoformat(timespec="seconds")
        with fake_container.online._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO typing_history "
                "(user_id, mode, prompt_text, typed_text, duration_sec, "
                " wpm, accuracy, error_count, total_chars, completed, "
                " result_json, created_at, updated_at, sync_status) "
                "VALUES (1, 'words', 'hello world', 'hello world', 20, "
                " 40.0, 1.0, 0, 11, 1, '{}', :ts, :ts, 'synced')"
            ), {"ts": ts})
            row = conn.execute(
                text("SELECT id FROM typing_history ORDER BY id DESC LIMIT 1")
            ).first()
            remote_id = int(row[0])
        assert remote_id > 0

        worker = SyncWorker(fake_container)  # type: ignore[arg-type]
        result = worker.sync_once()

        # 关键契约：pull typing_history 不能抛 KeyError 'id'
        typing_errors = [
            e for e in result.errors
            if "typing_history" in e and "'id'" in e
        ]
        assert typing_errors == [], (
            f"pull typing_history 仍抛 KeyError 'id': {typing_errors}"
        )

        # 本地应有一行且 id 与远端一致（保留 id 才能 ON CONFLICT 命中）
        local_conn = fake_container.offline._conn
        rows = local_conn.execute(
            "SELECT id, user_id, mode, wpm FROM typing_history WHERE user_id = 1"
        ).fetchall()
        assert len(rows) == 1, f"本地 typing_history 应有 1 行; 实际 {rows!r}"
        assert rows[0]["id"] == remote_id, (
            f"id 应保留为远端 {remote_id},实际 {rows[0]['id']}"
        )
        assert rows[0]["mode"] == "words"
        assert rows[0]["wpm"] == 40.0

    def test_pull_typing_history_is_idempotent(
        self, fake_container: _FakeContainer
    ):
        """二次 pull 不应产生重复行（ON CONFLICT (id) 必须命中）。

        修复前：INSERT 时不写 id → SQLite 自动分配新 id → ON CONFLICT (id) 不命中
        → 每次 pull 都新增一条。二次跑会变 2 行。
        """
        ts = datetime.now().isoformat(timespec="seconds")
        with fake_container.online._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO typing_history "
                "(user_id, mode, prompt_text, duration_sec, wpm, accuracy, "
                " result_json, created_at, updated_at, sync_status) "
                "VALUES (1, 'sentences', 'This is a test.', 15, 25.0, 0.9, "
                " '{}', :ts, :ts, 'synced')"
            ), {"ts": ts})

        worker = SyncWorker(fake_container)  # type: ignore[arg-type]
        worker.sync_once()
        worker.sync_once()

        local_conn = fake_container.offline._conn
        cnt = local_conn.execute(
            "SELECT COUNT(*) AS cnt FROM typing_history WHERE user_id = 1"
        ).fetchone()["cnt"]
        assert cnt == 1, f"二次 pull 应仍只有 1 行,实际 {cnt}（修复前会 2 行）"

    def test_pull_typing_history_preserves_remote_ts(
        self, fake_container: _FakeContainer
    ):
        """ON CONFLICT UPDATE 应更新到远端值,而不是保留旧的。"""
        ts_remote = datetime.now().isoformat(timespec="seconds")
        with fake_container.online._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO typing_history "
                "(user_id, mode, prompt_text, duration_sec, wpm, accuracy, "
                " result_json, created_at, updated_at, sync_status) "
                "VALUES (1, 'words', 'apple', 10, 30.0, 1.0, "
                " '{}', :ts, :ts, 'synced')"
            ), {"ts": ts_remote})

        worker = SyncWorker(fake_container)  # type: ignore[arg-type]
        worker.sync_once()

        local_conn = fake_container.offline._conn
        row = local_conn.execute(
            "SELECT updated_at, wpm FROM typing_history WHERE user_id = 1"
        ).fetchone()
        assert row["updated_at"] == ts_remote
        assert row["wpm"] == 30.0

    def test_pull_typing_history_handles_multiple_modes(
        self, fake_container: _FakeContainer
    ):
        """多种 mode 的打字记录都能正确同步。"""
        ts = datetime.now().isoformat(timespec="seconds")
        modes_payload = [
            ("words", "apple banana", 60, 35.0, 0.95),
            ("sentences", "I love programming.", 90, 40.0, 0.98),
            ("passage", "Long paragraph text here.", 180, 28.0, 0.92),
        ]
        with fake_container.online._engine.begin() as conn:
            for mode, prompt, duration, wpm, acc in modes_payload:
                conn.execute(text(
                    "INSERT INTO typing_history "
                    "(user_id, mode, prompt_text, duration_sec, wpm, accuracy, "
                    " result_json, created_at, updated_at, sync_status) "
                    "VALUES (1, :mode, :prompt, :dur, :wpm, :acc, "
                    " '{}', :ts, :ts, 'synced')"
                ), {
                    "mode": mode, "prompt": prompt, "dur": duration,
                    "wpm": wpm, "acc": acc, "ts": ts,
                })

        SyncWorker(fake_container).sync_once()  # type: ignore[arg-type]

        local_conn = fake_container.offline._conn
        rows = local_conn.execute(
            "SELECT mode, prompt_text, wpm, accuracy FROM typing_history "
            "WHERE user_id = 1 ORDER BY id"
        ).fetchall()
        assert len(rows) == 3, f"应有 3 种 mode 的记录; 实际 {len(rows)}"
        assert [r["mode"] for r in rows] == ["words", "sentences", "passage"]
        assert rows[0]["wpm"] == 35.0
        assert rows[1]["wpm"] == 40.0
        assert rows[2]["wpm"] == 28.0