"""Web 端统计服务：直 SQL 读 ``learning_records``，对应 ``ielts_buddy.web`` 子包。

为什么不复用 ``ielts_buddy.services.stats_service.StatsService``：
- 后者用 ``self._conn`` 拿连接，假设连接在"调用方"线程里打开；
- FastAPI 同步端点在 threadpool 跑，连接被多个 worker 共享会爆
  ``SQLite objects created in a thread can only be used in that same thread``；
- StatsService 直接走 sqlite3.Connection，不走 Repository 抽象，绕过了
  ``check_same_thread=False`` 的兼容能力。

本服务：
- 用 lifespan 阶段打开的 ``check_same_thread=False`` 连接；
- 业务方法签名（返回值结构）跟 CLI ``StatsService`` 对齐，前端模板不感知差异；
- 不动 services / repositories 两层代码，零侵入。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any


class WebStatsService:
    """Web 端统计服务（阶段 2）。"""

    def __init__(self, conn: sqlite3.Connection, user_id: int) -> None:
        self._conn = conn
        self._user_id = user_id

    # ---- 内部 ----

    def _table_exists(self) -> bool:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='learning_records'"
        ).fetchone()
        return row is not None

    # ---- 业务方法（与 services/stats_service.py 对齐） ----

    def total_stats(self) -> dict[str, Any]:
        """累计统计。"""
        if not self._table_exists():
            return {
                "total_words": 0,
                "total_reviews": 0,
                "total_correct": 0,
                "total_wrong": 0,
                "accuracy": 0.0,
                "mastered": 0,
            }
        row = self._conn.execute(
            """SELECT
               COUNT(*) as total_words,
               COALESCE(SUM(learn_count), 0) as total_reviews,
               COALESCE(SUM(correct_count), 0) as total_correct,
               COALESCE(SUM(wrong_count), 0) as total_wrong,
               COUNT(CASE WHEN memory_level >= 5 THEN 1 END) as mastered
               FROM learning_records WHERE user_id = ?""",
            (self._user_id,),
        ).fetchone()

        total_attempts = row["total_correct"] + row["total_wrong"]
        accuracy = row["total_correct"] / total_attempts if total_attempts > 0 else 0.0
        return {
            "total_words": row["total_words"],
            "total_reviews": row["total_reviews"],
            "total_correct": row["total_correct"],
            "total_wrong": row["total_wrong"],
            "accuracy": accuracy,
            "mastered": row["mastered"],
        }

    def today_stats(self) -> dict[str, Any]:
        """今日统计。"""
        if not self._table_exists():
            return {
                "new_words": 0,
                "reviewed_words": 0,
                "correct": 0,
                "wrong": 0,
                "accuracy": 0.0,
            }
        today = date.today().isoformat()
        new_row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM learning_records "
            "WHERE user_id = ? AND first_learned LIKE ?",
            (self._user_id, f"{today}%"),
        ).fetchone()
        review_row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM learning_records "
            "WHERE user_id = ? AND last_reviewed LIKE ?",
            (self._user_id, f"{today}%"),
        ).fetchone()
        return {
            "new_words": new_row["cnt"],
            "reviewed_words": review_row["cnt"],
            "correct": 0,
            "wrong": 0,
            "accuracy": 0.0,
        }

    def due_count(self) -> int:
        """今日待复习数。"""
        if not self._table_exists():
            return 0
        today = date.today().isoformat()
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM learning_records "
            "WHERE user_id = ? AND next_review <= ?",
            (self._user_id, today),
        ).fetchone()
        return row["cnt"]

    def level_distribution(self) -> dict[int, int]:
        """记忆等级分布。"""
        if not self._table_exists():
            return {}
        rows = self._conn.execute(
            """SELECT memory_level, COUNT(*) as cnt
               FROM learning_records WHERE user_id = ?
               GROUP BY memory_level ORDER BY memory_level""",
            (self._user_id,),
        ).fetchall()
        return {row["memory_level"]: row["cnt"] for row in rows}

    def get_streak(self) -> tuple[int, int]:
        """连续学习天数: (当前连续, 历史最长)。"""
        if not self._table_exists():
            return (0, 0)
        rows = self._conn.execute(
            """SELECT DISTINCT DATE(last_reviewed) as study_date
               FROM learning_records
               WHERE user_id = ? AND last_reviewed IS NOT NULL
               ORDER BY study_date DESC""",
            (self._user_id,),
        ).fetchall()
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
        """最近 N 天每日学习数: [(date, studied, accuracy), ...]。

        每日 studied = 当日 new + reviewed。
        """
        if not self._table_exists():
            today = date.today()
            start = today - timedelta(days=days - 1)
            return [
                ((start + timedelta(days=i)).isoformat(), 0, 0.0)
                for i in range(days)
            ]
        today = date.today()
        start = today - timedelta(days=days - 1)
        rows = self._conn.execute(
            """SELECT
               DATE(COALESCE(first_learned, last_reviewed)) as d,
               COUNT(DISTINCT CASE WHEN DATE(first_learned) = DATE(COALESCE(first_learned, last_reviewed)) THEN word END) as new_cnt,
               COUNT(DISTINCT CASE WHEN DATE(last_reviewed) = DATE(COALESCE(first_learned, last_reviewed)) THEN word END) as rev_cnt
               FROM learning_records
               WHERE user_id = ? AND DATE(COALESCE(first_learned, last_reviewed)) >= ?
               GROUP BY d ORDER BY d""",
            (self._user_id, start.isoformat()),
        ).fetchall()
        # 用 dict 方便补齐没有数据的日期
        by_date = {row["d"]: row["new_cnt"] + row["rev_cnt"] for row in rows}
        return [
            ((start + timedelta(days=i)).isoformat(),
             by_date.get((start + timedelta(days=i)).isoformat(), 0),
             0.0)
            for i in range(days)
        ]

    def get_band_progress(self) -> list[tuple[int, int, int, float]]:
        """各 Band 掌握进度: [(band, total, mastered, ratio), ...]。

        复用内置词库统计：仅在 web_data.db 没建词库表时退化为 0。
        """
        if not self._table_exists():
            # 没学习记录直接返回空
            return []
        # 从词库加载的内存词表（已 lru_cache 共享）统计 band 总量
        from ielts_buddy.web.services import _vocab_service_singleton

        vocab = _vocab_service_singleton()
        stats = vocab.get_vocab_stats()
        band_totals = stats.get("bands", {})

        rows = self._conn.execute(
            "SELECT word_data, memory_level FROM learning_records WHERE user_id = ?",
            (self._user_id,),
        ).fetchall()

        band_mastered: dict[int, int] = {}
        for row in rows:
            try:
                word_data = json.loads(row["word_data"])
                band = word_data.get("band", 0)
                if row["memory_level"] >= 4:
                    band_mastered[band] = band_mastered.get(band, 0) + 1
            except (json.JSONDecodeError, KeyError):
                continue

        result = []
        for band, total in sorted(band_totals.items()):
            mastered = band_mastered.get(band, 0)
            ratio = mastered / total if total > 0 else 0.0
            result.append((band, total, mastered, ratio))
        return result

    def get_history(self, days: int = 7) -> list[dict[str, Any]]:
        """历史聚合: [{date, new_words, reviewed_words}, ...]。"""
        if not self._table_exists():
            today = date.today()
            start = today - timedelta(days=days - 1)
            return [
                {
                    "date": (start + timedelta(days=i)).isoformat(),
                    "new_words": 0,
                    "reviewed_words": 0,
                }
                for i in range(days)
            ]
        return self.get_daily_trend(days)


__all__ = ["WebStatsService"]
