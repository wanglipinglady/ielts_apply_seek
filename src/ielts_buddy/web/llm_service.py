"""Web 端 LLM 服务：联网查词 + 文章翻译共用。

设计原则：
1. 直接用 ``openai`` SDK（OpenAI 兼容协议），参考 ``docs/grok.py`` 已验证的 MiniMax 调用方式
2. **单例 + lazy 初始化**：避免 web 启动时 import openai 卡顿
3. **dry-run 模式**：未配置 API key 时返回 mock 数据，让前端能正常演示
4. **结构化输出**：所有 prompt 都要求 JSON 输出，便于解析
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from ielts_buddy.web import config as web_config

logger = logging.getLogger(__name__)


# =============================================================
# 数据结构
# =============================================================


@dataclass
class WordLookupResult:
    """联网查词结果。"""

    word: str
    phonetic: str = ""           # /fəˈnetɪk/
    pos: str = ""                # n.
    meaning_cn: str = ""         # 中文释义
    meaning_en: str = ""         # 英文释义（可选）
    example: str = ""            # 英文例句
    example_cn: str = ""         # 例句中文
    source: str = "unknown"      # builtin / dictionary_api / llm / mock
    confidence: str = "medium"   # high / medium / low


@dataclass
class TranslationResult:
    """段落翻译结果。"""

    source_text: str
    translation: str
    source: str = "llm"


# =============================================================
# LLM 服务（单例）
# =============================================================


@lru_cache(maxsize=1)
def get_llm_service() -> "LLMService":
    """获取 LLM 服务单例。"""
    return LLMService(
        api_key=web_config.LLM_API_KEY,
        base_url=web_config.LLM_BASE_URL,
        model=web_config.LLM_MODEL,
        timeout=web_config.LLM_TIMEOUT_SECONDS,
        dry_run=web_config.LLM_DRY_RUN,
    )


class LLMService:
    """统一的 LLM 调用入口。"""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.minimaxi.com/v1",
        model: str = "MiniMax-M2.7-highspeed",
        timeout: float = 30.0,
        dry_run: bool = False,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.dry_run = dry_run
        self._client = None

    def _ensure_client(self):
        """Lazy 初始化 openai 客户端。"""
        if self._client is not None:
            return self._client
        if self.dry_run or not self.api_key:
            return None
        try:
            import openai
            self._client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
            return self._client
        except ImportError:
            logger.warning("openai SDK 未安装，无法调用 LLM")
            return None

    def is_available(self) -> bool:
        """LLM 是否可用（有 API key 且 SDK 装好）。"""
        return self._ensure_client() is not None

    # ----- 公共方法：单词查询 -----

    def lookup_word(self, word: str) -> WordLookupResult:
        """用 LLM 查询单词的音标、释义、例句。

        仅在词库 + 词典 API 都查不到时调用此方法。
        """
        word = word.strip()
        if not word:
            return WordLookupResult(word="", source="unknown")

        if self.dry_run or not self.api_key:
            return self._mock_word_lookup(word)

        try:
            return self._llm_word_lookup(word)
        except Exception as e:
            logger.error(f"LLM 查词失败: {e}")
            return self._mock_word_lookup(word, error=str(e))

    # ----- 公共方法：IPA → DJ 音标转换 -----

    def convert_to_dj_phonetic(
        self,
        word: str,
        ipa_phonetic: str,
    ) -> str:
        """将 IPA 国际音标转为 DJ 教材音标（英式宽式）。

        仅在 LLM 可用（api_key 已配置 + 非 dry-run）时返回有效结果；
        否则返回原 IPA，让用户知道降级了。

        使用场景：词典 API 返回 IPA（如 /ˌsɛ.ɹən.ˈdɪ.pɪ.ti/），
        但 IELTS 教材用 DJ（如 [ˌserənˈdɪpəti]）。
        调用 LLM 做 IPA→DJ 转写，确保用户拿到的是教材一致的形式。

        Returns:
            DJ 风格音标（带 [ ] 或不带皆可）；失败时返回原 IPA。
        """
        ipa = (ipa_phonetic or "").strip()
        if not ipa or not self.is_available():
            return ipa_phonetic  # 失败/无 key：返回原 IPA

        try:
            client = self._ensure_client()
            if client is None:
                return ipa_phonetic

            prompt = (
                f'将以下英文单词 "{word}" 的国际音标 (IPA) 转为 DJ 教材音标'
                f'（英式宽式，Daniel Jones 体系）。\n\n'
                f'IPA: {ipa}\n\n'
                f'要求：\n'
                f'1. 输出严格的 DJ 音标（用 / / 包裹，去掉 ɹ 颜色化、ʳ 标记等 IPA 细节）\n'
                f'2. 只输出音标本身，不要任何解释或前缀\n'
                f'3. 如 /əˈfɛ.mə.ɹəl/ → /ɪˈfemərəl/ 风格\n'
                f'4. 如 /ˌsɛ.ɹən.ˈdɪ.pɪ.ti/ → /ˌserənˈdɪpəti/\n'
            )
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是英语语音学专家，专门做 IPA→DJ 音标转写。"
                        "输出严格、不解释。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            content = (resp.choices[0].message.content or "").strip()
            # 清理：去掉 markdown 代码块标记、行首说明
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            # 去掉前后引号
            content = content.strip().strip("'\"").strip()
            # 提取第一个音标（如 "...DJ 音标: /abc/" → /abc/）
            match = re.search(r"\[?[ˈˌa-zæɛɪɒʌəɜɑɔʊθðʃʒŋɲɹɾʁʔˈˌː.\-]+\]?", content)
            if match:
                content = match.group(0)
            # 至少要有 // 包裹
            if "/" not in content:
                content = f"/{content.strip('/[]')}/"
            return content or ipa_phonetic
        except Exception as e:
            logger.warning(f"IPA→DJ 转写失败: {e}")
            return ipa_phonetic

    # ----- 公共方法：段落翻译 -----

    def translate(self, text: str, target_lang: str = "zh") -> TranslationResult:
        """翻译整段文本到目标语言（默认中文）。"""
        text = text.strip()
        if not text:
            return TranslationResult(source_text="", translation="")

        if self.dry_run or not self.api_key:
            return TranslationResult(
                source_text=text,
                translation=f"[DRY-RUN 翻译] {text[:60]}...",
                source="mock",
            )

        try:
            return self._llm_translate(text, target_lang)
        except Exception as e:
            logger.error(f"LLM 翻译失败: {e}")
            return TranslationResult(
                source_text=text,
                translation=f"[翻译失败: {e}] {text[:60]}...",
                source="error",
            )

    # ----- 私有：LLM 实现 -----

    def _llm_word_lookup(self, word: str) -> WordLookupResult:
        """调用 LLM 查词（structured JSON output）。"""
        client = self._ensure_client()
        if client is None:
            return self._mock_word_lookup(word, error="LLM client unavailable")

        prompt = f"""请为英文单词 "{word}" 提供词典信息。严格按 JSON 格式输出，不要有其他文字：

