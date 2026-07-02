"""模拟考试服务：生成考试、提交答案、生成报告、历史记录

W2 阶段：所有 SQL 调用委托给 SQLiteExamRepository。
W4 阶段：未传 db_path 时按 config.mode 选 local/online 容器。
W5 阶段：未传 user_id 时按 get_user_id() 解析（env > config > 1）。
"""
from __future__ import annotations

import json
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ielts_buddy.core.models import ExamQuestion, ExamReport, ExamSession
from ielts_buddy.repositories import create_repositories


class ExamService:
    """模拟考试服务（W2: 委托给 Repository；W4: 模式分发；W5: user_id 注入）"""

    def __init__(self, db_path: Path | None = None, user_id: int | None = None) -> None:
        # 显式传 db_path = 强制走 local（保持旧测试 / 旧调用方行为不变）
        if db_path is not None:
            self._container = create_repositories(mode="local", db_path=db_path)
        else:
            from ielts_buddy.core.config import Config, get_mode
            cfg = Config()
            mode = get_mode(cfg)
            self._container = create_repositories(mode=mode)
        self._repo = self._container.exam
        # W5: user_id 显式传 > get_user_id() 解析 > 1
        if user_id is not None:
            self._user_id = user_id
        else:
            from ielts_buddy.core.config import Config, get_user_id
            self._user_id = get_user_id(Config())
        # 保存当前 session 供 submit/finish 内部用
        self._current_session: ExamSession | None = None

    def close(self) -> None:
        self._container.close()

    # ---- 向后兼容 ----

    @property
    def _conn(self):
        return self._container._conn

    @property
    def _db_path(self) -> Path:
        return self._container._db_path

    # ---- 考试流程 ----

    def create_exam(
        self,
        band: int | None = None,
        count: int = 30,
        time_limit: int = 20,
    ) -> ExamSession:
        """生成模拟考试，从词库随机选词并混合 en2zh/zh2en 题型"""
        from ielts_buddy.services.vocab_service import VocabService

        svc = VocabService()
        svc.load_all()

        words = svc.random_words(count, band)
        if not words:
            raise ValueError("词库中没有足够的单词生成考试")

        questions: list[ExamQuestion] = []
        for i, w in enumerate(words):
            mode = random.choice(["en2zh", "zh2en"])
            if mode == "en2zh":
                prompt = f"{w.word}  {w.phonetic}  [{w.pos}]"
                answer = w.meaning
            else:
                prompt = f"{w.meaning}  [{w.pos}]"
                answer = w.word

            questions.append(
                ExamQuestion(
                    index=i,
                    word=w.word,
                    mode=mode,
                    prompt=prompt,
                    answer=answer,
                    band=w.band,
                )
            )

        session = ExamSession(
            id=uuid.uuid4().hex[:12],
            user_id=self._user_id,
            questions=questions,
            time_limit=time_limit,
            started_at=datetime.now().isoformat(timespec="seconds"),
            band_filter=band,
        )
        # 立刻落库
        self._save_exam(session)
        self._current_session = session
        return session

    def submit_answer(
        self, session: ExamSession, q_index: int, answer: str
    ) -> dict:
        """提交单题答案（保持原 Service 接口，内存判分 + 落库）"""
        if q_index < 0 or q_index >= len(session.questions):
            raise IndexError(f"题号 {q_index} 超出范围 (共 {len(session.questions)} 题)")

        q = session.questions[q_index]
        q.user_answer = answer

        if q.mode == "en2zh":
            meanings = q.answer.replace("；", "，").replace(",", "，").split("，")
            q.is_correct = any(
                m.strip() in answer or answer in m.strip()
                for m in meanings if m.strip()
            )
        else:
            q.is_correct = answer.strip().lower() == q.answer.strip().lower()

        # 落库（更新 questions JSON）
        self._update_session_questions(session)
        return {"correct": q.is_correct, "answer": q.answer}

    def finish_exam(self, session: ExamSession) -> ExamReport:
        """结束考试，生成报告并保存到数据库"""
        now = datetime.now().isoformat(timespec="seconds")
        session.finished_at = now

        answered = [q for q in session.questions if q.is_correct is not None]
        correct_count = sum(1 for q in answered if q.is_correct)
        total = len(answered)
        accuracy = correct_count / total if total > 0 else 0.0

        band_breakdown: dict[int, dict[str, int]] = {}
        for q in answered:
            if q.band not in band_breakdown:
                band_breakdown[q.band] = {"correct": 0, "wrong": 0}
            if q.is_correct:
                band_breakdown[q.band]["correct"] += 1
            else:
                band_breakdown[q.band]["wrong"] += 1

        weak_words = [q.word for q in answered if not q.is_correct]
        started = datetime.fromisoformat(session.started_at)
        finished = datetime.fromisoformat(session.finished_at)
        duration = int((finished - started).total_seconds())

        report = ExamReport(
            session_id=session.id,
            user_id=self._user_id,
            score=correct_count,
            total=total,
            accuracy=accuracy,
            band_breakdown=band_breakdown,
            weak_words=weak_words,
            duration=duration,
            finished_at=now,
        )

        # 落库（更新 finished_at + 报告字段）
        # 若 session 还没落库（测试场景：直接 finish 未 create），先 INSERT
        row = self._conn.execute(
            "SELECT 1 FROM exam_sessions WHERE id = ?", (session.id,)
        ).fetchone()
        if row is None:
            self._save_exam(session)
        self._finalize_exam(session, report)
        return report

    def _save_exam(self, session: ExamSession, report: ExamReport | None = None) -> None:
        """保存考试记录到 SQLite。

        向后兼容：
        - ``_save_exam(session)``：只保存 session（不写报告字段）
        - ``_save_exam(session, report)``：保存 session + 报告（结束考试时）
        """
        questions_json = json.dumps(
            [q.model_dump() for q in session.questions], ensure_ascii=False
        )
        if report is not None:
            self._conn.execute(
                """INSERT OR REPLACE INTO exam_sessions
                   (id, user_id, questions, time_limit, started_at, finished_at, band_filter,
                    score, total, accuracy, duration, weak_words, band_breakdown)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id, self._user_id, questions_json, session.time_limit,
                    session.started_at, report.finished_at, session.band_filter,
                    report.score, report.total, report.accuracy, report.duration,
                    json.dumps(report.weak_words, ensure_ascii=False),
                    json.dumps(report.band_breakdown, ensure_ascii=False),
                ),
            )
        else:
            self._conn.execute(
                """INSERT OR REPLACE INTO exam_sessions
                   (id, user_id, questions, time_limit, started_at, finished_at, band_filter,
                    score, total, accuracy, duration, weak_words, band_breakdown)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id, self._user_id, questions_json, session.time_limit,
                    session.started_at, session.finished_at, session.band_filter,
                    0, 0, 0.0, 0,
                    "[]", "{}",
                ),
            )
        self._conn.commit()

    def _update_session_questions(self, session: ExamSession) -> None:
        """更新 questions JSON（提交答案时）"""
        questions_json = json.dumps(
            [q.model_dump() for q in session.questions], ensure_ascii=False
        )
        self._conn.execute(
            "UPDATE exam_sessions SET questions = ? WHERE id = ?",
            (questions_json, session.id),
        )
        self._conn.commit()

    def _finalize_exam(self, session: ExamSession, report: ExamReport) -> None:
        """考试结束时更新所有报告字段"""
        self._conn.execute(
            """UPDATE exam_sessions SET
               finished_at = ?, score = ?, total = ?, accuracy = ?,
               duration = ?, weak_words = ?, band_breakdown = ?
               WHERE id = ?""",
            (
                report.finished_at, report.score, report.total, report.accuracy,
                report.duration,
                json.dumps(report.weak_words, ensure_ascii=False),
                json.dumps(report.band_breakdown, ensure_ascii=False),
                session.id,
            ),
        )
        self._conn.commit()

    def get_exam_history(self, limit: int = 10) -> list[ExamReport]:
        """获取历史考试记录"""
        histories = self._repo.get_exam_history(self._user_id, limit)
        return [
            ExamReport(
                session_id=h["session_id"],
                user_id=self._user_id,
                score=h["score"],
                total=h["total"],
                accuracy=h["accuracy"],
                band_breakdown=h["band_breakdown"],
                weak_words=h["weak_words"],
                duration=h["duration"],
                finished_at=h["finished_at"],
            )
            for h in histories
        ]
