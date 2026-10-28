"""Reading LLM 出题器（v3.8 P3.2 新增）。

PRD: docs/web-mvp/plans/phase-10-reading-and-resources.md §5.2

设计:
- 4 个 Section(档位):easy / medium / hard / academic
- 5 大题型:tfng / multiple_choice / matching / summary / sentence_completion
- 题型比例 ~40% tfng / 25% mc / 15% matching / 10% summary / 10% sentence_completion
- 每套题 3 个 passage + ~13 题(一次 LLM 返回)
- 复用 extract_json + retry-once + JSON 容错(沿用 SpeakingGradeService helper)
- 失败 → 返回 [],由调用方走 fallback
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from typing import Any, Optional

from ielts_buddy.web.speaking_grade_service import extract_json

logger = logging.getLogger(__name__)


# =============================================================
# Section → 主题配置(PRD §5.2.2)
# =============================================================


@dataclass
class SectionProfile:
    section: str
    name: str
    description: str
    topics: list[str]
    word_count_range: tuple[int, int]
    difficulty: str
    question_count: int  # 一套题总题数(跨 3 个 passage)


SECTION_PROFILES: dict[str, SectionProfile] = {
    "easy": SectionProfile(
        section="easy",
        name="日常话题(简单)",
        description="日常话题短文(Band 5-6 词汇),适合零基础-5 分。",
        topics=["Daily Life", "Travel", "Food", "Shopping", "Hobbies"],
        word_count_range=(500, 700),
        difficulty="Band 5-6 词汇,简单句为主",
        question_count=10,
    ),
    "medium": SectionProfile(
        section="medium",
        name="社会文化(中等)",
        description="社会文化话题(Band 6-7 词汇),适合 5-6 分。",
        topics=["Education", "Environment", "Technology", "Society", "Work"],
        word_count_range=(600, 800),
        difficulty="Band 6-7 词汇,中等句长",
        question_count=12,
    ),
    "hard": SectionProfile(
        section="hard",
        name="学术科普(困难)",
        description="学术科普话题(Band 7-8 词汇),适合 6.5-7 分。",
        topics=["Science", "History", "Psychology", "Economics", "Biology"],
        word_count_range=(700, 900),
        difficulty="Band 7-8 词汇,复杂句 + 学术表达",
        question_count=13,
    ),
    "academic": SectionProfile(
        section="academic",
        name="学术论文(挑战)",
        description="学术论文风格(Band 8-9 词汇),适合 7+ 分。",
        topics=["Linguistics", "Anthropology", "Geology", "Cognitive Science", "Evolution"],
        word_count_range=(800, 1000),
        difficulty="Band 8-9 词汇,嵌套从句 + 专业术语",
        question_count=14,
    ),
}


def _distribute_questions(total: int, passages: int) -> list[int]:
    """把 total 道题**精确**分配到 passages 个 passage（余数先给前面的）。

    例：_distribute_questions(13, 3) → [5, 4, 4]（和 = 13）
    """
    base = total // passages
    remainder = total % passages
    return [
        base + (1 if i < remainder else 0)
        for i in range(passages)
    ]


# =============================================================
# 出题器
# =============================================================


class ReadingQuestionGenerator:
    """按 Section 模板生成 IELTS 风格阅读题。

    Args:
        llm_client: 兼容 OpenAI 的 client。None 时走 LLMService 单例。
        model: 模型名,默认走 .env 的 IELTS_BUDDY_LLM_MODEL。
    """

    def __init__(
        self,
        llm_client: Any = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        # v4.0：出题是"长输出"任务（3 篇 passage + 10-14 道题，实测 ~40s），
        # 默认的 LLM_TIMEOUT_SECONDS=30 不够 → 线上一直 "Request timed out" 降级到 mock。
        # 这里用独立的 READING_LLM_TIMEOUT_SECONDS（默认 180s）。
        self._timeout = timeout
        try:
            from ielts_buddy.web.llm_service import get_llm_service
            self._llm_service = get_llm_service()
        except Exception as exc:
            logger.warning("[reading-gen] LLMService init failed: %s", exc)
            self._llm_service = None

        if self._timeout is None:
            try:
                from ielts_buddy.web import config as web_config
                self._timeout = web_config.READING_LLM_TIMEOUT_SECONDS
            except Exception:
                self._timeout = 180.0

    # =============================================================
    # 主要入口
    # =============================================================

    def generate_section(
        self,
        section: str,
        scenario: Optional[str] = None,
    ) -> list[dict]:
        """生成一套 Section 题(3 个 passage + 10-14 题)。

        Returns:
            list of dict with keys:
            - qid, section, passage_number, title, topic, question_type
            - word_count, passage_text, stem, options, answer, explanation, source_line

        失败 / 无 LLM → 返回 mock 占位题。
        """
        section = str(section)
        profile = SECTION_PROFILES.get(section)
        if profile is None:
            logger.warning("[reading-gen] unknown section=%s", section)
            return []

        # 选场景话题
        if not scenario:
            scenario = random.choice(profile.topics)

        if self._is_llm_available():
            payload = self._build_prompt(profile, scenario)
            parsed = self._call_llm_with_retry(payload)
            if parsed is not None:
                normalized = self._normalize_questions(parsed, profile, scenario)
                if normalized:
                    return normalized
            logger.warning(
                "[reading-gen] LLM 解析/归一化失败,降级到 mock (section=%s)",
                section,
            )

        return self._mock_questions(profile, scenario)

    def generate_full_set(
        self, sections: Optional[list[str]] = None
    ) -> dict[str, list[dict]]:
        """一次性生成多个 Section;默认 4 个各自分配。"""
        targets = sections or list(SECTION_PROFILES.keys())
        out: dict[str, list[dict]] = {}
        for s in targets:
            qs = self.generate_section(s)
            if qs:
                out[s] = qs
        return out

    # =============================================================
    # LLM 调用路径
    # =============================================================

    def _is_llm_available(self) -> bool:
        if self._llm_client is not None:
            return True
        if self._llm_service is None:
            return False
        if getattr(self._llm_service, "dry_run", False):
            return False
        return self._llm_service.is_available()

    def _build_prompt(self, profile: SectionProfile, scenario: str) -> str:
        """构造出题 prompt。"""
        wc_min, wc_max = profile.word_count_range
        # 题型分布(根据 question_count 调整)
        total_q = profile.question_count
        # v4.0：把 total_q 题**精确**分配到 3 个 passage。
        # 初版用 per_passage = (total_q + 2) // 3，13 题时算出 5 → prompt 里
        # 同时出现 "3 篇各 5 题"（=15）和 "总共 13 题"，模型自己先在 <think> 里
        # 发现矛盾（线上实测："3 passages each followed by 5 questions = 15
        # conflict total 13"），导致输出质量下降。
        counts = _distribute_questions(total_q, 3)
        per_passage_desc = (
            f"Passage 1 has {counts[0]} questions, "
            f"Passage 2 has {counts[1]} questions, "
            f"Passage 3 has {counts[2]} questions "
            f"(total {total_q} questions)"
        )
        schema_block = (
            "{{"
            "\"passage_number\": <int 1-3>, "
            "\"qid\": <int 1-N 跨 passage 累加>, "
            "\"title\": \"<passage 标题>\", "
            "\"topic\": \"<主题>\", "
            "\"question_type\": \"<tfng|multiple_choice|matching|summary|sentence_completion>\", "
            "\"word_count\": <int 500-1000>, "
            "\"passage_text\": \"<完整 passage 文本 80-200 词(口语/学术风)>\", "
            "\"stem\": \"<题干>\", "
            "\"options\": [<4 选项> | null], "
            "\"answer\": \"<正确选项 A-D 或填空答案>\", "
            "\"explanation\": \"<为什么这是正确答案,1-2 句>\", "
            "\"source_line\": <int 或 null 出题句在 passage 中的行号 1-based>"
            "}}"
        )
        return (
            "You are an IELTS Reading item writer.\n"
            f"Section: {profile.name}\n"
            f"Description: {profile.description}\n"
            f"Scenario/topic: {scenario}\n"
            f"Difficulty: {profile.difficulty}\n"
            f"Word count range per passage: {wc_min}-{wc_max}\n\n"
            f"Generate exactly 3 reading passages. {per_passage_desc}.\n"
            "Each passage should be 3-5 short paragraphs (NOT a single line).\n\n"
            "Allowed question types (use all 5 types across the set):\n"
            "  - tfng (True/False/Not Given): stem is a statement, "
            "answer is one of 'T', 'F', 'NG', options MUST be null.\n"
            "  - multiple_choice: 4 options labeled A/B/C/D, "
            "answer is single letter.\n"
            "  - matching: stem asks 'Which paragraph matches X', "
            "4 options A-D, answer single letter.\n"
            "  - summary: stem has a blank in summary text, "
            "options MUST be null, answer is the word/phrase.\n"
            "  - sentence_completion: stem is a sentence with blank at end, "
            "options MUST be null, answer is the word/phrase.\n\n"
            "Each question's answer must appear in its passage_text.\n"
            "T/F/NG conventions:\n"
            "  - T = statement agrees with passage\n"
            "  - F = statement contradicts passage\n"
            "  - NG = statement is NOT mentioned in passage\n\n"
            f"Return a JSON array of exactly {total_q} objects, "
            f"each matching this schema:\n"
            f"{schema_block}\n\n"
            "Constraints:\n"
            "1. Output ONLY the JSON array. No markdown fence. No pre/post text.\n"
            f"2. qid must be 1..{total_q} in order across 3 passages.\n"
            "3. passage_number must be 1, 2, or 3 (with questions for that passage).\n"
            "4. question_type must be one of the 5 listed.\n"
            "5. For tfng/summary/sentence_completion: options MUST be null "
            "(NOT empty array).\n"
            "6. For multiple_choice/matching: options MUST be array of 4 "
            "distinct strings; answer is A/B/C/D.\n"
            f"7. Vocabulary at {profile.difficulty} level. Avoid obscure proper nouns.\n"
        )

    def _call_llm_with_retry(self, prompt: str) -> Optional[list]:
        """调 LLM,失败重试 1 次,返回 list 或 None。"""
        client = self._llm_client
        if client is None and self._llm_service is not None:
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
                         "你是雅思阅读真题出题专家,严格按 5 大题型,输出严格 JSON 数组。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    # v4.0：单独给长任务设超时（默认 30s 不够，会 "Request timed out"）
                    timeout=self._timeout,
                )
                last_text = (resp.choices[0].message.content or "").strip()
                parsed = extract_json(last_text)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    items = list(parsed.values())
                    if items and all(isinstance(x, dict) for x in items):
                        return items
                logger.warning(
                    "[reading-gen] attempt %d parse failed (not list); raw=%r",
                    attempt, last_text[:200],
                )
            except Exception as exc:
                logger.warning("[reading-gen] attempt %d failed: %s", attempt, exc)
        return None

    # =============================================================
    # 归一化
    # =============================================================

    def _normalize_questions(
        self,
        raw_items: list,
        profile: SectionProfile,
        scenario: str,
    ) -> list[dict]:
        """把 LLM 返回的 list 归一化为契约结构。"""
        allowed_types = {
            "tfng", "multiple_choice", "matching",
            "summary", "sentence_completion",
        }
        normalized: list[dict] = []
        for idx, raw in enumerate(raw_items or [], start=1):
            if not isinstance(raw, dict):
                continue
            try:
                qid = int(raw.get("qid") or idx)
                if qid < 1 or qid > profile.question_count + 5:
                    continue
                passage_number = int(raw.get("passage_number") or 1)
                if passage_number < 1 or passage_number > 3:
                    continue
                qtype = (raw.get("question_type") or "").strip()
                if qtype not in allowed_types:
                    continue
                title = (raw.get("title") or "").strip()
                topic = (raw.get("topic") or scenario).strip()
                word_count = int(raw.get("word_count") or 600)
                passage_text = (raw.get("passage_text") or "").strip()
                stem = (raw.get("stem") or "").strip()
                answer = (raw.get("answer") or "").strip()
                explanation = (raw.get("explanation") or "").strip()
                if not stem or not answer or not passage_text:
                    continue
                # options 处理
                if qtype in ("tfng", "summary", "sentence_completion"):
                    options = None
                else:
                    opts_raw = raw.get("options")
                    if isinstance(opts_raw, list):
                        options = [
                            str(o).strip() for o in opts_raw
                            if str(o).strip()
                        ][:4]
                    else:
                        options = []
                    if len(options) != 4:
                        continue
                    # answer 必须是 A/B/C/D
                    ans_upper = answer.upper()
                    if ans_upper not in ("A", "B", "C", "D"):
                        continue
                    answer = ans_upper
                # T/F/NG answer 归一化
                if qtype == "tfng":
                    ans_upper = answer.upper()
                    if ans_upper in ("TRUE", "T"):
                        answer = "T"
                    elif ans_upper in ("FALSE", "F"):
                        answer = "F"
                    elif ans_upper == "NG":
                        answer = "NG"
                    else:
                        # 非法值 → 拒绝
                        continue
                source_line = raw.get("source_line")
                if source_line is not None:
                    try:
                        source_line = int(source_line)
                    except Exception:
                        source_line = None
                normalized.append({
                    "qid": qid,
                    "section": profile.section,
                    "passage_number": passage_number,
                    "title": title or f"Passage {passage_number}",
                    "topic": topic,
                    "question_type": qtype,
                    "word_count": word_count,
                    "passage_text": passage_text,
                    "stem": stem,
                    "options": options,
                    "answer": answer,
                    "explanation": explanation or "(暂无解析)",
                    "source_line": source_line,
                })
            except Exception as exc:
                logger.warning(
                    "[reading-gen] skip malformed item idx=%d: %s; raw=%r",
                    idx, exc, raw,
                )
                continue
        return normalized

    # =============================================================
    # mock 降级
    # =============================================================

    def _mock_questions(
        self, profile: SectionProfile, scenario: str
    ) -> list[dict]:
        """LLM 不可用时的合规占位题。"""
        out: list[dict] = []
        # 题目类型分布:tfng 40% / mc 25% / matching 15% / summary 10% / sentence_completion 10%
        total = profile.question_count
        n_tfng = int(total * 0.4)
        n_mc = int(total * 0.25)
        n_match = int(total * 0.15)
        n_summary = int(total * 0.10)
        n_sent = total - n_tfng - n_mc - n_match - n_summary
        types = (
            ["tfng"] * n_tfng
            + ["multiple_choice"] * n_mc
            + ["matching"] * n_match
            + ["summary"] * n_summary
            + ["sentence_completion"] * n_sent
        )
        # 分配到 3 个 passage
        for i in range(1, total + 1):
            qtype = types[i - 1] if i - 1 < len(types) else "multiple_choice"
            passage_num = ((i - 1) // 5) + 1  # 5 道/篇
            if passage_num > 3:
                passage_num = 3
            if qtype in ("tfng", "summary", "sentence_completion"):
                stem = (
                    f"[Mock Passage {passage_num}] Question {i}: "
                    f"The text mentions that [BLANK] (fill in)."
                )
                options = None
                if qtype == "tfng":
                    answer = "T"
                else:
                    answer = "placeholder"
            else:
                stem = f"[Mock Passage {passage_num}] Question {i}: Which option is correct?"
                options = ["Option A (placeholder)", "Option B", "Option C", "Option D"]
                answer = "A"
            passage_text = (
                f"[Mock passage text for {scenario}. This is a placeholder passage. "
                f"Configure IELTS_BUDDY_LLM_API_KEY and restart to generate real IELTS "
                f"reading content. Topic: {scenario}.] * {i}"
            )
            out.append({
                "qid": i,
                "section": profile.section,
                "passage_number": passage_num,
                "title": f"[Mock] {scenario} - Passage {passage_num}",
                "topic": scenario,
                "question_type": qtype,
                "word_count": 600,
                "passage_text": passage_text,
                "stem": stem,
                "options": options,
                "answer": answer,
                "explanation": (
                    "Mock 题:请配置 IELTS_BUDDY_LLM_API_KEY 后重启,LLM 将自动"
                    "生成高质量 IELTS 真题。"
                ),
                "source_line": None,
            })
        return out


__all__ = [
    "ReadingQuestionGenerator",
    "SECTION_PROFILES",
    "SectionProfile",
]