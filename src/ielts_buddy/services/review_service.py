"""复习服务：基于艾宾浩斯遗忘曲线的间隔重复，使用 SQLite 存储学习记录

W2 阶段：所有 SQL 调用委托给 SQLiteLearningRepository。
W4 阶段：未传 db_path 时按 config.mode 选 local/online 容器。
W5 阶段：未传 user_id 时按 get_user_id() 解析（env > config > 1）。
公开 API 保持不变（commands 层和测试无需修改）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ielts_buddy.core.models import LearningRecord, Word
from ielts_buddy.repositories import REVIEW_INTERVALS, create_repositories

# 艾宾浩斯复习间隔（天数），memory_level 0-6 对应
__all__ = ["ReviewService", "REVIEW_INTERVALS", "_next_review_date"]


# 向后兼容：原 review_service.py 内部 helper
def _next_review_date(today_str: str, level: int) -> str:
    """根据记忆等级计算下次复习日期（向后兼容原 review_service 公开 helper）"""
    from datetime import date, timedelta
    today = date.fromisoformat(today_str)
    interval = REVIEW_INTERVALS[min(level, len(REVIEW_INTERVALS) - 1)]
    return (today + timedelta(days=interval)).isoformat()


class ReviewService:
    """艾宾浩斯复习服务（W2: 委托给 Repository）"""

    def __init__(self, db_path: Path | None = None, user_id: int | None = None) -> None:
        # 显式传 db_path = 强制走 local（保持旧测试 / 旧调用方行为不变）
        if db_path is not None:
            self._container = create_repositories(mode="local", db_path=db_path)
        else:
            from ielts_buddy.core.config import Config, get_mode
            cfg = Config()
            mode = get_mode(cfg)
            self._container = create_repositories(mode=mode)
        # 每次构造都建独立 container（与原版 conn 生命周期一致）
        # 关闭时调用 .close()
        self._repo = self._container.learning
        # W5: user_id 显式传 > get_user_id() 解析 > 1
        if user_id is not None:
            self._user_id = user_id
        else:
            from ielts_buddy.core.config import Config, get_user_id
            self._user_id = get_user_id(Config())  # 单机模式默认 1

    def close(self) -> None:
        self._container.close()

    # ---- 向后兼容属性（旧版测试代码访问 _conn / _db_path） ----

    @property
    def _conn(self):
        """向后兼容：旧版测试直接用 service._conn 查表。"""
        return self._container._conn

    @property
    def _db_path(self) -> Path:
        """向后兼容：旧版测试用 service._db_path 读路径。"""
        return self._container._db_path

    # ---- 学习记录管理 ----

    def record_learn(self, word: Word, correct: bool, source: str = "builtin") -> LearningRecord:
        """记录一次学习/复习结果，并更新下次复习时间（向后兼容 API）"""
        return self._repo.upsert_record(self._user_id, word, correct, source)

    def _get_record(self, word: str) -> LearningRecord:
        """内部使用：获取单词的学习记录"""
        rec = self._repo.get_record(self._user_id, word)
        if rec is None:
            raise ValueError(f"未找到单词 '{word}' 的学习记录")
        return rec

    # ---- 复习计划 ----

    def get_due_words(self, limit: int = 20) -> list[dict]:
        """获取今天需要复习的单词，返回 [{word, word_data, record}, ...]"""
        return self._repo.get_due_words(self._user_id, limit)

    def get_due_count(self) -> int:
        """获取今天待复习的单词数量"""
        return self._repo.get_due_count(self._user_id)

    # ---- 查询 ----

    def get_all_records(self) -> list[LearningRecord]:
        """获取所有学习记录"""
        return self._repo.get_all_records(self._user_id)

    def get_learned_count(self) -> int:
        """获取已学习的单词总数"""
        return self._repo.get_learned_count(self._user_id)

    def toggle_star(self, word: str) -> bool:
        """切换单词的星标状态，返回新状态"""
        return self._repo.toggle_star(self._user_id, word)
