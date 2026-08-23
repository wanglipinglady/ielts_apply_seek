"""口语评分服务（v3.7 P1 新增,Sprint 3 完整实现）。

PRD: docs/web-mvp/plans/phase-8-speaking-practice.md §5.3

本 Sprint 2 阶段提供:
- 稳定的 mock 评分(dry-run / LLM 不可用 fallback)
- 严格的 JSON 解析
- retry-once + regex 抽取 JSON 块
- 接口签名已确定,Sprint 3 替换 prompt + 真 LLM 调用

输出 schema(契约):
{
  "scores": {fluency, lexical, grammar, pronunciation, overall_band},
  "word_errors": [{original, correction, context}],
  "grammar_errors": [{original, correction, rule}],
  "highlights": [str],
  "suggestions": [str],
  "score_fallback": bool,  # True 表示 LLM 走了 mock
}
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# 评判 prompt 本期给出,Sprint 3 会针对 LLM 输出格式做更细的指令
SPEAKING_GRADE_PROMPT = """You are an experienced IELTS speaking examiner.
The candidate just answered the following Part {part} question on the topic "{topic}":

Question: {question}
Transcript (estimated from speech-to-text, may contain minor errors):
{transcript}

Score the response on the official IELTS 4 criteria, each on 0-9 band scale:
1. Fluency and Coherence
2. Lexical Resource
3. Grammatical Range and Accuracy
4. Pronunciation (estimated from transcript patterns ONLY — you cannot hear audio)

Return a JSON object with this EXACT schema:
{{
  "scores": {{
    "fluency": <float 0-9>,
    "lexical": <float 0-9>,
    "grammar": <float 0-9>,
    "pronunciation": <float 0-9>,
    "overall_band": <float 0-9>
  }},
  "word_errors": [
    {{"original": "...", "correction": "...", "context": "..."}}
  ],
  "grammar_errors": [
    {{"original": "...", "correction": "...", "rule": "..."}}
  ],
  "highlights": ["<one short praise>"],
  "suggestions": ["<one short actionable improvement>"]
}}

