"""Reading 真题题库业务服务（v3.8 P3.2 新增）。

PRD: docs/web-mvp/plans/phase-10-reading-and-resources.md §5.1-5.3
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ielts_buddy.core.repository import ReadingPracticeRepository

logger = logging.getLogger(__name__)


# =============================================================
# 常量
# =============================================================


SECTION_LABELS = {
    "easy": "日常话题(简单)",
    "medium": "社会文化(中等)",
    "hard": "学术科普(困难)",
    "academic": "学术论文(挑战)",
}

QUESTION_TYPE_LABELS = {
    "tfng": "True / False / Not Given",
    "multiple_choice": "选择题",
    "matching": "匹配题",
    "summary": "摘要填空",
    "sentence_completion": "句子填空",
}


# =============================================================
# 业务服务
# =============================================================


class ReadingPracticeService:
    """Reading 题库业务服务。

    Args:
        container: 业务容器(拿 .reading_practice + .learning)
        user_id: 当前 web 用户 ID
    """

    def __init__(self, container: Any, user_id: int) -> None:
        self._container = container
        self._user_id = int(user_id)
        self._repo: ReadingPracticeRepository = container.reading_practice

    # =============================================================
    # 列表 + 概览
    # =============================================================

    def list_sections(self) -> list[dict]:
        """4 个 Section 档位概览(含个人正确率)。"""
        sections = self._repo.list_sections_with_counts()
        stats = self._repo.get_user_stats(self._user_id)
        by_section = stats.get("by_section", {})
        out: list[dict] = []
        for s in sections:
            sec = s["section"]
            user_data = by_section.get(sec, {})
            user_attempts = int(user_data.get("attempts", 0))
            user_correct = int(user_data.get("correct", 0))
            accuracy = (
                round(user_correct / user_attempts * 100, 1)
                if user_attempts > 0 else None
            )
            out.append({
                "section": sec,
                "name": SECTION_LABELS.get(sec, f"Section {sec}"),
                "total_sets": int(s["total_sets"]),
                "total_passages": int(s["total_passages"]),
                "user_attempts": user_attempts,
                "user_accuracy": accuracy,
            })
        return out

    def list_sets(self, section: str) -> list[dict]:
        """列出某 Section 档位下所有套题。"""
        return self._repo.list_sets_by_section(section)

    # =============================================================
    # 抽题 + 单题详情
    # =============================================================

    def start_set(self, section: str, set_id: int) -> Optional[dict]:
        """抽一套题(section + set_id 必填)。"""
        rows = self._repo.list_passages_by_set(section, set_id)
        if not rows:
            return None
        scenario = rows[0].get("topic") or ""
        return {
            "section": section,
            "set_id": set_id,
            "section_label": SECTION_LABELS.get(section, section),
            "scenario": scenario,
            "questions": [self._normalize_question_for_client(q) for q in rows],
        }

    def start_random_set(
        self, section: Optional[str] = None
    ) -> Optional[dict]:
        """随机抽一套题。"""
        sections = self._repo.list_sections_with_counts()
        if section is not None:
            sections = [s for s in sections if s["section"] == section]
        available: list[tuple[str, int]] = []
        for s in sections:
            sec = str(s["section"])
            sets = self._repo.list_sets_by_section(sec)
            for st in sets:
                available.append((sec, int(st["set_id"])))
        if not available:
            return None
        import random
        sec, set_id = random.choice(available)
        return self.start_set(sec, set_id)

    def get_question(self, question_id: int) -> Optional[dict]:
        """单题详情(过滤 answer/explanation/transcript 等敏感字段)。"""
        q = self._repo.get_passage(int(question_id))
        if q is None:
            return None
        return self._normalize_question_for_client(q)

    # =============================================================
    # 提交答案
    # =============================================================

    def submit_answer(
        self,
        question_id: int,
        user_answer: str,
        duration_sec: float = 0.0,
    ) -> Optional[dict]:
        """判分 + 落 attempts + 找下一题。"""
        q = self._repo.get_passage(int(question_id))
        if q is None:
            return None
        user_answer_clean = (user_answer or "").strip()
        correct_answer = (q.get("answer") or "").strip()
        qtype = q.get("question_type", "")
        is_correct = self._is_answer_correct(
            user_answer_clean, correct_answer, qtype
        )
        attempt_id = self._repo.record_attempt(
            user_id=self._user_id,
            question_id=int(question_id),
            user_answer=user_answer_clean,
            is_correct=is_correct,
            duration_sec=float(duration_sec),
        )
        # 找下一题:同 section+set 的下一条 qid
        next_qid = self._find_next_question_id(
            str(q["section"]), int(q["set_id"]), int(q["qid"])
        )
        return {
            "question_id": int(question_id),
            "is_correct": is_correct,
            "correct_answer": correct_answer,
            "explanation": q.get("explanation") or "",
            "transcript": q.get("passage_text") or "",  # Reading 把 passage_text 当 transcript 用
            "question_type": qtype,
            "played_count": 1,
            "attempt_id": int(attempt_id),
            "next_question_id": next_qid,
        }

    def _is_answer_correct(
        self, user_answer: str, correct: str, qtype: str
    ) -> bool:
        u = (user_answer or "").strip()
        c = (correct or "").strip()
        if not u or not c:
            return False
        if qtype == "tfng":
            u_upper = u.upper()
            c_upper = c.upper()
            # T/True/F/False/NG 容错
            u_t = "T" if u_upper in ("T", "TRUE") else (
                "F" if u_upper in ("F", "FALSE") else u_upper
            )
            c_t = "T" if c_upper in ("T", "TRUE") else (
                "F" if c_upper in ("F", "FALSE") else c_upper
            )
            return u_t == c_t and u_t in ("T", "F", "NG")
        if qtype in ("multiple_choice", "matching"):
            return u.upper() == c.upper()
        # summary / sentence_completion:大小写不敏感 + 去标点
        norm = lambda s: re.sub(
            r"\s+", " ",
            re.sub(r"[^\w\s]", "", s.lower())
        ).strip()
        return norm(u) == norm(c)

    def _find_next_question_id(
        self, section: str, set_id: int, current_qid: int
    ) -> Optional[int]:
        rows = self._repo.list_passages_by_set(section, set_id)
        rows.sort(key=lambda r: int(r["qid"]))
        for idx, row in enumerate(rows):
            if int(row["qid"]) == int(current_qid):
                if idx + 1 < len(rows):
                    return int(rows[idx + 1]["id"])
                return None
        return None

    # =============================================================
    # 历史 + 统计
    # =============================================================

    def list_history(
        self,
        page: int = 1,
        size: int = 20,
        section: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        return self._repo.list_user_attempts(
            user_id=self._user_id,
            page=page, size=size,
            section=section,
        )

    def get_user_stats(self) -> dict:
        """聚合统计(API 友好格式)。"""
        raw = self._repo.get_user_stats(self._user_id)
        total = int(raw.get("total_attempts", 0))
        # accuracy:无 attempts 时返回 None(避免 0/0 → 0.0 误导)
        raw_acc = raw.get("accuracy")
        if total == 0 or raw_acc is None:
            accuracy: Optional[float] = None
        else:
            accuracy = raw_acc
        # by_section 中每个 section 也归一化
        by_section = {}
        for sec_key, s in (raw.get("by_section") or {}).items():
            sec_attempts = int(s.get("attempts", 0))
            sec_accuracy: Optional[float] = (
                s.get("accuracy") if sec_attempts > 0 else None
            )
            by_section[sec_key] = {
                "attempts": sec_attempts,
                "correct": int(s.get("correct", 0)),
                "accuracy": sec_accuracy,
            }
        return {
            "total_attempts": total,
            "correct": int(raw.get("correct_count", 0)),
            "accuracy": accuracy,
            "by_section": by_section,
        }

    # =============================================================
    # Helpers
    # =============================================================

    def _normalize_question_for_client(self, q: dict) -> dict:
        """DB row → 客户端结构(过滤敏感字段)。"""
        qtype = q.get("question_type") or ""
        return {
            "id": int(q["id"]),
            "section": str(q.get("section") or ""),
            "set_id": int(q.get("set_id") or 0),
            "qid": int(q.get("qid") or 0),
            "passage_number": int(q.get("passage_number") or 1),
            "title": q.get("title") or "",
            "topic": q.get("topic") or "",
            "question_type": qtype,
            "question_type_label": QUESTION_TYPE_LABELS.get(qtype, qtype),
            "word_count": int(q.get("word_count") or 0),
            "passage_text": q.get("passage_text") or "",
            "stem": q.get("stem") or "",
            "options": q.get("options"),
            "audio_url": None,  # Reading 无音频
            "source_line": q.get("source_line"),
        }


# =============================================================
# 模块级(启动期种子 + 清理)
# =============================================================


def seed_initial_reading(
    container: Any,
    sections: Optional[dict[str, int]] = None,
) -> dict[str, int]:
    """启动期种子题库。

    Args:
        container: 业务容器
        sections: 每个 Section 要生成的套数;默认 {easy: 10, medium: 8, hard: 7, academic: 5}
    Returns:
        {"seeded_passages": N, "skipped": bool}
    """
    from ielts_buddy.services.reading_question_generator import (
        ReadingQuestionGenerator,
    )
    if sections is None:
        sections = {
            "easy": 10,
            "medium": 8,
            "hard": 7,
            "academic": 5,
        }
    repo = container.reading_practice
    if repo.count_passages() > 0:
        return {"seeded_passages": 0, "skipped": True}
    generator = ReadingQuestionGenerator()
    seeded = 0
    for section, set_count in sections.items():
        for set_idx in range(1, set_count + 1):
            questions = generator.generate_section(section)
            if not questions:
                continue
            for q in questions:
                qid = q.get("qid", 0)
                if qid < 1:
                    continue
                try:
                    repo.seed_passage(
                        section=str(section),
                        set_id=int(set_idx),
                        qid=int(qid),
                        passage_number=int(q.get("passage_number", 1)),
                        title=str(q.get("title", "")),
                        topic=str(q.get("topic", "")),
                        question_type=str(q.get("question_type", "multiple_choice")),
                        word_count=int(q.get("word_count", 600)),
                        passage_text=str(q.get("passage_text", "")),
                        stem=str(q.get("stem", "")),
                        options=q.get("options"),
                        answer=str(q.get("answer", "")),
                        explanation=str(q.get("explanation", "")),
                        source_line=q.get("source_line"),
                    )
                    seeded += 1
                except Exception as exc:
                    logger.warning(
                        "[reading] seed failed (sec=%s set=%d qid=%d): %s",
                        section, set_idx, qid, exc,
                    )
    return {"seeded_passages": seeded, "skipped": False}


__all__ = [
    "ReadingPracticeService",
    "SECTION_LABELS",
    "QUESTION_TYPE_LABELS",
    "seed_initial_reading",
]