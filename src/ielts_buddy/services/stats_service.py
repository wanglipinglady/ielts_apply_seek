"""学习统计服务：今日/总计学习数据、正确率、连续学习天数、趋势等

W2 阶段：所有 SQL 调用委托给 SQLiteLearningRepository。
W4 阶段：未传 db_path 时按 config.mode 选 local/online 容器。
W5 阶段：未传 user_id 时按 get_user_id() 解析（env > config > 1）。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from ielts_buddy.repositories import create_repositories


class StatsService:
    """学习统计服务（W2: 委托给 Repository；W4: 模式分发；W5: user_id 注入）"""

    def __init__(self, db_path: Path | None = None, user_id: int | None = None) -> None:
        # 显式传 db_path = 强制走 local（保持旧测试 / 旧调用方行为不变）
        if db_path is not None:
            self._container = create_repositories(mode="local", db_path=db_path)
        else:
            # 走配置：环境变量 / 配置文件决定 local 或 online
            from ielts_buddy.core.config import Config, get_mode
            cfg = Config()
            mode = get_mode(cfg)
            self._container = create_repositories(mode=mode)
        self._repo = self._container.learning
        # W5: user_id 显式传 > get_user_id() 解析 > 1
        if user_id is not None:
            self._user_id = user_id
        else:
            from ielts_buddy.core.config import Config, get_user_id
            self._user_id = get_user_id(Config())

    def close(self) -> None:
        self._container.close()

    # ---- 向后兼容 ----

    @property
    def _conn(self):
        return self._container._conn

    @property
    def _db_path(self) -> Path:
        return self._container._db_path

    def _table_exists(self) -> bool:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='learning_records'"
        ).fetchone()
        return row is not None

    # ---- 统计方法 ----

    def total_stats(self) -> dict:
        """获取总体统计数据"""
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

    def today_stats(self) -> dict:
        """获取今日学习统计"""
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
            "SELECT COUNT(*) as cnt FROM learning_records WHERE user_id = ? AND first_learned LIKE ?",
            (self._user_id, f"{today}%"),
        ).fetchone()
        review_row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM learning_records WHERE user_id = ? AND last_reviewed LIKE ?",
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
        """获取待复习单词数量"""
        if not self._table_exists():
            return 0
        return self._repo.get_due_count(self._user_id)

    def level_distribution(self) -> dict[int, int]:
        """获取记忆等级分布"""
        if not self._table_exists():
            return {}
        rows = self._conn.execute(
            """SELECT memory_level, COUNT(*) as cnt
               FROM learning_records WHERE user_id = ?
               GROUP BY memory_level
               ORDER BY memory_level""",
            (self._user_id,),
        ).fetchall()
        return {row["memory_level"]: row["cnt"] for row in rows}

    def get_streak(self) -> tuple[int, int]:
        """获取连续学习天数: (当前连续天数, 历史最长连续天数)"""
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
        """获取每日学习趋势: [(日期, 学习数, 正确率), ...]"""
        history = self._repo.get_history(self._user_id, days=days)
        return [(h["date"], h["new_words"] + h["reviewed_words"], 0.0) for h in history]

    def get_band_progress(self) -> list[tuple[int, int, int, float]]:
        """获取各Band掌握进度"""
        from ielts_buddy.services.vocab_service import VocabService

        vocab_svc = VocabService()
        vocab_svc.load_all()
        band_totals = vocab_svc.get_vocab_stats()["bands"]

        if not self._table_exists():
            return [(band, total, 0, 0.0) for band, total in sorted(band_totals.items())]

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

    def get_history(self, days: int = 7) -> list[dict]:
        """获取学习历史: [{date, new_words, reviewed_words}, ...]"""
        if not self._table_exists():
            today = date.today()
            start = today - timedelta(days=days - 1)
            return [
                {"date": (start + timedelta(days=i)).isoformat(), "new_words": 0, "reviewed_words": 0}
                for i in range(days)
            ]
        return self._repo.get_history(self._user_id, days=days)
