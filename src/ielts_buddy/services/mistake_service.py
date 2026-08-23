"""错词本服务（v3.6 新增）。

封装 ``learning_records`` 中 wrong_count > 0 的查询 / 聚合，
并提供"自动入 mistakes 分类"的能力。

设计：
- 复用 learning_records 既有 wrong_count 字段 —— 不新建事件级错词日志表
- ``record_mistake`` 在 quiz/study/listening/exam 答错时被调用,自动:
    1) +1 wrong_count(由 upsert_record 完成)
    2) 加入 personal_vocab.mistakes 系统分类(对齐 CLI 行为)
- ``list_wrong_words`` 给 web /mistakes 页面用,按 wrong_count DESC 排序
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ielts_buddy.core.models import Word

logger = logging.getLogger(__name__)


class MistakeService:
    """错词本服务。直接绑定业务容器(同时持有 learning + personal_vocab repo)。

    Args:
        container: 业务容器(支持 learning / personal_vocab 属性)
        user_id: 当前 web 用户 id
    """

    def __init__(self, container: Any, user_id: int) -> None:
        self._container = container
        self._user_id = user_id

    # =============================================================
    # 写:答错时调用
    # =============================================================

    def record_mistake(self, word: Word | str, source: str = "mistake_auto") -> None:
        """答错时调用:把词加入 personal_vocab.mistakes 分类(去重)。

        注意 wrong_count +1 由上游 upsert_record 完成,本方法只负责 personal_vocab。
        若词不在 vocab_svc 索引里,会创建一个最小的 PersonalWord(meaning="", band=5)。
        """
        try:
            if not hasattr(self._container, "personal_vocab"):
                return
            # 兼容 str 和 Word
            from ielts_buddy.core.models import PersonalWord
            word_text = word.word if hasattr(word, "word") else str(word)
            if isinstance(word, Word):
                pw = PersonalWord(
                    word=word.word,
                    phonetic=getattr(word, "phonetic", "") or "",
                    meaning=getattr(word, "meaning", "") or "",
                    pos=getattr(word, "pos", "") or "",
                    band=getattr(word, "band", 5) or 5,
                    topic=getattr(word, "topic", "") or "",
                    example=getattr(word, "example", "") or "",
                    example_cn=getattr(word, "example_cn", "") or "",
                )
            else:
                pw = PersonalWord(word=word_text, meaning="", band=5)
            self._container.personal_vocab.add_mistake(
                self._user_id, pw, source=source
            )
        except Exception:
            # 错词本收录失败不应阻塞主答题流程
            logger.warning(
                "[mistake_service] record_mistake failed for %r", word_text, exc_info=True
            )

    # =============================================================
    # 读:web /mistakes 页面
    # =============================================================

    def list_wrong_words(
        self,
        min_wrong: int = 1,
        days: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """按 wrong_count DESC 返回错词列表(每个 dict 含 word/word_data/wrong_count/...)"""
        if not hasattr(self._container, "learning"):
            return []
        return self._container.learning.get_wrong_words(
            self._user_id,
            min_wrong=min_wrong,
            days=days,
            limit=limit,
        )

    def get_stats(self) -> dict:
        """聚合统计(distinct_words / total_wrong / last_7d / top_offenders)。"""
        if not hasattr(self._container, "learning"):
            return {
                "distinct_words": 0,
                "total_wrong_count": 0,
                "last_7d_wrong": 0,
                "top_offenders": [],
            }
        return self._container.learning.get_mistake_stats(self._user_id)

    # =============================================================
    # 异步包装(给 web router 用)
    # =============================================================

    async def alist_wrong_words(self, **kwargs) -> list:
        return await asyncio.to_thread(self.list_wrong_words, **kwargs)

    async def aget_stats(self) -> dict:
        return await asyncio.to_thread(self.get_stats)

    async def arecord_mistake(self, word, source: str = "mistake_auto") -> None:
        await asyncio.to_thread(self.record_mistake, word, source)


__all__ = ["MistakeService"]