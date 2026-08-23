"""LLM 出题器（v3.7 P2 真·听力题库）。

PRD: docs/web-mvp/plans/phase-9-listening-practice.md §5.1

设计:
- 按 Section 类型差异化 prompt:
  - Section 1 日常社交(租房/订餐/旅游咨询)— 填空为主
  - Section 2 校园/工作(社团/设施介绍)— 选择题 + 匹配
  - Section 3 学术讨论(2-4 人)— 选择题
  - Section 4 学术讲座(单人独白)— 填空为主
- 一次 generate_section() 返回 4-6 题 list[dict]
- 复用 extract_json + retry-once + JSON 容错(沿用 SpeakingGradeService 的 helper)
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
# Section → 题型配置
# =============================================================


@dataclass
class SectionProfile:
    """每个 Section 的题目模板(profile)。

    - question_types: 此 Section 允许的题型集合
    - question_count: 一套题几道
    - description: 中文描述(用于 prompt)
    - example_scenarios: 场景示例,让 LLM 学几样风格
    """
    section: int
    name: str
    description: str
    question_types: list[str]
    question_count: int
    example_scenarios: list[str]


SECTION_PROFILES: dict[int, SectionProfile] = {
    1: SectionProfile(
        section=1,
        name="日常社交场景",
        description="两人或多人非正式对话,日常社交话题(租房、旅游咨询、订餐、面试等)。",
        question_types=["form_completion", "multiple_choice"],
        question_count=5,
        example_scenarios=[
            "A student is inquiring about accommodation near the university.",
            "A customer is booking a table at a restaurant for a birthday party.",
            "A tourist is asking for directions to the city museum.",
            "An applicant is scheduling a job interview at the reception desk.",
            "A tenant is reporting a broken washing machine to the landlord.",
        ],
    ),
    2: SectionProfile(
        section=2,
        name="校园/工作场景",
        description="单人独白,介绍校园或工作环境(社团活动、设施介绍、福利制度等)。",
        question_types=["multiple_choice", "matching"],
        question_count=5,
        example_scenarios=[
            "A university guide is describing student clubs available on campus.",
            "A manager is introducing the company's new health benefits program.",
            "A tour guide is explaining facilities at a holiday resort.",
            "A librarian is presenting new digital services at the public library.",
            "A school counsellor is explaining the new student support system.",
        ],
    ),
    3: SectionProfile(
        section=3,
        name="学术讨论",
        description="2-4 人在学术或研究语境下的讨论(课题选择、研究方法、论文反馈等)。",
        question_types=["multiple_choice", "matching"],
        question_count=5,
        example_scenarios=[
            "Two students and a tutor are discussing their research methodology for a geography project.",
            "Three PhD candidates are comparing notes on their literature reviews.",
            "Two students are planning a joint field trip for an environmental science module.",
            "A supervisor is giving feedback on a draft dissertation chapter.",
            "Three classmates are debating the design of a psychology experiment.",
        ],
    ),
    4: SectionProfile(
        section=4,
        name="学术讲座",
        description="单人学术讲座(历史、自然科学、商业等主题),偏学术深度。",
        question_types=["form_completion", "multiple_choice"],
        question_count=6,
        example_scenarios=[
            "A lecture on the history of the Silk Road trade routes.",
            "A lecture on marine biology and coral reef ecosystems.",
            "A lecture on the psychology of decision-making under pressure.",
            "A lecture on the evolution of urban public transportation systems.",
            "A lecture on renewable energy and offshore wind farms.",
        ],
    ),
}


# =============================================================
# 出题器
# =============================================================


class ListeningQuestionGenerator:
    """按 Section 模板生成 IELTS 真题风格听力题。

    Args:
        llm_client: 兼容 OpenAI 的 client。None 时走 LLMService 单例。
        model: 模型名,默认走 .env 的 IELTS_BUDDY_LLM_MODEL。
    """

    def __init__(self, llm_client: Any = None, model: Optional[str] = None) -> None:
        self._llm_client = llm_client
        self._model = model
        try:
            from ielts_buddy.web.llm_service import get_llm_service
            self._llm_service = get_llm_service()
        except Exception as exc:
            logger.warning("[listening-gen] LLMService init failed: %s", exc)
            self._llm_service = None

    # =============================================================
    # 主要入口:生成一套 Section
    # =============================================================

    def generate_section(
        self,
        section: int,
        scenario: Optional[str] = None,
    ) -> list[dict]:
        """生成一套 Section(4-6 题),返回 dict 列表。

        每个 dict:
        {
            "qid": int,
            "section": int,
            "scenario": str,
            "question_type": str,    # multiple_choice / form_completion / matching
            "stem": str,
            "options": list[str] | None,
            "answer": str,
            "explanation": str,
            "transcript": str,
        }

        失败 / 无 LLM → 返回 []。
        """
        section = int(section)
        profile = SECTION_PROFILES.get(section)
        if profile is None:
            logger.warning("[listening-gen] unknown section=%s", section)
            return []

        # 1. 选 scenario
        if not scenario:
            scenario = random.choice(profile.example_scenarios)

        # 2. LLM 真路径 / mock 降级
        if self._is_llm_available():
            payload = self._build_prompt(profile, scenario)
            parsed = self._call_llm_with_retry(payload)
            if parsed is not None:
                normalized = self._normalize_questions(parsed, profile, scenario)
                if normalized:
                    return normalized
            logger.warning(
                "[listening-gen] LLM 解析/归一化失败,降级到 mock (section=%s)",
                section,
            )

        # 3. mock 降级(LLM 不可用 / 失败)
        return self._mock_questions(profile, scenario)

    def generate_full_set(
        self,
        sections: Optional[list[int]] = None,
    ) -> dict[int, list[dict]]:
        """一次性生成多个 Section;默认 1-4 各自分配套数。

        Returns:
            dict[section, list[dict]] 与 generate_section 单套结构一致。
        """
        targets = sections or [1, 2, 3, 4]
        out: dict[int, list[dict]] = {}
        for s in targets:
            qs = self.generate_section(s)
            if qs:
                out[int(s)] = qs
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
        # 列出每个题型的模板(schema)
        schema_block = (
            '{'
            '"qid": <int 1-based>, '
            '"section": <int 1-4>, '
            '"scenario": "<场景描述>", '
            '"question_type": "<multiple_choice|form_completion|matching>", '
            '"stem": "<题干>", '
            '"options": [<list of 4 option strings> | null], '
            '"answer": "<正确选项 A/B/C/D 或填空答案>", '
            '"explanation": "<为什么这是正确答案,1-2 句>", '
            '"transcript": "<完整原文台词 80-200 词,自然口语>" '
            '}'
        )
        types_str = ", ".join(profile.question_types)
        return (
            f"You are an IELTS listening item writer.\n"
            f"Section: Section {profile.section} ({profile.name})\n"
            f"Description: {profile.description}\n"
            f"Scenario: {scenario}\n\n"
            f"Generate exactly {profile.question_count} questions for one "
            f"IELTS Section {profile.section} listening set.\n\n"
            f"Allowed question types for this section: {types_str}\n"
            f"  - multiple_choice: 4 options labeled A/B/C/D, "
            f"answer is a single letter.\n"
            f"  - form_completion: stem has ONE blank (e.g. 'The price is ___'), "
            f"options MUST be null, answer is the word/phrase that fills the blank.\n"
            f"  - matching: 4 options labeled A/B/C/D, stem asks 'Which X matches Y', "
            f"answer is a single letter.\n\n"
            f"For EACH question, output the transcript segment "
            f"(80-200 words natural spoken English) that contains the answer. "
            f"The transcript must be ONE continuous conversation/lecture for the "
            f"whole set, and the answer must appear within it.\n\n"
            f"Return a JSON array of exactly {profile.question_count} objects, "
            f"each matching this EXACT schema:\n"
            f"{schema_block}\n\n"
            f"Constraints:\n"
            f"1. Output ONLY the JSON array. No markdown fence. No pre/post text.\n"
            f"2. qid must be 1..{profile.question_count} in order.\n"
            f"3. question_type MUST be one of: {types_str}.\n"
            f"4. For form_completion, options MUST be null (not an empty array).\n"
            f"5. For multiple_choice and matching, options MUST be an array of 4 "
            f"distinct strings; answer is A/B/C/D.\n"
            f"6. Keep vocabulary at IELTS Band 6-8 level. "
            f"Avoid obscure proper nouns.\n"
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
                         "你是雅思听力真题出题专家，输出严格 JSON 数组，"
                         "不解释，不包裹 markdown。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                )
                last_text = (resp.choices[0].message.content or "").strip()
                parsed = extract_json(last_text)
                if isinstance(parsed, list):
                    return parsed
                # 万一 LLM 包了 dict 而非 list(常见 JSON 对象误返回)
                # 兼容 dict of {qid: item}
                if isinstance(parsed, dict):
                    items = list(parsed.values())
                    if items and all(isinstance(x, dict) for x in items):
                        return items
                logger.warning(
                    "[listening-gen] attempt %d parse failed (not list); raw=%r",
                    attempt, last_text[:200],
                )
            except Exception as exc:
                logger.warning(
                    "[listening-gen] attempt %d failed: %s",
                    attempt, exc,
                )
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
        """把 LLM 返回的 list 归一化为契约结构,丢掉非法条目。

        校验:
        - qid 1-based 顺序;不在范围内丢弃
        - question_type 必须 ∈ profile.question_types;否则归类为第一个允许的
        - options 长度 4(选择题/匹配);form_completion → None
        - answer:选择题/匹配 → 'A'/'B'/'C'/'D';填空 → str
        - transcript / explanation / stem / scenario 不能为空
        """
        normalized: list[dict] = []
        allowed_types = set(profile.question_types)
        for idx, raw in enumerate(raw_items or [], start=1):
            if not isinstance(raw, dict):
                continue
            try:
                qid = int(raw.get("qid") or idx)
                if qid < 1 or qid > profile.question_count:
                    continue
                qtype = (raw.get("question_type") or "").strip()
                if qtype not in allowed_types:
                    # 选第一个允许的 type 作为兜底
                    qtype = profile.question_types[0]
                stem = (raw.get("stem") or "").strip()
                if not stem:
                    continue
                answer = (raw.get("answer") or "").strip()
                explanation = (raw.get("explanation") or "").strip()
                transcript = (raw.get("transcript") or "").strip()
                if not transcript or not answer:
                    continue
                # options 处理
                if qtype == "form_completion":
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
                        # 选项不足 → 拒绝这条(避免乱填)
                        continue
                    # answer 必须是 A/B/C/D
                    ans_upper = answer.upper()
                    if ans_upper not in ("A", "B", "C", "D"):
                        continue
                    answer = ans_upper
                normalized.append({
                    "qid": qid,
                    "section": profile.section,
                    "scenario": scenario,
                    "question_type": qtype,
                    "stem": stem,
                    "options": options,
                    "answer": answer,
                    "explanation": explanation or "(暂无解析)",
                    "transcript": transcript,
                })
            except Exception as exc:
                logger.warning(
                    "[listening-gen] skip malformed item idx=%d: %s; raw=%r",
                    idx, exc, raw,
                )
                continue
        return normalized

    # =============================================================
    # mock 降级:仅在 LLM 完全不可用时使用
    # =============================================================

    def _mock_questions(
        self,
        profile: SectionProfile,
        scenario: str,
    ) -> list[dict]:
        """生成一套合规但极简的占位题(LLM 不可用时)。

        场景:API key 未配置 + 启动期用户尝试抽题。
        期望:前端仍能展示 + 提交,但 score=0 + 「未配置 LLM」标签。
        """
        out: list[dict] = []
        for i in range(1, profile.question_count + 1):
            qtype = profile.question_types[0]
            if qtype == "form_completion":
                stem = f"[Mock] Question {i}: The key term mentioned is _____."
                options = None
                answer = "placeholder"
            else:
                stem = f"[Mock] Question {i}: Which option best describes the topic?"
                options = [
                    "Option A (placeholder)",
                    "Option B (placeholder)",
                    "Option C (placeholder)",
                    "Option D (placeholder)",
                ]
                answer = "A"
            out.append({
                "qid": i,
                "section": profile.section,
                "scenario": scenario,
                "question_type": qtype,
                "stem": stem,
                "options": options,
                "answer": answer,
                "explanation": (
                    "Mock 题:请配置 IELTS_BUDDY_LLM_API_KEY 后重启,LLM 将自动"
                    "生成高质量 IELTS 真题。"
                ),
                "transcript": (
                    f"[Mock transcript for scenario: {scenario}. "
                    f"This is a placeholder. Configure LLM to enable real IELTS "
                    f"questions. Audio will not be generated for mock items.]"
                ),
            })
        return out


__all__ = [
    "ListeningQuestionGenerator",
    "SECTION_PROFILES",
    "SectionProfile",
]