"""口语评分服务（v3.7 P1 新增,Sprint 3 完整实现）。

PRD: docs/web-mvp/plans/phase-8-speaking-practice.md §5.3

本 Sprint 3 阶段提供:
- 真 LLM 调用(走 LLMService 单例)+ retry-once
- 严格 JSON 解析(markdown 围栏 + <think> 块剥离 + regex 抽取)
- 失败 → 回退到 mock,score_fallback=True
- dry-run(LLM_DRY_RUN=True)→ 直接 mock

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
        # Sprint 3:默认拿 LLMService 单例,允许外部注入 mock 测试
        try:
            from ielts_buddy.web.llm_service import get_llm_service
            self._llm_service = get_llm_service()
        except Exception as exc:
            logger.warning("[speaking-grade] LLMService init failed: %s", exc)
            self._llm_service = None

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
                 suggestions / score_fallback。

        行为:
          - dry-run / LLM 不可用 / LLM 调用失败 → 走 mock,score_fallback=True
          - 正常路径 → 走真 LLM,score_fallback=False
        """
        # ---- 1. 真 LLM 路径 ----
        if self._llm_client is not None or (
            self._llm_service and self._llm_service.is_available()
            and not getattr(self._llm_service, "dry_run", False)
        ):
            llm_payload = self._build_prompt(
                part=part, topic=topic, question=question,
                transcript=transcript,
                sample_answer=sample_answer, vocab_hints=vocab_hints,
            )
            parsed = self._call_llm_with_retry(llm_payload)
            if parsed is not None:
                # 标准化字段
                normalized = self._normalize_payload(parsed)
                return normalized
            logger.warning("[speaking-grade] LLM 解析失败,降级到 mock")

        # ---- 2. mock / fallback ----
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

    # =============================================================
    # 真 LLM 路径(retry-once + JSON 抽取)
    # =============================================================

    def _build_prompt(
        self,
        part: int,
        topic: str,
        question: str,
        transcript: str,
        sample_answer: Optional[str] = None,
        vocab_hints: Optional[list[str]] = None,
    ) -> str:
        """构造完整 prompt。vocab_hints / sample_answer 用于评分上下文。"""
        hints_str = ", ".join(vocab_hints or []) or "(none)"
        sample_str = (sample_answer or "").strip() or "(none provided)"
        transcript_str = (transcript or "").strip() or "(no speech detected)"

        schema_block = (
            '{"scores":{'
            '"fluency":<float 0-9>,"lexical":<float 0-9>,'
            '"grammar":<float 0-9>,"pronunciation":<float 0-9>,'
            '"overall_band":<float 0-9>},"word_errors":['
            '{"original":"...","correction":"...","context":"..."}],'
            '"grammar_errors":['
            '{"original":"...","correction":"...","rule":"..."}],'
            '"highlights":["..."],"suggestions":["..."]}'
        )
        return (
            "You are an experienced IELTS speaking examiner.\n"
            f"Part: Part {part}\n"
            f"Topic: {topic}\n"
            f"Question: {question}\n"
            f"Suggested vocabulary: {hints_str}\n"
            f"Sample answer (for reference, NOT to copy): {sample_str}\n"
            f"Transcript (may have minor ASR errors): {transcript_str}\n\n"
            "Score on the 4 official IELTS criteria, each 0-9 band:\n"
            "  1. Fluency and Coherence\n"
            "  2. Lexical Resource\n"
            "  3. Grammatical Range and Accuracy\n"
            "  4. Pronunciation (estimated from transcript patterns only)\n\n"
            f"Return a JSON object with EXACT schema:\n{schema_block}\n\n"
            "Constraints:\n"
            "- Output ONLY the JSON. No markdown fence, no pre/post text.\n"
            "- word_errors and grammar_errors arrays may be empty [].\n"
            "- highlights/suggestions each 1-3 short strings.\n"
            "- overall_band = mean of the 4 dimensions (rounded to 0.5).\n"
        )

    def _call_llm_with_retry(self, prompt: str) -> Optional[dict]:
        """调 LLM,失败重试 1 次,返回解析后的 dict 或 None。"""
        client = self._llm_client
        if client is None and self._llm_service is not None:
            # 用 LLMService 内部的 _ensure_client()
            client = self._llm_service._ensure_client()
        if client is None:
            return None

        model = self._model or (
            self._llm_service.model if self._llm_service else "gpt-4o-mini"
        )

        last_text = ""
        for attempt in (1, 2):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content":
                         "你是经验丰富的雅思口语考官，按 4 个维度打分，输出严格 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
                last_text = (resp.choices[0].message.content or "").strip()
                parsed = extract_json(last_text)
                if parsed is not None:
                    return parsed
                logger.warning(
                    "[speaking-grade] attempt %d JSON parse failed; raw=%r",
                    attempt, last_text[:200],
                )
            except Exception as exc:
                logger.warning(
                    "[speaking-grade] attempt %d failed: %s",
                    attempt, exc,
                )
        return None

    def _normalize_payload(self, raw: dict) -> dict:
        """把 LLM 返回的 dict 归一化为契约结构。"""
        scores = raw.get("scores") or {}
        normalized_scores = {
            "fluency": _clamp_score(scores.get("fluency")),
            "lexical": _clamp_score(scores.get("lexical")),
            "grammar": _clamp_score(scores.get("grammar")),
            "pronunciation": _clamp_score(scores.get("pronunciation")),
            "overall_band": _clamp_score(scores.get("overall_band")),
        }
        # 缺 overall_band 时用均值(同样走 0.5 精度)
        if normalized_scores["overall_band"] is None:
            four = [
                normalized_scores["fluency"], normalized_scores["lexical"],
                normalized_scores["grammar"], normalized_scores["pronunciation"],
            ]
            valid = [x for x in four if x is not None]
            if valid:
                mean = sum(valid) / len(valid)
                normalized_scores["overall_band"] = (
                    round(mean * 2) / 2  # 0.5 精度
                )
            else:
                normalized_scores["overall_band"] = 6.0

        word_errors = raw.get("word_errors") or []
        grammar_errors = raw.get("grammar_errors") or []
        highlights = raw.get("highlights") or []
        suggestions = raw.get("suggestions") or []

        return {
            "scores": normalized_scores,
            "word_errors": [w for w in word_errors if isinstance(w, dict)],
            "grammar_errors": [g for g in grammar_errors if isinstance(g, dict)],
            "highlights": [str(h) for h in highlights if h][:5],
            "suggestions": [str(s) for s in suggestions if s][:5],
            "score_fallback": False,
        }

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
    """从 LLM 输出提取 JSON,容错处理 markdown 围栏 + 额外文字 + think 块。

    LLM 偶尔会在 JSON 前后加文字/换行,这里用 regex 抽第一个 {...} 块。
    """
    if not text:
        return None
    t = text.strip()
    # 去掉 <think>...</think> 思维链(跨行)
    t = re.sub(r"<think>[\s\S]*?</think>\s*", "", t, flags=re.IGNORECASE)
    # 去掉 ```json ... ``` / ``` ... ``` 围栏
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)
    # 尝试直接解析
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # 抽取第一个 {...} 块(平衡括号;regex 退化为非贪婪 + 整段 DOTALL)
    m = _JSON_BLOCK_RE.search(t)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _clamp_score(value: Any) -> Optional[float]:
    """归一化 0-9 范围的分数。非法值返回 None。"""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < 0 or v > 9:
        return None
    # 四舍五入到 0.5
    return round(v * 2) / 2


__all__ = ["SpeakingGradeService", "GradeResult", "SPEAKING_GRADE_PROMPT", "extract_json"]
