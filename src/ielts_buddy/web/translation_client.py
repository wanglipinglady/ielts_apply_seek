"""MyMemory 翻译 API 客户端：免费的英中翻译。

API：https://mymemory.translated.net/
特点：
- 无需注册（每天有免费额度，足够个人学习使用）
- 支持多语言
- 翻译质量中等偏上，专业词典术语偶尔不准
- 含 match 字段（0-1），越高表示越接近人工翻译
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class TranslationResult:
    """翻译结果。"""

    def __init__(self, source: str, translated: str, quality: float = 0.0):
        self.source = source
        self.translated = translated
        self.quality = quality  # 0-1，越高越好

    def is_valid(self) -> bool:
        """翻译是否有效（非空、非占位符）。"""
        t = self.translated.strip()
        if not t:
            return False
        # MyMemory 占位符："MYMEMORY WARNING"
        if "WARNING" in t.upper() or "PLEASE ENTER TWO" in t.upper():
            return False
        return True


class MyMemoryClient:
    """MyMemory 免费翻译 API 客户端。"""

    BASE_URL = "https://api.mymemory.translated.net/get"

    def __init__(self, timeout: float = 4.0):
        self.timeout = timeout

    async def translate(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "zh-CN",
    ) -> Optional[TranslationResult]:
        """翻译文本。

        Args:
            text: 要翻译的文本（≤ 500 bytes）
            source_lang: 源语言代码（默认 en）
            target_lang: 目标语言代码（默认 zh-CN）

        Returns:
            TranslationResult 或 None（失败时）
        """
        text = (text or "").strip()
        if not text:
            return None
        # MyMemory 限制 500 bytes
        if len(text.encode("utf-8")) > 500:
            text = text[:500]

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    self.BASE_URL,
                    params={
                        "q": text,
                        "langpair": f"{source_lang}|{target_lang}",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"MyMemory API {resp.status_code}: {text[:30]}")
                    return None
                data = resp.json()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning(f"MyMemory 网络错误: {e}")
            return None
        except Exception as e:
            logger.warning(f"MyMemory 解析错误: {e}")
            return None

        response_data = data.get("responseData") or {}
        translated = response_data.get("translatedText", "") or ""
        try:
            quality = float(response_data.get("match", 0))
        except (TypeError, ValueError):
            quality = 0.0

        result = TranslationResult(
            source=text, translated=translated.strip(), quality=quality
        )
        if not result.is_valid():
            return None
        return result


__all__ = [
    "MyMemoryClient",
    "TranslationResult",
]