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
        phonetic_system: str = "ipa",  # "ipa" / "dj" / "unknown"
        phonetic_region: str = "",     # "us" / "au" / "uk"
    ):
        self.word = word
        self.phonetic = phonetic
        self.pos = pos
        self.meaning_cn = meaning_cn
        self.meaning_en = meaning_en
        self.example = example
        self.example_cn = example_cn
        self.phonetic_system = phonetic_system
        self.phonetic_region = phonetic_region

    def is_empty(self) -> bool:
        return not (self.phonetic or self.meaning_en or self.meaning_cn)


# =============================================================
# 客户端
# =============================================================


class DictionaryClient:
    """free dictionary API 客户端。

    设计要点：
    1. **重试机制**：公共服务不稳定（偶发 502/timeout），失败时重试 1 次
    2. **区分 404 vs 5xx**：404 = 词典没收这个词（终态），5xx/timeout = 网络问题（重试）
    3. **超时加长到 8s**：公共服务首请求可能较慢
    """

    BASE_URL = "https://api.dictionaryapi.dev/api/v2/entries/en"

    def __init__(self, timeout: float = 8.0, max_retries: int = 1):
        self.timeout = timeout
        self.max_retries = max_retries

    async def lookup(self, word: str) -> Optional[DictionaryAPIResult]:
        """查询单词；返回 None 表示没找到 / 网络错误（重试耗尽后）。"""
        word = word.strip().lower()
        if not word:
            return None
        url = f"{self.BASE_URL}/{word}"

        # 重试循环：max_retries=1 意味着最多请求 2 次
        last_err: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(url)

                # 404 是终态：词典没收这个词，不需要重试
                if resp.status_code == 404:
                    return None

                # 200 OK：解析
                if resp.status_code == 200:
                    return self._parse(word, resp.json())

                # 5xx / 其他错误：记录 + 重试
                last_err = f"HTTP {resp.status_code}"
                logger.warning(
                    f"词典 API {last_err} (尝试 {attempt + 1}/{self.max_retries + 1}): {word}"
                )
                if attempt < self.max_retries:
                    continue  # 重试
                return None

            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_err = f"{type(e).__name__}: {e}"
                logger.warning(
                    f"词典 API 网络错误 (尝试 {attempt + 1}/{self.max_retries + 1}): {last_err}"
                )
                if attempt < self.max_retries:
                    continue  # 重试
                return None
            except Exception as e:
                # JSON 解析错误：重试也无用，直接返回
                logger.warning(f"词典 API 解析错误: {e}")
                return None

        return None

    @staticmethod
    def _parse(word: str, data: list) -> Optional[DictionaryAPIResult]:
        """解析 dictionaryapi.dev 的响应。

        注意：dictionaryapi.dev 返回的是 IPA（国际音标），主要来自美/澳发音，
        与 IELTS 教材常用的 DJ 音标（英式）有差异。例如 serendipity：
          IPA: /ˌsɛ.ɹən.ˈdɪ.pɪ.ti/
          DJ:  [ˌserənˈdɪpəti]
        """
        if not isinstance(data, list) or not data:
            return None
        entry = data[0]

        # 音标 + 区域（us/au/uk）
        phonetic = entry.get("phonetic", "") or ""
        region = ""
        if not phonetic:
            for p in entry.get("phonetics", []):
                if p.get("text"):
                    phonetic = p["text"]
                    audio = p.get("audio", "")
                    # audio URL 末尾 "-us.mp3" / "-au.mp3" / "-uk.mp3"
                    if audio:
                        region = audio.rsplit("-", 1)[-1].replace(".mp3", "")
                    break
        else:
            # 顶层 phonetic 字段时也尝试从 phonetics 数组提取 region
            for p in entry.get("phonetics", []):
                audio = p.get("audio", "")
                if audio:
                    region = audio.rsplit("-", 1)[-1].replace(".mp3", "")
                    break

        # dictionaryapi.dev 用的始终是 IPA（基于 Wiktionary 的源）
        phonetic_system = "ipa" if phonetic else "unknown"

        # 第一个 meaning
        meanings = entry.get("meanings", [])
        if not meanings:
            return DictionaryAPIResult(
                word=word, phonetic=phonetic,
                phonetic_system=phonetic_system, phonetic_region=region,
            )

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
            phonetic_system=phonetic_system,
            phonetic_region=region,
        )


__all__ = [
    "DictionaryClient",
    "DictionaryAPIResult",
]