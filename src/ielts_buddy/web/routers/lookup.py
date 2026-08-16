"""联网查词路由：内置词库 → 词典 API → LLM 三层 fallback。

GET /api/lookup/word?word=xxx
- 第一层命中内置词库（4770 词，免费 O(1)）
- 第二层调用 free dictionary API（无 key，免费，约 1s）
- 第三层调用 LLM（需 API key，最准确，约 3-10s）
- LLM 未配置时返回 mock 数据（dry-run）

设计要点：
1. 词典 API 命中后**不再强行等 LLM 翻译**：用英文释义直接返回，
   confidence 标记为 medium；中文用户能在前端手动翻译
2. LLM 第三层只用于"词典 API 也查不到"的兜底
3. dry-run 模式下 LLM 返回 mock 占位符，让前端可演示
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.llm_service import get_llm_service
from ielts_buddy.web.lookup_client import DictionaryClient
from ielts_buddy.web.services import get_vocab_service


api_router = APIRouter(prefix="/api/lookup", tags=["lookup"])


# 单例 DictionaryClient
_dict_client: DictionaryClient | None = None


def _get_dict_client() -> DictionaryClient:
    global _dict_client
    if _dict_client is None:
        # 超时 8s + 重试 1 次：公共服务不稳定，给足时间
        _dict_client = DictionaryClient(timeout=8.0, max_retries=1)
    return _dict_client


@api_router.get("/word")
async def api_lookup_word(
    word: Annotated[str, Query(min_length=1, max_length=100)],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
) -> dict:
    """联网查单词：内置词库 → 词典 API → LLM 三层 fallback。

    返回字段：
    - word: 查询的单词
    - phonetic: 音标
    - pos: 词性
    - meaning_cn: 中文释义
    - meaning_en: 英文释义
    - example: 例句
    - example_cn: 例句中文
    - band: 词库 band（内置词库命中才有）
    - topic: 主题（内置词库命中才有）
    - source: builtin / dictionary_api / llm / mock / none
    - confidence: high / medium / low
    """
    word_clean = word.strip()
    if not word_clean:
        return {"word": "", "source": "none"}

    # ========== 第一层：内置词库（O(1)）==========
    db_word = vocab.get_word(word_clean)
    if db_word is not None and db_word.meaning:
        return {
            "word": db_word.word,
            "phonetic": db_word.phonetic or "",
            "pos": db_word.pos or "",
            "meaning_cn": db_word.meaning,
            "meaning_en": "",
            "example": db_word.example or "",
            "example_cn": db_word.example_cn or "",
            "band": db_word.band,
            "topic": db_word.topic or "",
            "source": "builtin",
            "confidence": "high",
        }

    # ========== 第二层：free dictionary API（异步，4s 超时）==========
    dict_client = _get_dict_client()
    dict_result = None
    try:
        dict_result = await dict_client.lookup(word_clean)
    except Exception as e:
        from ielts_buddy.web.llm_service import logger as _logger
        _logger.warning(f"Dictionary API lookup failed: {e}")

    if dict_result and not dict_result.is_empty():
        # 词典 API 命中 → 直接返回英文释义（中文用户可手动修改）
        # 不再阻塞等 LLM 翻译
        return {
            "word": word_clean,
            "phonetic": dict_result.phonetic,
            "pos": dict_result.pos,
            "meaning_cn": "",                  # 空：让用户填或编辑
            "meaning_en": dict_result.meaning_en,
            "example": dict_result.example,
            "example_cn": "",
            "band": None,
            "topic": "",
            "source": "dictionary_api",
            "confidence": "high",
        }

    # ========== 第三层：LLM 兜底（slow but accurate）==========
    llm = get_llm_service()
    llm_result = llm.lookup_word(word_clean)
    return {
        "word": llm_result.word,
        "phonetic": llm_result.phonetic,
        "pos": llm_result.pos,
        "meaning_cn": llm_result.meaning_cn,
        "meaning_en": llm_result.meaning_en,
        "example": llm_result.example,
        "example_cn": llm_result.example_cn,
        "band": None,
        "topic": "",
        "source": llm_result.source,  # llm / mock / error
        "confidence": llm_result.confidence,
    }


__all__ = ["api_router"]