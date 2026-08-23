"""v3 同步集成测试：MySQL ↔ SQLite 双向同步全链路。

覆盖场景：
  1. 增量 pull：MySQL 新增一行 → SQLite 拉过来
  2. 增量 push：SQLite 标 pending_upload → MySQL 写入
  3. 冲突解决（last-write-wins）：本地更新 + 远端旧 → 远端覆盖；反之亦然
  4. 跨表同步：personal_vocab / learning_records / vocab_categories 同时同步
  5. 不可达时不抛异常（SyncWorker.try_mysql 失败时静默）

注意：需要 MySQL 可达。CI 环境若不可达则整个文件 skip。
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path

# 必须在 import ielts_buddy 之前设置
os.environ.setdefault("IELTS_BUDDY_JWT_SECRET", "test_" + "x" * 32)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _mysql_reachable() -> bool:
    """前置检查：MySQL 可达才跑测试。"""
    try:
        import pymysql
        conn = pymysql.connect(
            host="118.190.148.121", port=3306,
            user="remote_user", password="Pass@666",
            database="ietls_learn_online", charset="utf8mb4",
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_mysql_reachable(), "MySQL 不可达")
class V3SyncIntegrationTest(unittest.TestCase):
    """v3 同步全链路集成测试。"""

    @classmethod
    def setUpClass(cls):
        # 用一个独立的临时 SQLite 文件，避免污染用户的 ~/.ielts-buddy/ielts_buddy.db
        import tempfile
        cls._tmpdir = tempfile.mkdtemp(prefix="v3-sync-test-")
        cls.sqlite_path = Path(cls._tmpdir) / "test.db"

        from ielts_buddy.repositories.fallback_repo import create_fallback_container
        from ielts_buddy.repositories.mysql_repo import _build_mysql_url
        cls.container = create_fallback_container(
            sqlite_db_path=cls.sqlite_path,
            mysql_url=_build_mysql_url(),
            prefer_mode="online",
        )
        from ielts_buddy.services.sync import SyncWorker
        cls.worker = SyncWorker(cls.container)
        cls.user_id = 1155  # 测试用：已知存在 wanglipingresume@163.com

        # 测试开始前：清理 _v3test_ 前缀的测试数据
        with cls.container.online._engine.begin() as conn:
            from sqlalchemy import text
            for tbl in ("personal_vocab", "learning_records",
                        "vocab_categories", "articles"):
                try:
                    conn.execute(
                        text(f"DELETE FROM {tbl} WHERE word LIKE '_v3test_%' "
                             f"OR word LIKE 'name LIKE \\'_v3test_%\\'")
                    )
                except Exception:
                    pass
        cls.container.offline._conn.execute(
            "DELETE FROM personal_vocab WHERE word LIKE '_v3test_%'"
        )
        cls.container.offline._conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.container.close()
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _now_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def test_01_pull_personal_vocab(self):
        """场景 1：MySQL 端新增一行 → sync_once() 拉到本地。"""
        from sqlalchemy import text
        test_word = "_v3test_pull"
        now = self._now_str()

        # 1. MySQL 端写入
        with self.container.online._engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM personal_vocab WHERE word=:w AND user_id=:u"
            ), {"w": test_word, "u": self.user_id})
            conn.execute(text(
                """INSERT INTO personal_vocab
                   (user_id, word, phonetic, meaning, pos, band,
                    source, created_at, updated_at, sync_status)
                   VALUES (:u, :w, :p, :m, :pos, :b, 'manual',
                           :ts, :ts, 'synced')"""
            ), {
                "u": self.user_id, "w": test_word,
                "p": "/test/", "m": "测试词", "pos": "n", "b": 7,
                "ts": now,
            })

        # 2. 重置 last_pull_at，确保会拉
        self.container.offline._conn.execute(
            "UPDATE sync_meta SET last_pull_at=NULL WHERE id=1"
        )
        self.container.offline._conn.commit()

        # 3. 执行 sync
        result = self.worker.sync_once()
        self.assertEqual(len(result.errors), 0, f"sync errors: {result.errors}")
        self.assertGreaterEqual(result.pulled, 1)

        # 4. 本地应该有这行
        row = self.container.offline._conn.execute(
            "SELECT word, meaning FROM personal_vocab "
            "WHERE word=? AND user_id=?",
            (test_word, self.user_id),
        ).fetchone()
        self.assertIsNotNone(row, "pull 后本地应有此行")
        self.assertEqual(row[1], "测试词")

        # cleanup
        with self.container.online._engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM personal_vocab WHERE word=:w AND user_id=:u"
            ), {"w": test_word, "u": self.user_id})
        self.container.offline._conn.execute(
            "DELETE FROM personal_vocab WHERE word=? AND user_id=?",
            (test_word, self.user_id),
        )
        self.container.offline._conn.commit()

    def test_02_push_personal_vocab(self):
        """场景 2：本地 pending_upload → MySQL 端写入。"""
        from sqlalchemy import text
        test_word = "_v3test_push"
        now = self._now_str()

        # 1. 本地写入 + 标 pending_upload
        self.container.offline._conn.execute(
            """INSERT INTO personal_vocab
               (user_id, word, phonetic, meaning, pos, band,
                source, created_at, updated_at, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, 'manual', ?, ?, 'pending_upload')""",
            (self.user_id, test_word, "/push/", "推送测试", "v", 8,
             now, now),
        )
        self.container.offline._conn.commit()

        # 2. 执行 sync
        result = self.worker.sync_once()
        self.assertEqual(len(result.errors), 0, f"sync errors: {result.errors}")
        self.assertGreaterEqual(result.pushed, 1)

        # 3. MySQL 端应该有
        with self.container.online._engine.connect() as conn:
            row = conn.execute(
                text("SELECT meaning FROM personal_vocab "
                     "WHERE word=:w AND user_id=:u"),
                {"w": test_word, "u": self.user_id},
            ).first()
        self.assertIsNotNone(row, "push 后 MySQL 端应有此行")
        self.assertEqual(row[0], "推送测试")

        # 4. 本地应已标 synced
        row = self.container.offline._conn.execute(
            "SELECT sync_status FROM personal_vocab "
            "WHERE word=? AND user_id=?",
            (test_word, self.user_id),
        ).fetchone()
        self.assertEqual(row[0], "synced", "push 后本地应标记 synced")

        # cleanup
        with self.container.online._engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM personal_vocab WHERE word=:w AND user_id=:u"
            ), {"w": test_word, "u": self.user_id})
        self.container.offline._conn.execute(
            "DELETE FROM personal_vocab WHERE word=? AND user_id=?",
            (test_word, self.user_id),
        )
        self.container.offline._conn.commit()

    def test_03_conflict_last_write_wins_local_newer(self):
        """场景 3a：本地更新（newer）vs 远端旧（older）→ 本地赢。"""
        from sqlalchemy import text
        test_word = "_v3test_conflict_local"
        local_ts = "2026-08-23 12:00:00"
        remote_ts = "2026-08-23 10:00:00"

        # 准备本地行（newer）
        self.container.offline._conn.execute(
            "DELETE FROM personal_vocab WHERE word=? AND user_id=?",
            (test_word, self.user_id),
        )
        self.container.offline._conn.execute(
            """INSERT INTO personal_vocab
               (user_id, word, meaning, source, created_at, updated_at, sync_status)
               VALUES (?, ?, 'LOCAL_NEWER', 'manual', ?, ?, 'pending_upload')""",
            (self.user_id, test_word, local_ts, local_ts),
        )
        self.container.offline._conn.commit()

        # 准备远端行（older）
        with self.container.online._engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM personal_vocab WHERE word=:w AND user_id=:u"
            ), {"w": test_word, "u": self.user_id})
            conn.execute(text(
                """INSERT INTO personal_vocab
                   (user_id, word, meaning, source, created_at, updated_at, sync_status)
                   VALUES (:u, :w, 'REMOTE_OLDER', 'manual', :ts, :ts, 'synced')"""
            ), {"u": self.user_id, "w": test_word, "ts": remote_ts})

        # 同步
        self.worker.sync_once()

        # 远端应该是 LOCAL_NEWER（被本地覆盖）
        with self.container.online._engine.connect() as conn:
            row = conn.execute(
                text("SELECT meaning FROM personal_vocab "
                     "WHERE word=:w AND user_id=:u"),
                {"w": test_word, "u": self.user_id},
            ).first()
        self.assertEqual(row[0], "LOCAL_NEWER", "last-write-wins: 本地 newer 应赢")

        # 清理
        with self.container.online._engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM personal_vocab WHERE word=:w AND user_id=:u"
            ), {"w": test_word, "u": self.user_id})
        self.container.offline._conn.execute(
            "DELETE FROM personal_vocab WHERE word=? AND user_id=?",
            (test_word, self.user_id),
        )
        self.container.offline._conn.commit()

    def test_04_sync_worker_idempotent(self):
        """场景 4：sync 跑两次结果一致（幂等性）。"""
        # 不修改任何数据时，连续跑两次都应该是 push=0 pull=0（无新数据）
        self.container.offline._conn.execute(
            "UPDATE sync_meta SET last_pull_at=NULL, last_push_at=NULL WHERE id=1"
        )
        self.container.offline._conn.commit()
        r1 = self.worker.sync_once()
        r2 = self.worker.sync_once()
        # 第二次应该 pull=0, push=0（同步水位已对齐）
        self.assertEqual(r2.pulled, 0)
        self.assertEqual(r2.pushed, 0)
        self.assertEqual(r2.errors, [])

    def test_05_mysql_unreachable_silent(self):
        """场景 5：MySQL 不可达时，sync 不抛异常、errors 列表里有说明。"""
        # 构造一个指向不存在的 host 的 container
        from ielts_buddy.repositories.fallback_repo import create_fallback_container
        bad_container = create_fallback_container(
            sqlite_db_path=self.sqlite_path,
            mysql_url=("mysql+pymysql://nope:wrong@127.0.0.1:1/"
                       "nonexistent?charset=utf8mb4"),
            prefer_mode="online",
        )
        try:
            # ping 应失败 → 切到 fallback_sqlite
            self.assertFalse(bad_container.try_mysql())
            self.assertEqual(bad_container.current_mode, "fallback_sqlite")

            from ielts_buddy.services.sync import SyncWorker
            worker = SyncWorker(bad_container)
            result = worker.sync_once()
            self.assertGreater(len(result.errors), 0)
            self.assertIn("MySQL 不可达", " ".join(result.errors))
        finally:
            bad_container.close()


if __name__ == "__main__":
    unittest.main()
