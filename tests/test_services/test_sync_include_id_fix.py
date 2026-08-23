"""v3 SyncWorker 在 ``include_id=True`` 表上的回归测试。

回归 bug（v3.5 之前）：sync.py 把 ``conflict_key=["user_id","id"]`` 但 ``cols`` 不含 id
的 spec（grade_history / articles）做 SELECT 时,只 select 了 cols 列,导致
``row_dict["id"]`` KeyError，整轮 pull 报错
``pull grade_history 失败: 'id'``。

修复点（v3.6）：
- pull：``select_cols = cols ∪ {id}`` 当 ``include_id=True``
- pull：``row_dict`` 用 ``select_cols`` 映射
- pull：INSERT 列与 args 也按 ``select_cols``（含 id）来,确保 ``ON CONFLICT (id)`` 命中
- push：pending 行 SELECT 也带 id；``row_dict`` 用 ``push_select_cols`` 映射

本测试不依赖真 MySQL —— 用 SQLite 双端（一份本地 + 一份"远端"用 SQLAlchemy engine）
模拟 SyncWorker 真实调用链。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pytest
from sqlalchemy import create_engine, text

from ielts_buddy.services.sync import SyncWorker


# =============================================================
# Schema
# =============================================================


REMOTE_SCHEMA = """
CREATE TABLE IF NOT EXISTS grade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    essay_text TEXT NOT NULL,
    topic TEXT DEFAULT '',
    overall_score REAL NOT NULL,
    task_response_score REAL,
    coherence_score REAL,
    lexical_score REAL,
    grammar_score REAL,
    result_json TEXT NOT NULL,
    task_type TEXT DEFAULT 'task2',
    error_summary_json TEXT DEFAULT '{}',
    graded_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_gh_user_updated
    ON grade_history(user_id, updated_at);

