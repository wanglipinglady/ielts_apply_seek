"""联网查词路由：内置词库 → 词典 API + MyMemory 翻译 → LLM 三层 fallback。

GET /api/lookup/word?word=xxx
- 第一层命中内置词库（4770 词，免费 O(1)）
- 第二层调用 free dictionary API（无 key，免费，约 1s）+ MyMemory 翻译英中（无 key，免费，并行）
- 第三层调用 LLM（需 API key，最准确，约 3-10s）
- LLM 未配置时返回 mock 数据（dry-run）

设计要点：
1. 词典 API 命中后**并行**调 MyMemory 翻译英文→中文（不阻塞）
2. MyMemory 翻译失败/低质量（quality<0.5）→ 仍用英文释义，让用户手填
3. LLM 第三层只在"词典 API 也查不到"时触发
4. dry-run 模式下 LLM 返回 mock 占位符
"""
from __future__ import annotations

import asyncio
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query

from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.llm_service import get_llm_service
from ielts_buddy.web.lookup_client import DictionaryClient
from ielts_buddy.web.services import get_vocab_service
from ielts_buddy.web.translation_client import MyMemoryClient


api_router = APIRouter(prefix="/api/lookup", tags=["lookup"])


# 单例客户端
_dict_client: Optional[DictionaryClient] = None
_translate_client: Optional[MyMemoryClient] = None


def _get_dict_client() -> DictionaryClient:
    global _dict_client
    if _dict_client is None:
        _dict_client = DictionaryClient(timeout=8.0, max_retries=1)
    return _dict_client


def _get_translate_client() -> MyMemoryClient:
    global _translate_client
    if _translate_client is None:
        _translate_client = MyMemoryClient(timeout=4.0)
    return _translate_client


async def _translate_to_cn(text: str) -> str:
    """异步翻译英文到中文；返回空字符串表示失败。"""
    if not text:
        return ""
    client = _get_translate_client()
    try:
        result = await client.translate(text)
        if result and result.is_valid() and result.quality >= 0.5:
            return result.translated
    except Exception:
        pass
    return ""


@api_router.get("/word")
async def api_lookup_word(
    word: Annotated[str, Query(min_length=1, max_length=100)],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
) -> dict:
    """联网查单词：内置词库 → 词典 API + MyMemory 翻译 → LLM 三层 fallback。

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
            "phonetic_system": "dj",           # 内置词库用的是 DJ/教材音标
            "phonetic_region": "",             # 混合英美，不特指
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

    # ========== 第二层：词典 API + MyMemory 翻译（并行）==========
    dict_client = _get_dict_client()
    dict_result = None
    try:
        dict_result = await dict_client.lookup(word_clean)
    except Exception as e:
        from ielts_buddy.web.llm_service import logger as _logger
        _logger.warning(f"Dictionary API lookup failed: {e}")

    if dict_result and not dict_result.is_empty():
        # 并行翻译英文释义 + 例句 → 中文
        # MyMemory 失败/低质量时仍返回英文，前端用户可手动修改
        meaning_cn, example_cn = await asyncio.gather(
            _translate_to_cn(dict_result.meaning_en or ""),
            _translate_to_cn(dict_result.example or ""),
        )
        # 翻译质量决定 confidence：有中文释义 → high，否则 medium
        confidence = "high" if meaning_cn else "medium"
        return {
            "word": word_clean,
            "phonetic": dict_result.phonetic,
            "phonetic_system": dict_result.phonetic_system,  # "ipa" / "dj"
            "phonetic_region": dict_result.phonetic_region,  # "us" / "au"
            "pos": dict_result.pos,
            "meaning_cn": meaning_cn,           # MyMemory 翻译（可能空）
            "meaning_en": dict_result.meaning_en,
            "example": dict_result.example,
            "example_cn": example_cn,
            "band": None,
            "topic": "",
            "source": "dictionary_api",
            "confidence": confidence,
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
        "source": llm_result.source,
        "confidence": llm_result.confidence,
    }


__all__ = ["api_router"]