"""真·听力题库业务服务（v3.7 P2 新增）。

PRD: docs/web-mvp/plans/phase-9-listening-practice.md §5.3-5.4

业务层封装 calling chain:
  1) 列 Sections / 列出套题 / 抽一套题
  2) 单题详情:有 audio 直接给 URL,无 audio → 触发 TTS 合成
  3) 提交答案:判分 → 落 listening_attempts
  4) 错词回填(目前仅落 attempts;v3.8 再做"错题集")
  5) 30 天音频清理(lifespan 启动期触发)

设计:
- 同步实现,web 端走 asyncio.to_thread 转异步
- 任何一个 step 失败 → log warning,不阻断 UI
- TTS 是后台异步任务,不阻塞抽题/答题
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from ielts_buddy.core.repository import ListeningPracticeRepository
from ielts_buddy.services.listening_question_generator import (
    ListeningQuestionGenerator,
)
from ielts_buddy.web import config as web_config
from ielts_buddy.web.listening_tts_service import (
    ListeningTTSService,
    audio_path_for,
)

logger = logging.getLogger(__name__)


# =============================================================
# 常量
# =============================================================


SECTION_LABELS = {
    1: "Section 1 · 日常社交",
    2: "Section 2 · 校园/工作",
    3: "Section 3 · 学术讨论",
    4: "Section 4 · 学术讲座",
}

QUESTION_TYPE_LABELS = {
    "multiple_choice": "选择题",
    "form_completion": "填空题",
    "matching": "匹配题",
}


# =============================================================
# Dataclass 风格返回结构
# =============================================================


class StartSetResult:
    """抽一套题后的响应结构。"""

    def __init__(
        self,
        section: int,
        set_id: int,
        scenario: str,
        questions: list[dict],
    ) -> None:
        self.section = section
        self.set_id = set_id
        self.scenario = scenario
        self.questions = questions


class SubmitAnswerResult:
    """单题提交响应。"""

    def __init__(
        self,
        question_id: int,
        is_correct: bool,
        correct_answer: str,
        explanation: str,
        transcript: str,
        question_type: str,
        options: Optional[list[str]],
        played_count: int,
        attempt_id: int,
        next_question_id: Optional[int] = None,
    ) -> None:
        self.question_id = question_id
        self.is_correct = is_correct
        self.correct_answer = correct_answer
        self.explanation = explanation
        self.transcript = transcript
        self.question_type = question_type
        self.options = options
        self.played_count = played_count
        self.attempt_id = attempt_id
        self.next_question_id = next_question_id


# =============================================================
# 业务服务
# =============================================================


class ListeningPracticeService:
    """真·听力题库业务服务。

    Args:
        container: 业务容器(拿 .listening_practice + .learning 等)
        user_id: 当前 web 用户 ID
    """

    def __init__(
        self,
        container: Any,
        user_id: int,
        tts: Optional[ListeningTTSService] = None,
        generator: Optional[ListeningQuestionGenerator] = None,
    ) -> None:
        self._container = container
        self._user_id = int(user_id)
        # TTS / Generator 默认走单例
        self._tts = tts or self._default_tts()
        self._generator = generator or self._default_generator()

    # =============================================================
    # 工厂方法
    # =============================================================

    def _default_tts(self) -> Optional[ListeningTTSService]:
        try:
            return ListeningTTSService()
        except Exception as exc:
            logger.warning("[listening] TTS init failed: %s", exc)
            return None

    def _default_generator(self) -> ListeningQuestionGenerator:
        try:
            return ListeningQuestionGenerator()
        except Exception as exc:
            logger.warning("[listening] Generator init failed: %s", exc)
            return ListeningQuestionGenerator(llm_client=None)  # 走 mock

    # =============================================================
    # 列表 + 概览
    # =============================================================

    def list_sections(self) -> list[dict]:
        """4 个 Section 概览(含个人正确率)。"""
        repo: ListeningPracticeRepository = self._container.listening_practice
        sections = repo.list_sections_with_counts()
        stats = self.get_user_stats()
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
                "total_questions": int(s["total_questions"]),
                "user_attempts": user_attempts,
                "user_accuracy": accuracy,
            })
        return out

    def list_sets(self, section: int) -> list[dict]:
        """列出某 Section 下所有套题。"""
        repo: ListeningPracticeRepository = self._container.listening_practice
        return repo.list_sets_by_section(int(section))

    # =============================================================
    # 抽题
    # =============================================================

    def start_set(self, section: int, set_id: int) -> Optional[StartSetResult]:
        """抽一套题(section + set_id 必填;MVP 不做随机)。"""
        repo: ListeningPracticeRepository = self._container.listening_practice
        rows = repo.list_questions_by_set(int(section), int(set_id))
        if not rows:
            return None
        # 同一套的 scenario 应该一致;取第一个
        scenario = rows[0].get("scenario") or ""
        return StartSetResult(
            section=int(section),
            set_id=int(set_id),
            scenario=scenario,
            questions=[
                self._normalize_question_for_client(q) for q in rows
            ],
        )

    def start_random_set(
        self, section: Optional[int] = None
    ) -> Optional[StartSetResult]:
        """随机抽一套题(可指定 section)。"""
        repo: ListeningPracticeRepository = self._container.listening_practice
        sections = repo.list_sections_with_counts()
        if section is not None:
            sections = [
                s for s in sections if s["section"] == int(section)
            ]
        available: list[tuple[int, int]] = []
        for s in sections:
            sec = int(s["section"])
            sets = repo.list_sets_by_section(sec)
            for st in sets:
                available.append((sec, int(st["set_id"])))
        if not available:
            return None
        import random
        sec, set_id = random.choice(available)
        return self.start_set(sec, set_id)

    # =============================================================
    # 单题详情(触发 TTS 合成)
    # =============================================================

    def get_question(self, question_id: int) -> Optional[dict]:
        """单题详情。若无 audio_path → 触发 TTS 合成(后台)。"""
        repo: ListeningPracticeRepository = self._container.listening_practice
        q = repo.get_question(int(question_id))
        if q is None:
            return None
        # 若缺 audio_path,后台合成
        if not q.get("audio_path"):
            self._synthesize_audio_async(int(question_id), q.get("transcript", ""))
        return self._normalize_question_for_client(q)

    def _synthesize_audio_async(self, question_id: int, transcript: str) -> None:
        """后台尝试合成音频;失败不影响主流程。

        走同步 fallback(测试环境无 asyncio),实际 web 端会被 to_thread 包到线程池。
        """
        try:
            self.synthesize_audio(question_id, transcript)
        except Exception as exc:
            logger.warning(
                "[listening] async TTS failed qid=%d: %s",
                question_id, exc,
            )

    def synthesize_audio(
        self,
        question_id: int,
        transcript: str = "",
    ) -> Optional[str]:
        """同步合成音频并落库 audio_path。失败返回 None。

        Args:
            question_id: 题 ID
            transcript: 原文台词(可选,空时从 DB 查)
        Returns:
            相对路径(如 "1/q2.mp3")或 None
        """
        repo: ListeningPracticeRepository = self._container.listening_practice
        if not transcript:
            q = repo.get_question(int(question_id))
            if q is None:
                return None
            transcript = q.get("transcript", "")
        if not transcript:
            return None
        if self._tts is None or not self._tts.is_available():
            return None
        # 查 section
        q = repo.get_question(int(question_id))
        if q is None:
            return None
        section = int(q["section"])
        path = self._tts.synthesize_to_file(
            text=transcript,
            section=section,
            question_id=int(question_id),
        )
        if path is None:
            return None
        rel_path = path.name  # 仅存文件名;section 从 DB 拿
        repo.set_audio_path(
            question_id=int(question_id),
            audio_path=str(path),
            audio_generated_at=datetime.now().isoformat(timespec="seconds"),
        )
        return str(path)

    # =============================================================
    # 提交答案
    # =============================================================

    def submit_answer(
        self,
        question_id: int,
        user_answer: str,
        duration_sec: float = 0.0,
        played_count: int = 1,
    ) -> Optional[SubmitAnswerResult]:
        """提交答案:判分 + 落 attempts + 找下一题。"""
        repo: ListeningPracticeRepository = self._container.listening_practice
        q = repo.get_question(int(question_id))
        if q is None:
            return None
        user_answer_clean = (user_answer or "").strip()
        correct_answer = (q.get("answer") or "").strip()
        is_correct = self._is_answer_correct(
            user_answer_clean, correct_answer, q.get("question_type", "")
        )
        attempt_id = repo.record_attempt(
            user_id=self._user_id,
            question_id=int(question_id),
            user_answer=user_answer_clean,
            is_correct=is_correct,
            duration_sec=float(duration_sec),
            played_count=int(played_count) if played_count >= 1 else 1,
        )
        # 找下一题:同 section+set 的下一条 qid;若无则返回 None
        next_qid = self._find_next_question_id(
            int(q["section"]), int(q["set_id"]), int(q["qid"])
        )
        return SubmitAnswerResult(
            question_id=int(question_id),
            is_correct=is_correct,
            correct_answer=correct_answer,
            explanation=q.get("explanation") or "",
            transcript=q.get("transcript") or "",
            question_type=q.get("question_type") or "",
            options=q.get("options"),
            played_count=int(played_count) if played_count >= 1 else 1,
            attempt_id=int(attempt_id),
            next_question_id=next_qid,
        )

    def _is_answer_correct(
        self, user_answer: str, correct: str, qtype: str
    ) -> bool:
        """判分:选择题/匹配 → 不区分大小写比对;填空 → 大小写不敏感 + 简单归一化。"""
        u = (user_answer or "").strip()
        c = (correct or "").strip()
        if not u or not c:
            return False
        if qtype in ("multiple_choice", "matching"):
            return u.upper() == c.upper()
        # 填空题:小写 + 去标点 + 多空格合一
        norm = lambda s: re.sub(r"\s+", " ",
                                re.sub(r"[^\w\s]", "", s.lower())).strip()
        return norm(u) == norm(c)

    def _find_next_question_id(
        self, section: int, set_id: int, current_qid: int
    ) -> Optional[int]:
        repo: ListeningPracticeRepository = self._container.listening_practice
        rows = repo.list_questions_by_set(int(section), int(set_id))
        ids = sorted(int(r["id"]) for r in rows)
        for i, qid in enumerate(ids):
            # ids 是按 set 内 qid 排序后映射的真实 id;但因为同套可能 qid 不连续,
            # 这里取「按 qid 排序后下一条」的 id
            pass
        # 重新按 qid 排序
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
        section: Optional[int] = None,
    ) -> tuple[list[dict], int]:
        repo: ListeningPracticeRepository = self._container.listening_practice
        return repo.list_user_attempts(
            user_id=self._user_id,
            page=page,
            size=size,
            section=int(section) if section is not None else None,
        )

    def get_user_stats(self) -> dict:
        """聚合用户统计,统一返回字段名。

        Repo 返回 ``correct_count``(SQL 风格),Service 标准化为 ``correct``。
        """
        repo: ListeningPracticeRepository = self._container.listening_practice
        raw = repo.get_user_stats(self._user_id)
        return {
            "total_attempts": int(raw.get("total_attempts", 0)),
            "correct": int(raw.get("correct_count", 0)),
            "accuracy": raw.get("accuracy"),
            "by_section": raw.get("by_section", {}),
        }

    # =============================================================
    # Helpers
    # =============================================================

    def _normalize_question_for_client(self, q: dict) -> dict:
        """把 DB row 转成前端友好结构(过滤掉 answer/explanation/transcript 等敏感字段)。"""
        return {
            "id": int(q.get("id")),
            "section": int(q.get("section")),
            "set_id": int(q.get("set_id")),
            "qid": int(q.get("qid")),
            "scenario": q.get("scenario") or "",
            "question_type": q.get("question_type") or "",
            "question_type_label": QUESTION_TYPE_LABELS.get(
                q.get("question_type") or "", q.get("question_type") or ""
            ),
            "stem": q.get("stem") or "",
            "options": q.get("options"),
            "audio_path": q.get("audio_path"),
            "audio_url": (
                f"/api/listening/practice/audio/{int(q.get('id'))}"
                if q.get("audio_path") else None
            ),
            "audio_generated_at": q.get("audio_generated_at"),
        }

    def get_audio_path(self, question_id: int) -> Optional[Path]:
        """防 IDOR:由调用方保证 user 已登录;audio 是公开资源,所有人可听。"""
        repo: ListeningPracticeRepository = self._container.listening_practice
        q = repo.get_question(int(question_id))
        if q is None or not q.get("audio_path"):
            return None
        p = Path(q["audio_path"])
        return p if p.exists() else None


# =============================================================
# 模块级入口(供 main.py lifespan 调用)
# =============================================================


def seed_initial_questions(
    container: Any,
    s1: Optional[int] = None,
    s2: Optional[int] = None,
    s3: Optional[int] = None,
    s4: Optional[int] = None,
    auto_trigger_tts: bool = True,
) -> dict[str, int]:
    """启动期种子题库(LLM 出题 + 落库 + 可选 TTS)。

    设计:
    - 已有任何题则跳过(幂等)
    - 跑后台 fire-and-forget,不阻塞 web 启动
    - 失败也无所谓,下次启动再试

    Returns:
        {"seeded_questions": N, "synthesized_audio": M, "skipped": bool}
    """
    s1 = s1 if s1 is not None else web_config.LISTENING_SEED_S1
    s2 = s2 if s2 is not None else web_config.LISTENING_SEED_S2
    s3 = s3 if s3 is not None else web_config.LISTENING_SEED_S3
    s4 = s4 if s4 is not None else web_config.LISTENING_SEED_S4
    distribution = {1: s1, 2: s2, 3: s3, 4: s4}

    repo: ListeningPracticeRepository = container.listening_practice
    if repo.count_questions() > 0:
        return {"seeded_questions": 0, "synthesized_audio": 0, "skipped": True}

    generator = ListeningQuestionGenerator()
    tts: Optional[ListeningTTSService] = None
    if auto_trigger_tts:
        try:
            tts = ListeningTTSService()
        except Exception as exc:
            logger.warning("[listening] seed TTS init failed: %s", exc)
            tts = None

    seeded = 0
    synthed = 0
    for section, count in distribution.items():
        for set_idx in range(1, count + 1):
            questions = generator.generate_section(int(section))
            if not questions:
                continue
            for q in questions:
                qid = q.get("qid", 0)
                if qid < 1:
                    continue
                try:
                    new_id = repo.seed_question(
                        section=int(section),
                        set_id=int(set_idx),
                        qid=int(qid),
                        scenario=str(q.get("scenario", "")),
                        question_type=str(q.get("question_type", "multiple_choice")),
                        stem=str(q.get("stem", "")),
                        options=q.get("options"),
                        answer=str(q.get("answer", "")),
                        explanation=str(q.get("explanation", "")),
                        transcript=str(q.get("transcript", "")),
                    )
                    seeded += 1
                    if tts and tts.is_available():
                        path = tts.synthesize_to_file(
                            text=str(q.get("transcript", "")),
                            section=int(section),
                            question_id=int(new_id),
                        )
                        if path is not None:
                            repo.set_audio_path(
                                question_id=int(new_id),
                                audio_path=str(path),
                                audio_generated_at=datetime.now().isoformat(
                                    timespec="seconds"
                                ),
                            )
                            synthed += 1
                except Exception as exc:
                    logger.warning(
                        "[listening] seed q failed (sec=%d set=%d qid=%d): %s",
                        section, set_idx, qid, exc,
                    )
    return {
        "seeded_questions": seeded,
        "synthesized_audio": synthed,
        "skipped": False,
    }


def purge_expired_audio(
    container: Any,
    retention_days: int = 30,
) -> dict[str, int]:
    """跨用户清理 retention_days 天前的听力音频文件。"""
    repo: ListeningPracticeRepository = container.listening_practice
    try:
        expired = repo.list_expired_audio_paths(retention_days)
    except Exception as exc:
        logger.warning("[listening] list_expired_audio_paths failed: %s", exc)
        return {"files_deleted": 0, "rows_nulled": 0}

    files_deleted = 0
    rows_nulled = 0
    for qid, audio_path in expired:
        if audio_path:
            p = Path(audio_path)
            if p.exists():
                try:
                    p.unlink()
                    files_deleted += 1
                except Exception:
                    pass
        try:
            repo.set_audio_path(
                question_id=int(qid),
                audio_path=None,
                audio_generated_at=None,
            )
            rows_nulled += 1
        except Exception:
            pass
    return {"files_deleted": files_deleted, "rows_nulled": rows_nulled}


__all__ = [
    "ListeningPracticeService",
    "StartSetResult",
    "SubmitAnswerResult",
    "SECTION_LABELS",
    "QUESTION_TYPE_LABELS",
    "seed_initial_questions",
    "purge_expired_audio",
]