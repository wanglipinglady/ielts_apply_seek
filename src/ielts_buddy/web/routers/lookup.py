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
5. ``resolve_word_metadata()`` 是核心 helper，
   既给 ``/api/lookup/word`` 用，也给 ``/api/personal/words/batch`` 批量加入时用
"""
from __future__ import annotations

import asyncio
from typing import Annotated, Any, Optional

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


async def _maybe_convert_to_dj(
    llm, word: str, ipa_phonetic: str, phonetic_system: str
) -> str:
    """异步调用 LLM 把 IPA 转 DJ 音标；无 key/失败时返回空字符串。

    返回空字符串让上层 fallback 到原 IPA（不阻塞主流程）。
    只在输入是 IPA 时才转写；已是 DJ 时直接跳过。
    """
    if not ipa_phonetic or phonetic_system != "ipa":
        return ""
    if not llm.is_available():
        return ""
    # LLM 调用是同步的；放进 asyncio.to_thread 不阻塞事件循环
    try:
        result = await asyncio.to_thread(
            llm.convert_to_dj_phonetic, word, ipa_phonetic
        )
        return result or ""
    except Exception:
        return ""


async def resolve_word_metadata(
    word: str, vocab: VocabService
) -> dict[str, Any]:
    """三层 fallback 查词元数据（内置词库 → 词典 API → LLM）。

    返回结构与 ``/api/lookup/word`` 完全一致，但作为 helper 给其他路由复用
    （如 ``POST /api/personal/words/batch`` 批量加入时也走相同链路补全释义）。

    返回字段：
    - word / phonetic / phonetic_system / phonetic_region
    - pos / meaning_cn / meaning_en / example / example_cn
    - band / topic / source / confidence
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
        # 并行：MyMemory 翻译 + LLM IPA→DJ 音标转写
        # - MyMemory：英译中（无 key 免费）
        # - LLM 转音标：仅在 LLM 已配置 + 词典返回 IPA 时执行；
        #   否则返回原 IPA（不阻塞主流程）
        llm = get_llm_service()
        phonetic_task = _maybe_convert_to_dj(
            llm, word_clean, dict_result.phonetic, dict_result.phonetic_system,
        )
        meaning_cn, example_cn, dj_phonetic = await asyncio.gather(
            _translate_to_cn(dict_result.meaning_en or ""),
            _translate_to_cn(dict_result.example or ""),
            phonetic_task,
        )

        # 优先用 LLM 转写的 DJ 音标（若有），否则用原 IPA
        final_phonetic = dj_phonetic or dict_result.phonetic
        # phonetic_system：DJ 转写成功 → "dj"，否则沿用上游（"ipa"）
        final_phonetic_system = (
            "dj" if dj_phonetic and dj_phonetic != dict_result.phonetic
            else dict_result.phonetic_system
        )
        # 翻译质量决定 confidence：有中文释义 → high，否则 medium
        confidence = "high" if meaning_cn else "medium"
        return {
            "word": word_clean,
            "phonetic": final_phonetic,
            "phonetic_system": final_phonetic_system,  # "ipa" / "dj"
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


@api_router.get("/word")
async def api_lookup_word(
    word: Annotated[str, Query(min_length=1, max_length=100)],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
) -> dict:
    """联网查单词：内置词库 → 词典 API + MyMemory 翻译 → LLM 三层 fallback。

    返回字段：见 ``resolve_word_metadata()``。
    """
    return await resolve_word_metadata(word, vocab)


__all__ = ["api_router", "resolve_word_metadata"]