Output ONLY the JSON. No markdown fence. No pre/post text.
"""


# =============================================================
# 默认评分(mock;LLM 不可用时使用)
# =============================================================

DEFAULT_MOCK_SCORES = {
    "fluency": 6.0,
    "lexical": 6.0,
    "grammar": 6.0,
    "pronunciation": 6.0,
    "overall_band": 6.0,
}


@dataclass
class GradeResult:
    """评分服务的返回值包装。"""
    scores: dict
    word_errors: list
    grammar_errors: list
    highlights: list
    suggestions: list
    score_fallback: bool

    def to_dict(self) -> dict:
        return {
            "scores": self.scores,
            "word_errors": self.word_errors,
            "grammar_errors": self.grammar_errors,
            "highlights": self.highlights,
            "suggestions": self.suggestions,
            "score_fallback": self.score_fallback,
        }


class SpeakingGradeService:
    """口语评分服务。

    Args:
        llm_client: 兼容 OpenAI 的 client。
            None 时走 mock(LLM 不可用或 dry-run)。
        model: 模型名,默认走 .env 的 IELTS_BUDDY_LLM_MODEL。
    """

    def __init__(self, llm_client: Any = None, model: Optional[str] = None) -> None:
        self._llm_client = llm_client
        self._model = model

    # ---- 主要入口 ----
    def grade(
        self,
        part: int,
        topic: str,
        question: str,
        transcript: str,
        sample_answer: Optional[str] = None,
        vocab_hints: Optional[list[str]] = None,
    ) -> dict:
        """对一份转写做评分。

        Returns:
            dict 含 scores / word_errors / grammar_errors / highlights /
                 suggestions / score_fallback。Sprint 3 在此替换成真 LLM。
        """
        # Sprint 2:稳定 mock + 占位 JSON 解析层
        return self._mock_grade(transcript)

    # =============================================================
    # mock 评分(dry-run / LLM 不可用 fallback)
    # =============================================================

    def _mock_grade(self, transcript: str) -> dict:
        """基于 transcript 长度的 toy 评分:
        - transcript 为空 → 全 5.5 + 提示"模型预热中"
        - 长度过短(< 30 词) → 全 5.5 + 提示"请说更多"
        - 长度中等 → 全 6.0
        - 长度充分 → 给一些真实感的高频词"教学提示",6.5
        """
        text = (transcript or "").strip()
        word_count = len(text.split()) if text else 0
        is_empty = not text or "(no speech" in text.lower()

        if is_empty:
            scores = {**DEFAULT_MOCK_SCORES, "fluency": 5.0, "overall_band": 5.0}
            highlights = ["(评分模拟模式:无可识别语音)"]
            suggestions = [
                "请重新录制,确保环境安静、麦克风离嘴 3-5cm",
                "评分模型正在预热,稍后重试将出真实评分",
            ]
            word_errors = []
            grammar_errors = []
            return self._make_payload(
                scores, word_errors, grammar_errors, highlights, suggestions,
                score_fallback=True,
            )

        if word_count < 30:
            scores = {**DEFAULT_MOCK_SCORES, "fluency": 5.0, "overall_band": 5.5}
            highlights = ["基本能用简单句表达"]
            suggestions = [
                "Part 1 建议说 3-4 句(每问 20-40 词),现在回答过短",
                "可加 'because' 引出原因,提升 Fluency 维度",
            ]
        elif word_count < 100:
            scores = {**DEFAULT_MOCK_SCORES, "overall_band": 6.0}
            highlights = ["回答结构完整,有具体细节"]
            suggestions = [
                "尝试加入 1-2 个高级词汇(如 'efficiently' / 'leisure')",
                "注意 th 音区分 /θ/ 与 /s/",
            ]
        else:
            scores = {**DEFAULT_MOCK_SCORES, "fluency": 6.5,
                       "lexical": 6.5, "overall_band": 6.5}
            highlights = [
                "回答详尽,达到了 Part 2 描述性回答的篇幅要求",
                "使用时间连接词(firstly / then / finally)结构感好",
            ]
            suggestions = [
                "可加入更深层的个人体验或观点,提升 Lexical 维度",
                "注意区分 /eɪ/ vs /æ/ 元音(例如 'grade' vs 'glad')",
            ]

        # toy 错词高亮:抓字符串里几个常见的"看着像拼错"的词
        # 此处不做太严苛的检测(避免 LLM mock 误报)
        word_errors: list[dict] = []
        grammar_errors: list[dict] = []

        return self._make_payload(
            scores, word_errors, grammar_errors, highlights, suggestions,
            score_fallback=True,
        )

    def _make_payload(
        self,
        scores: dict,
        word_errors: list,
        grammar_errors: list,
        highlights: list,
        suggestions: list,
        score_fallback: bool,
    ) -> dict:
        # 强制 overall_band = mean(4 维)
        if scores.get("overall_band") is None:
            four = [
                scores.get("fluency"), scores.get("lexical"),
                scores.get("grammar"), scores.get("pronunciation"),
            ]
            scores["overall_band"] = round(
                sum(x for x in four if x is not None) / 4, 2
            )
        return {
            "scores": scores,
            "word_errors": word_errors,
            "grammar_errors": grammar_errors,
            "highlights": highlights,
            "suggestions": suggestions,
            "score_fallback": score_fallback,
        }


# =============================================================
# 解析工具(Sprint 3 完整实现 LLM 后用)
# =============================================================


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> Optional[dict]:
    """从 LLM 输出提取 JSON,容错处理 markdown 围栏 + 额外文字。

    LLM 偶尔会在 JSON 前后加文字/换行,这里用 regex 抽第一个 {...} 块。
    """
    if not text:
        return None
    t = text.strip()
    # 去掉 ```json ... ``` 围栏
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)
    # 尝试直接解析
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # 抽取第一个 {...} 块
    m = _JSON_BLOCK_RE.search(t)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


__all__ = ["SpeakingGradeService", "GradeResult", "SPEAKING_GRADE_PROMPT", "extract_json"]
