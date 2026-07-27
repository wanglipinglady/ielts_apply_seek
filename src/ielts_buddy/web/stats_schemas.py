"""Pydantic 响应模型（阶段 2：Dashboard + Stats）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StatsSummary(BaseModel):
    """Dashboard 上要展示的精简数字（首页"卡片"用）。"""

    # 今日
    today_new_words: int = 0          # 今日新学
    today_reviewed: int = 0          # 今日复习
    # 累计
    total_words: int = 0             # 总学过的词数
    total_reviews: int = 0           # 累计复习次数
    total_correct: int = 0           # 累计正确
    total_wrong: int = 0             # 累计错误
    accuracy: float = 0.0            # 累计正确率
    mastered: int = 0                # memory_level>=5 视为"掌握"
    # 待办
    due_count: int = 0               # 今天待复习
    # 连续
    current_streak: int = 0          # 当前连续学习天数
    max_streak: int = 0              # 历史最长


class LevelDistributionItem(BaseModel):
    level: int
    count: int


class BandProgressItem(BaseModel):
    band: int
    total: int           # 词库中 band 的总词数
    mastered: int        # memory_level >= 4 的数量
    ratio: float         # mastered / total


class DailyTrendItem(BaseModel):
    date: str
    studied: int         # 当日学习 + 复习总数


class StatsOverview(BaseModel):
    """Stats 页面要展示的全量数据。"""

    summary: StatsSummary
    level_distribution: list[LevelDistributionItem]
    band_progress: list[BandProgressItem]
    trend: list[DailyTrendItem]


__all__ = [
    "StatsSummary",
    "LevelDistributionItem",
    "BandProgressItem",
    "DailyTrendItem",
    "StatsOverview",
]
