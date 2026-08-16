"""联网查词典：调用 free dictionary API（dictionaryapi.dev）。

这是一个免费、无需 key 的英英词典 API。
文档：https://dictionaryapi.dev/

文档不够（没音标/中文）时由 LLMService 兜底。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# =============================================================
# 数据结构
# =============================================================


class DictionaryAPIResult:
    """词典 API 查询结果。"""

    def __init__(
        self,
        word: str,
        phonetic: str = "",
        pos: str = "",
        meaning_cn: str = "",
        meaning_en: str = "",
        example: str = "",
        example_cn: str = "",
    ):
        self.word = word
        self.phonetic = phonetic
        self.pos = pos
        self.meaning_cn = meaning_cn
        self.meaning_en = meaning_en
        self.example = example
        self.example_cn = example_cn

    def is_empty(self) -> bool:
        return not (self.phonetic or self.meaning_en or self.meaning_cn)


# =============================================================
# 客户端
# =============================================================


class DictionaryClient:
    """free dictionary API 客户端。"""

    BASE_URL = "https://api.dictionaryapi.dev/api/v2/entries/en"

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    async def lookup(self, word: str) -> Optional[DictionaryAPIResult]:
        """查询单词；返回 None 表示没找到 / 网络错误。"""
        word = word.strip().lower()
        if not word:
            return None
        url = f"{self.BASE_URL}/{word}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    return None
                if resp.status_code != 200:
                    logger.warning(f"词典 API 状态 {resp.status_code}: {word}")
                    return None
                data = resp.json()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning(f"词典 API 网络错误: {e}")
            return None
        except Exception as e:
            logger.warning(f"词典 API 解析错误: {e}")
            return None

        return self._parse(word, data)

    @staticmethod
    def _parse(word: str, data: list) -> Optional[DictionaryAPIResult]:
        """解析 dictionaryapi.dev 的响应。"""
        if not isinstance(data, list) or not data:
            return None
        entry = data[0]

        # 音标（可能在 phonetic 字段或在 phonetics 数组）
        phonetic = entry.get("phonetic", "") or ""
        if not phonetic:
            for p in entry.get("phonetics", []):
                if p.get("text"):
                    phonetic = p["text"]
                    break

        # 第一个 meaning
        meanings = entry.get("meanings", [])
        if not meanings:
            return DictionaryAPIResult(word=word, phonetic=phonetic)

        m = meanings[0]
        pos = m.get("partOfSpeech", "")

        # 释义（取第一个 definition）
        defs = m.get("definitions", [])
        meaning_en = ""
        example = ""
        if defs:
            meaning_en = (defs[0].get("definition") or "").split("\n")[0].strip()
            example = defs[0].get("example", "") or ""

        return DictionaryAPIResult(
            word=word,
            phonetic=phonetic,
            pos=pos,
            meaning_en=meaning_en,
            example=example,
        )


__all__ = [
    "DictionaryClient",
    "DictionaryAPIResult",
]