{{
  "phonetic": "国际音标，如 /ɪnˈtəːvɪʃn/",
  "pos": "词性缩写，如 n. / v. / adj.",
  "meaning_cn": "中文释义（简洁，1-2 个常见义项）",
  "meaning_en": "英文释义（可选，简单 1 行）",
  "example": "一个常见英文例句",
  "example_cn": "例句的中文翻译"
}}"""

        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的英汉词典，输出严格 JSON，不含任何 markdown 代码块标记。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        content = (resp.choices[0].message.content or "").strip()

        # 提取 JSON（容错：可能被 markdown 包裹）
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            raise ValueError(f"LLM 未返回 JSON: {content[:200]}")
        data: dict[str, Any] = json.loads(m.group(0))

        return WordLookupResult(
            word=word,
            phonetic=data.get("phonetic", ""),
            pos=data.get("pos", ""),
            meaning_cn=data.get("meaning_cn", ""),
            meaning_en=data.get("meaning_en", ""),
            example=data.get("example", ""),
            example_cn=data.get("example_cn", ""),
            source="llm",
            confidence="high",
        )

    def _llm_translate(self, text: str, target_lang: str) -> TranslationResult:
        """调用 LLM 翻译整段。"""
        client = self._ensure_client()
        if client is None:
            return TranslationResult(
                source_text=text,
                translation="[LLM unavailable]",
                source="error",
            )

        lang_name = "中文" if target_lang == "zh" else target_lang
        prompt = f"""请将以下英文段落流畅地翻译成{lang_name}。保持学术性、准确性，不要遗漏任何信息：

{text}"""

        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是专业的英汉翻译专家，输出地道流畅的中文翻译。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        translation = (resp.choices[0].message.content or "").strip()
        return TranslationResult(
            source_text=text, translation=translation, source="llm"
        )

    # ----- 私有：Mock -----

    def _mock_word_lookup(self, word: str, error: str = "") -> WordLookupResult:
        """Dry-run / 失败时的 mock 数据。"""
        return WordLookupResult(
            word=word,
            phonetic=f"/{word}/",
            pos="n.",
            meaning_cn=f"[DRY-RUN 释义] 单词 {word}（设置 API key 后由 LLM 查询）",
            meaning_en=f"[DRY-RUN] definition of {word}",
            example=f"This is an example with '{word}'.",
            example_cn=f"[DRY-RUN 翻译] 这是一个包含 '{word}' 的例句。",
            source="mock" if not error else "error",
            confidence="low",
        )


__all__ = [
    "get_llm_service",
    "LLMService",
    "WordLookupResult",
    "TranslationResult",
]