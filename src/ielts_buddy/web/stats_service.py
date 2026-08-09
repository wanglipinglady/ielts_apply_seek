"""Web 端统计服务：通过业务容器读 ``learning_records``。

设计：原本走 ``web_stats_conn``（SQLite-only），导致 MySQL 模式下 web 端 stats
和 study 全部 RuntimeError。现在改为走业务容器，SQLite / MySQL 都自动适配。

执行策略：
- SQLite 模式：直接 sqlite3.Connection，使用 ``?`` 占位符
- MySQL 模式：SQLAlchemy Engine，使用 SQLAlchemy Core ``text()`` + ``:param``
  关键：``conn.execute(text(sql))`` 时如果 conn 是 Engine，会自动开新连接；
  如果是 Connection，可以直接 execute。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Optional, Union


class WebStatsService:
    """Web 端统计服务。

    Args:
        connection: 业务容器的连接对象
            - SQLite 模式：``sqlite3.Connection``
            - MySQL 模式：``sqlalchemy.Engine``
        user_id: 当前 web 用户 id
    """

    def __init__(self, connection, user_id: int) -> None:
        self._conn = connection
        self._user_id = user_id
        # 检测执行风格
        import sqlite3 as _sqlite3
        self._is_sqlite = isinstance(connection, _sqlite3.Connection)

    # ---- 内部辅助 ----

    def _exec(self, sql: str, params: tuple = ()) -> list:
        """统一执行 SQL。

        SQLite: ``conn.execute(sql, params)`` 走原生 sqlite3 + ? 占位符
        MySQL: SQLAlchemy 2.0+ — Engine 没有 .execute()，必须先 .connect()
               然后在 with 块里 execute。with 块确保连接自动关闭。

        返回 list[dict]，统一字段访问。
        关键：MySQL 的 DATE() 返回 ``datetime.date`` 对象，stats_service 用
        ``date.fromisoformat()`` 处理；这里转成字符串避免类型不一致。
        """
        if self._is_sqlite:
            cur = self._conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
        else:
            from sqlalchemy import text
            from datetime import date as _date, datetime as _datetime
            t = text(sql)
            with self._conn.connect() as conn:
                result = conn.execute(t, params)
                rows = []
                for row in result:
                    m = dict(row._mapping)
                    # 规范化 date/datetime → isoformat 字符串
                    for k, v in list(m.items()):
                        if isinstance(v, (_date, _datetime)):
                            m[k] = v.isoformat()
                    rows.append(m)
                return rows

    def _exec_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        rows = self._exec(sql, params)
        return rows[0] if rows else None

    # ---- 业务方法 ----

    def total_stats(self) -> dict[str, Any]:
        """累计统计。"""
        # SQLite 用 ?，MySQL 用 :param — 写两套 SQL 略繁琐
        # 这里直接走 SQLAlchemy Core：SQLite 也支持 :param（通过 sqlite3 内部）
        # 但 sqlite3.Connection 不接受 text()；所以分支写两份 SQL
        try:
            if self._is_sqlite:
                row = self._exec_one(
                    """SELECT
                       COUNT(*) as total_words,
                       COALESCE(SUM(learn_count), 0) as total_reviews,
                       COALESCE(SUM(correct_count), 0) as total_correct,
                       COALESCE(SUM(wrong_count), 0) as total_wrong,
                       SUM(CASE WHEN memory_level >= 5 THEN 1 ELSE 0 END) as mastered
                       FROM learning_records WHERE user_id = ?""",
                    (self._user_id,),
                )
            else:
                row = self._exec_one(
                    """SELECT
                       COUNT(*) as total_words,
                       COALESCE(SUM(learn_count), 0) as total_reviews,
                       COALESCE(SUM(correct_count), 0) as total_correct,
                       COALESCE(SUM(wrong_count), 0) as total_wrong,
                       SUM(CASE WHEN memory_level >= 5 THEN 1 ELSE 0 END) as mastered
                       FROM learning_records WHERE user_id = :uid""",
                    {"uid": self._user_id},
                )
        except Exception:
            return self._empty_total()

        if row is None:
            return self._empty_total()

        total_correct = row.get("total_correct") or 0
        total_wrong = row.get("total_wrong") or 0
        total_attempts = total_correct + total_wrong
        accuracy = total_correct / total_attempts if total_attempts > 0 else 0.0
        return {
            "total_words": row.get("total_words") or 0,
            "total_reviews": row.get("total_reviews") or 0,
            "total_correct": total_correct,
            "total_wrong": total_wrong,
            "accuracy": accuracy,
            "mastered": int(row.get("mastered") or 0),
        }

    @staticmethod
    def _empty_total() -> dict[str, Any]:
        return {
            "total_words": 0, "total_reviews": 0,
            "total_correct": 0, "total_wrong": 0,
            "accuracy": 0.0, "mastered": 0,
        }

    def today_stats(self) -> dict[str, Any]:
        """今日统计。"""
        today = date.today().isoformat()
        try:
            if self._is_sqlite:
                new_row = self._exec_one(
                    "SELECT COUNT(*) as cnt FROM learning_records "
                    "WHERE user_id = ? AND first_learned LIKE ?",
                    (self._user_id, f"{today}%"),
                )
                review_row = self._exec_one(
                    "SELECT COUNT(*) as cnt FROM learning_records "
                    "WHERE user_id = ? AND last_reviewed LIKE ?",
                    (self._user_id, f"{today}%"),
                )
            else:
                new_row = self._exec_one(
                    "SELECT COUNT(*) as cnt FROM learning_records "
                    "WHERE user_id = :uid AND first_learned LIKE :today",
                    {"uid": self._user_id, "today": f"{today}%"},
                )
                review_row = self._exec_one(
                    "SELECT COUNT(*) as cnt FROM learning_records "
                    "WHERE user_id = :uid AND last_reviewed LIKE :today",
                    {"uid": self._user_id, "today": f"{today}%"},
                )
        except Exception:
            return {
                "new_words": 0, "reviewed_words": 0,
                "correct": 0, "wrong": 0, "accuracy": 0.0,
            }
        return {
            "new_words": (new_row or {}).get("cnt", 0) or 0,
            "reviewed_words": (review_row or {}).get("cnt", 0) or 0,
            "correct": 0, "wrong": 0, "accuracy": 0.0,
        }

    def due_count(self) -> int:
        """今日待复习数。"""
        today = date.today().isoformat()
        try:
            if self._is_sqlite:
                row = self._exec_one(
                    "SELECT COUNT(*) as cnt FROM learning_records "
                    "WHERE user_id = ? AND next_review <= ?",
                    (self._user_id, today),
                )
            else:
                row = self._exec_one(
                    "SELECT COUNT(*) as cnt FROM learning_records "
                    "WHERE user_id = :uid AND next_review <= :today",
                    {"uid": self._user_id, "today": today},
                )
        except Exception:
            return 0
        return (row or {}).get("cnt", 0) or 0

    def level_distribution(self) -> dict[int, int]:
        """记忆等级分布。"""
        try:
            if self._is_sqlite:
                rows = self._exec(
                    """SELECT memory_level, COUNT(*) as cnt
                       FROM learning_records WHERE user_id = ?
                       GROUP BY memory_level ORDER BY memory_level""",
                    (self._user_id,),
                )
            else:
                rows = self._exec(
                    """SELECT memory_level, COUNT(*) as cnt
                       FROM learning_records WHERE user_id = :uid
                       GROUP BY memory_level ORDER BY memory_level""",
                    {"uid": self._user_id},
                )
        except Exception:
            return {}
        return {row["memory_level"]: row["cnt"] for row in rows}

    def get_streak(self) -> tuple[int, int]:
        """连续学习天数: (当前连续, 历史最长)。"""
        try:
            if self._is_sqlite:
                rows = self._exec(
                    """SELECT DISTINCT DATE(last_reviewed) as study_date
                       FROM learning_records
                       WHERE user_id = ? AND last_reviewed IS NOT NULL
                       ORDER BY study_date DESC""",
                    (self._user_id,),
                )
            else:
                rows = self._exec(
                    """SELECT DISTINCT DATE(last_reviewed) as study_date
                       FROM learning_records
                       WHERE user_id = :uid AND last_reviewed IS NOT NULL
                       ORDER BY study_date DESC""",
                    {"uid": self._user_id},
                )
        except Exception:
            return (0, 0)
        if not rows:
            return (0, 0)

        dates = [date.fromisoformat(row["study_date"]) for row in rows]
        today = date.today()

        current_streak = 0
        if dates[0] == today or dates[0] == today - timedelta(days=1):
            current_streak = 1
            for i in range(1, len(dates)):
                if dates[i] == dates[i - 1] - timedelta(days=1):
                    current_streak += 1
                else:
                    break

        max_streak = 1
        streak = 1
        for i in range(1, len(dates)):
            if dates[i] == dates[i - 1] - timedelta(days=1):
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 1
        max_streak = max(max_streak, streak)
        return (current_streak, max_streak)

    def get_daily_trend(self, days: int = 7) -> list[tuple[str, int, float]]:
        """最近 N 天每日学习数。"""
        today = date.today()
        start = today - timedelta(days=days - 1)
        try:
            if self._is_sqlite:
                rows = self._exec(
                    """SELECT
                       DATE(COALESCE(first_learned, last_reviewed)) as d,
                       COUNT(DISTINCT CASE WHEN DATE(first_learned) = DATE(COALESCE(first_learned, last_reviewed)) THEN word END) as new_cnt,
                       COUNT(DISTINCT CASE WHEN DATE(last_reviewed) = DATE(COALESCE(first_learned, last_reviewed)) THEN word END) as rev_cnt
                       FROM learning_records
                       WHERE user_id = ? AND DATE(COALESCE(first_learned, last_reviewed)) >= ?
                       GROUP BY d ORDER BY d""",
                    (self._user_id, start.isoformat()),
                )
            else:
                rows = self._exec(
                    """SELECT
                       DATE(COALESCE(first_learned, last_reviewed)) as d,
                       COUNT(DISTINCT CASE WHEN DATE(first_learned) = DATE(COALESCE(first_learned, last_reviewed)) THEN word END) as new_cnt,
                       COUNT(DISTINCT CASE WHEN DATE(last_reviewed) = DATE(COALESCE(first_learned, last_reviewed)) THEN word END) as rev_cnt
                       FROM learning_records
                       WHERE user_id = :uid AND DATE(COALESCE(first_learned, last_reviewed)) >= :start
                       GROUP BY d ORDER BY d""",
                    {"uid": self._user_id, "start": start.isoformat()},
                )
            by_date = {row["d"]: row["new_cnt"] + row["rev_cnt"] for row in rows}
        except Exception:
            by_date = {}
        return [
            ((start + timedelta(days=i)).isoformat(),
             by_date.get((start + timedelta(days=i)).isoformat(), 0),
             0.0)
            for i in range(days)
        ]

    def get_band_progress(self) -> list[tuple[int, int, int, float]]:
        """各 Band 掌握进度。"""
        from ielts_buddy.web.services import _vocab_service_singleton
        try:
            vocab = _vocab_service_singleton()
            stats = vocab.get_vocab_stats()
            band_totals = stats.get("bands", {})

            if self._is_sqlite:
                rows = self._exec(
                    "SELECT word_data, memory_level FROM learning_records WHERE user_id = ?",
                    (self._user_id,),
                )
            else:
                rows = self._exec(
                    "SELECT word_data, memory_level FROM learning_records WHERE user_id = :uid",
                    {"uid": self._user_id},
                )
            band_mastered: dict[int, int] = {}
            for row in rows:
                try:
                    word_data = json.loads(row["word_data"])
                    band = word_data.get("band", 0)
                    if (row["memory_level"] or 0) >= 4:
                        band_mastered[band] = band_mastered.get(band, 0) + 1
                except (json.JSONDecodeError, KeyError):
                    continue

            result = []
            for band, total in sorted(band_totals.items()):
                mastered = band_mastered.get(band, 0)
                ratio = mastered / total if total > 0 else 0.0
                result.append((band, total, mastered, ratio))
            return result
        except Exception:
            return []

    def get_history(self, days: int = 7) -> list[dict[str, Any]]:
        """历史聚合。"""
        today = date.today()
        start = today - timedelta(days=days - 1)
        try:
            if self._is_sqlite:
                rows = self._exec(
                    """SELECT DATE(first_learned) as d, COUNT(*) as new_cnt
                       FROM learning_records
                       WHERE user_id = ? AND DATE(first_learned) >= ?
                       GROUP BY d""",
                    (self._user_id, start.isoformat()),
                )
            else:
                rows = self._exec(
                    """SELECT DATE(first_learned) as d, COUNT(*) as new_cnt
                       FROM learning_records
                       WHERE user_id = :uid AND DATE(first_learned) >= :start
                       GROUP BY d""",
                    {"uid": self._user_id, "start": start.isoformat()},
                )
            new_by_date = {row["d"]: row["new_cnt"] for row in rows}

            if self._is_sqlite:
                rows = self._exec(
                    """SELECT DATE(last_reviewed) as d, COUNT(*) as rev_cnt
                       FROM learning_records
                       WHERE user_id = ? AND DATE(last_reviewed) >= ?
                       GROUP BY d""",
                    (self._user_id, start.isoformat()),
                )
            else:
                rows = self._exec(
                    """SELECT DATE(last_reviewed) as d, COUNT(*) as rev_cnt
                       FROM learning_records
                       WHERE user_id = :uid AND DATE(last_reviewed) >= :start
                       GROUP BY d""",
                    {"uid": self._user_id, "start": start.isoformat()},
                )
            rev_by_date = {row["d"]: row["rev_cnt"] for row in rows}
        except Exception:
            new_by_date, rev_by_date = {}, {}
        return [
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "new_words": new_by_date.get((start + timedelta(days=i)).isoformat(), 0),
                "reviewed_words": rev_by_date.get((start + timedelta(days=i)).isoformat(), 0),
            }
            for i in range(days)
        ]


class _nullctx:
    """占位上下文管理器（无操作）。"""
    def __enter__(self): return self
    def __exit__(self, *a): return False


__all__ = ["WebStatsService"]