CREATE TABLE IF NOT EXISTS sync_meta (
    id INTEGER PRIMARY KEY,
    last_pull_at TEXT,
    last_push_at TEXT,
    last_error TEXT,
    last_error_at TEXT
);
INSERT OR IGNORE INTO sync_meta (id, last_pull_at, last_push_at) VALUES (1, NULL, NULL);
"""

LOCAL_SCHEMA = REMOTE_SCHEMA    # SQLite 端 schema 镜像


# =============================================================
# Fake FallbackContainer：满足 SyncWorker 最小接口
# =============================================================


class _FakeOnline:
    """替代远端，包装一个指向独立 SQLite 文件的 SQLAlchemy engine。"""

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
    """双 SQLite fallback container,SpyWorker 专属最小实现。"""

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
        for db_path, schema in (
            (self._remote_db, REMOTE_SCHEMA),
            (self._local_db, LOCAL_SCHEMA),
        ):
            c = sqlite3.connect(str(db_path))
            c.row_factory = sqlite3.Row
            c.executescript(schema)
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


class TestPullGradeHistoryIncludeIdFix:
    """SyncWorker.pull_table 在 include_id=True 表上的回归。"""

    def test_pull_grade_history_does_not_raise_keyerror_id(
        self, fake_container: _FakeContainer
    ):
        """修复前：`pull grade_history 失败: 'id'`

        修复后：pull 成功,本地 SQLite 写入一行带正确 id 的记录。
        """
        ts = datetime.now().isoformat(timespec="seconds")
        # 远端先写一行
        with fake_container.online._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO grade_history "
                "(user_id, essay_text, topic, overall_score, result_json, "
                " graded_at, updated_at, sync_status) "
                "VALUES (:uid, :essay, :topic, :score, :rj, :ga, :ua, 'synced')"
            ), {
                "uid": 1, "essay": "essay body", "topic": "env",
                "score": 6.5, "rj": '{"overall_score": 6.5}',
                "ga": ts, "ua": ts,
            })
            row = conn.execute(
                text("SELECT id FROM grade_history ORDER BY id DESC LIMIT 1")
            ).first()
            remote_id = int(row[0])
        assert remote_id > 0

        worker = SyncWorker(fake_container)  # type: ignore[arg-type]
        result = worker.sync_once()

        # 1) 错误堆里再不许有 'id' KeyError（修复前会一直冒出来）
        id_errors = [e for e in result.errors if "'id'" in e]
        assert id_errors == [], f"pull 仍抛 KeyError 'id': {id_errors}"

        # 2) 修复前的次级 bug：本地 SQLite 会因 ON CONFLICT 不命中而无限重复插入，
        #    但 _get_last_pull_at 会记忆远端的最新时间。
        #    检验方法：本地应只有 1 行,且 id 应等于远端 id（保留 id 才能 ON CONFLICT 命中）
        local_conn = fake_container.offline._conn
        rows = local_conn.execute(
            "SELECT id, user_id, overall_score FROM grade_history WHERE user_id = 1"
        ).fetchall()
        assert len(rows) == 1, f"本地 grade_history 应有 1 行; 实际 {rows!r}"
        assert rows[0]["id"] == remote_id, (
            f"id 应保留为远端 {remote_id},实际 {rows[0]['id']}（修复前会变）"
        )
        assert rows[0]["overall_score"] == 6.5

    def test_pull_grade_history_is_idempotent(
        self, fake_container: _FakeContainer
    ):
        """二次 pull 不应产生重复行（ON CONFLICT (id) 必须命中）。

        修复前：INSERT 时不写 id → SQLite 自动分配新 id → ON CONFLICT (id) 不命中
        → 每次 pull 都新增一条。二次跑会变 2 行。
        """
        ts = datetime.now().isoformat(timespec="seconds")
        with fake_container.online._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO grade_history "
                "(user_id, essay_text, overall_score, result_json, "
                " graded_at, updated_at, sync_status) "
                "VALUES (1, 'essay', 6.5, '{}', :ts, :ts, 'synced')"
            ), {"ts": ts})

        worker = SyncWorker(fake_container)  # type: ignore[arg-type]
        worker.sync_once()
        worker.sync_once()

        local_conn = fake_container.offline._conn
        cnt = local_conn.execute(
            "SELECT COUNT(*) AS cnt FROM grade_history WHERE user_id = 1"
        ).fetchone()["cnt"]
        assert cnt == 1, f"二次 pull 应仍只有 1 行,实际 {cnt}（修复前会 2 行）"

    def test_pull_grade_history_preserves_remote_ts(
        self, fake_container: _FakeContainer
    ):
        """ON CONFLICT UPDATE 应更新到远端值,而不是保留旧的。"""
        ts_remote = datetime.now().isoformat(timespec="seconds")
        with fake_container.online._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO grade_history "
                "(user_id, essay_text, overall_score, result_json, "
                " graded_at, updated_at, sync_status) "
                "VALUES (1, 'essay', 6.5, '{}', :ts, :ts, 'synced')"
            ), {"ts": ts_remote})

        worker = SyncWorker(fake_container)  # type: ignore[arg-type]
        worker.sync_once()

        local_conn = fake_container.offline._conn
        row = local_conn.execute(
            "SELECT updated_at FROM grade_history WHERE user_id = 1"
        ).fetchone()
        assert row["updated_at"] == ts_remote

    def test_pull_articles_spec_also_fixed(
        self, fake_container: _FakeContainer
    ):
        """articles 同样有 include_id=True + conflict_key=[user_id, id]
        但 cols 不含 id 的问题。验证它走同一条修复路径也不会爆。"""
        # 给 articles 建表
        for db_path in (fake_container._remote_db, fake_container._local_db):
            c = sqlite3.connect(str(db_path))
            c.row_factory = sqlite3.Row
            c.executescript("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL DEFAULT 1,
                    title TEXT,
                    source_text TEXT,
                    translation TEXT,
                    word_count INTEGER,
                    diff_words_json TEXT,
                    translation_source TEXT,
                    analysis_source TEXT,
                    created_at TEXT,
                    updated_at TEXT DEFAULT '',
                    sync_status TEXT DEFAULT 'synced'
                );
                CREATE INDEX IF NOT EXISTS idx_articles_user_created
                    ON articles(user_id, created_at);
            """)
            c.commit()
            c.close()

        ts = datetime.now().isoformat(timespec="seconds")
        with fake_container.online._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO articles "
                "(user_id, title, source_text, translation, word_count, "
                " diff_words_json, translation_source, analysis_source, "
                " created_at, updated_at, sync_status) "
                "VALUES (1, 't', 'src', 'trans', 100, '[]', 'llm', 'fallback', "
                " :ts, :ts, 'synced')"
            ), {"ts": ts})

        worker = SyncWorker(fake_container)  # type: ignore[arg-type]
        result = worker.sync_once()

        id_errors = [e for e in result.errors if "'id'" in e]
        assert id_errors == [], f"articles spec 仍有 'id' KeyError: {id_errors}"
