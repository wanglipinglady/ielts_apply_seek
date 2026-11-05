"""语音训练工坊 · Craft 改写服务（v3.9 W11）。

PRD: docs/web-mvp/plans/phase-11-voice-training-prd.md §5.1
把用户的中文日记改写成 B1 学习者可理解的地道英文（复刻 Enjoy Craft 循环）。
复用既有 LLMService（MiniMax），无 key 时返回 dry-run 演示文本。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

VALID_STYLES = ("natural", "casual", "formal")

# ---- LLM 思考标签清理（MiniMax M2 等推理模型会把 <think 块混在 content 里返回，
# 污染正文/TTS 输入，必须剥离） ----
_REASONING_BLOCK_RE = re.compile(
    r"<think(?:ing)?(?:\s[^>]*)?>.*?(?:</think(?:ing)?\s*>|$)", re.DOTALL | re.IGNORECASE
)
_REASONING_BLOCK2_RE = re.compile(
    r"<reasoning(?:\s[^>]*)?>.*?(?:</reasoning\s*>|$)", re.DOTALL | re.IGNORECASE
)
_LONE_TAG_RE = re.compile(r"</?(?:think(?:ing)?|reasoning)\b[^>]*>", re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """剥离 LLM content 里的思考块/孤立思考标签，只保留正式输出。"""
    if not text:
        return ""
    out = _REASONING_BLOCK_RE.sub("", text)
    out = _REASONING_BLOCK2_RE.sub("", out)
    out = _LONE_TAG_RE.sub("", out)
    return out.strip()

_STYLE_HINT = {
    "natural": "natural, everyday American English",
    "casual": "casual, conversational American English (spoken style)",
    "formal": "slightly formal, polished American English",
}


@dataclass
class RewriteResult:
    en_text: str
    word_count: int
    dry_run: bool = False


class CraftRewriteService:
    """中文 → 英文改写（享乐 Craft 等价物）。"""

    def __init__(self) -> None:
        from ielts_buddy.web.llm_service import get_llm_service
        self._llm = get_llm_service()

    def is_available(self) -> bool:
        return self._llm.is_available()

    def rewrite(self, zh_text: str, style: str = "natural") -> RewriteResult:
        """改写主入口。LLM 失败时抛 RuntimeError（路由层捕获后提示重试）。"""
        zh_text = (zh_text or "").strip()
        if not zh_text:
            raise ValueError("zh_text 为空")
        if style not in VALID_STYLES:
            style = "natural"

        if not self.is_available():
            return RewriteResult(
                en_text="[dry-run] Today I practiced my English training loop.",
                word_count=9,
                dry_run=True,
            )

        prompt = (
            f"Rewrite the following Chinese diary entry as "
            f"{_STYLE_HINT[style]}. Keep the original meaning. Use vocabulary "
            f"a B1-level English learner can understand; avoid rare words. "
            f"Output ONLY the English text — no explanations, no quotes, "
            f"no Chinese.\n\n{zh_text}"
        )
        try:
            client = self._llm._ensure_client()
            resp = client.chat.completions.create(
                model=self._llm.model,
                messages=[
                    {"role": "system", "content": "You are an English writing coach."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
            )
            en_text = strip_reasoning(resp.choices[0].message.content or "")
            en_text = re.sub(r"^\"+|\"+$", "", en_text).strip()
            if not en_text:
                raise RuntimeError("LLM 返回空文本")
            return RewriteResult(
                en_text=en_text,
                word_count=len(en_text.split()),
            )
        except Exception as exc:
            logger.error("[craft] LLM 改写失败: %s", exc)
            raise RuntimeError(f"LLM 改写失败: {exc}") from exc


# ---- 单例 ----
_craft_service: Optional[CraftRewriteService] = None


def get_craft_rewrite_service() -> CraftRewriteService:
    global _craft_service
    if _craft_service is None:
        _craft_service = CraftRewriteService()
    return _craft_service
