"""/exam 模拟考试路由。

功能：
- GET /exam: 考试配置页面
- POST /api/exam/start: 开始考试，生成题目
- POST /api/exam/answer: 提交答案
- POST /api/exam/submit: 交卷
- POST /api/exam/skip: 跳过当前题
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ielts_buddy.core.models import Word
from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_vocab_service


router = APIRouter(tags=["exam"])
api_router = APIRouter(prefix="/api/exam", tags=["exam-api"])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


# =============================================================
# 内存中的考试会话
# =============================================================

_exam_sessions: dict[str, dict] = {}


class ExamSession:
    """考试会话"""

    def __init__(
        self,
        session_id: str,
        user_id: int,
        questions: list[dict],
        time_limit: int = 20,  # 分钟
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.questions = questions
        self.time_limit = time_limit
        self.current_index = 0
        self.answers: list[dict] = []
        self.started_at = datetime.now()
        self.deadline = self.started_at + timedelta(minutes=time_limit)

    def current_question(self) -> Optional[dict]:
        if self.current_index < len(self.questions):
            return self.questions[self.current_index]
        return None

    def answer_question(self, answer: str, is_correct: bool) -> dict:
        q = self.current_question()
        if q is None:
            raise ValueError("没有更多题目")
        result = {
            "word": q["word"],
            "correct_answer": q["answer"],
            "user_answer": answer,
            "is_correct": is_correct,
        }
        self.answers.append(result)
        self.current_index += 1
        return result

    def skip_question(self) -> dict:
        q = self.current_question()
        if q is None:
            raise ValueError("没有更多题目")
        result = {
            "word": q["word"],
            "correct_answer": q["answer"],
            "user_answer": None,
            "is_correct": None,
            "skipped": True,
        }
        self.answers.append(result)
        self.current_index += 1
        return result

    def is_finished(self) -> bool:
        return self.current_index >= len(self.questions)

    def is_time_up(self) -> bool:
        return datetime.now() > self.deadline

    def get_remaining_seconds(self) -> int:
        delta = self.deadline - datetime.now()
        return max(0, int(delta.total_seconds()))

    def get_results(self) -> dict:
        total = len(self.answers)
        correct = sum(1 for a in self.answers if a.get("is_correct") is True)
        wrong = sum(1 for a in self.answers if a.get("is_correct") is False)
        skipped = sum(1 for a in self.answers if a.get("skipped"))
        wrong_words = [a["word"] for a in self.answers if a.get("is_correct") is False]

        # 按 Band 分析
        band_breakdown: dict[int, dict[str, int]] = {}
        for ans in self.answers:
            band = ans.get("band", 5)
            if band not in band_breakdown:
                band_breakdown[band] = {"correct": 0, "wrong": 0}
            if ans.get("is_correct"):
                band_breakdown[band]["correct"] += 1
            else:
                band_breakdown[band]["wrong"] += 1

        duration = int((datetime.now() - self.started_at).total_seconds())

        return {
            "session_id": self.session_id,
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "skipped": skipped,
            "accuracy": correct / total if total > 0 else 0.0,
            "wrong_words": wrong_words,
            "band_breakdown": band_breakdown,
            "duration": duration,
            "time_limit": self.time_limit,
        }


def _generate_exam_questions(
    vocab: VocabService,
    count: int = 30,
    band: int = 7,
) -> list[dict]:
    """生成考试题目（混合英译中和中译英）"""
    pool = vocab.filter_by_band(band)
    if not pool:
        pool = vocab.words

    selected = random.sample(pool, min(count, len(pool))) if pool else []

    questions = []
    for i, w in enumerate(selected):
        # 交替使用英译中和中译英
        mode = "en2zh" if i % 2 == 0 else "zh2en"
        answer = w.meaning if mode == "en2zh" else w.word

        questions.append({
            "index": i + 1,
            "word": w.word,
            "word_data": w.model_dump(),
            "phonetic": w.phonetic,
            "pos": w.pos,
            "meaning": w.meaning,
            "example": w.example,
            "band": w.band,
            "mode": mode,
            "answer": answer,
        })
    return questions


# =============================================================
# 页面路由
# =============================================================


@router.get("/exam", response_class=HTMLResponse)
def page_exam(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """考试配置页面"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/exam.html",
        {
            "title": "模拟考试",
            "phase": 4,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


@api_router.post("/start")
def api_exam_start(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
    count: Annotated[int, Form(ge=10, le=50)] = 30,
    band: Annotated[int, Form(ge=5, le=9)] = 7,
    time_limit: Annotated[int, Form(ge=10, le=60)] = 20,
) -> dict:
    """开始考试"""
    session_id = uuid.uuid4().hex[:12]
    questions = _generate_exam_questions(vocab, count, band)

    if not questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="词库中没有足够的单词生成考试",
        )

    session = ExamSession(
        session_id=session_id,
        user_id=user.id,
        questions=questions,
        time_limit=time_limit,
    )
    _exam_sessions[session_id] = session

    return {
        "session_id": session_id,
        "total": len(questions),
        "current_index": 1,
        "question": session.current_question(),
        "time_limit": time_limit,
        "remaining_seconds": session.get_remaining_seconds(),
    }


@api_router.post("/answer")
def api_exam_answer(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[str, Form()],
    answer: Annotated[str, Form()],
) -> dict:
    """提交答案"""
    session = _exam_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="考试会话不存在或已过期")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作此考试")
    if session.is_finished():
        raise HTTPException(status_code=400, detail="考试已结束")
    if session.is_time_up():
        raise HTTPException(status_code=400, detail="考试时间已到")

    q = session.current_question()

    # 判断答案
    if q["mode"] == "en2zh":
        meanings = q["answer"].replace("；", "，").replace(",", "，").split("，")
        is_correct = any(
            m.strip() in answer or answer.strip() in m.strip()
            for m in meanings if m.strip()
        )
    else:
        is_correct = answer.strip().lower() == q["answer"].strip().lower()

    result = session.answer_question(answer, is_correct)

    # 记录到学习记录
    _record_learning(user.id, q["word_data"], is_correct)

    if session.is_finished():
        return {
            "finished": True,
            "results": session.get_results(),
        }

    return {
        "finished": False,
        "current_index": session.current_index + 1,
        "total": session.count if hasattr(session, 'count') else len(session.questions),
        "question": session.current_question(),
        "remaining_seconds": session.get_remaining_seconds(),
    }


@api_router.post("/skip")
def api_exam_skip(
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[str, Form()],
) -> dict:
    """跳过当前题"""
    session = _exam_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="考试会话不存在或已过期")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作此考试")
    if session.is_finished():
        raise HTTPException(status_code=400, detail="考试已结束")

    session.skip_question()

    if session.is_finished():
        return {"finished": True, "results": session.get_results()}

    return {
        "finished": False,
        "current_index": session.current_index + 1,
        "total": len(session.questions),
        "question": session.current_question(),
        "remaining_seconds": session.get_remaining_seconds(),
    }


@api_router.post("/submit")
def api_exam_submit(
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[str, Form()],
) -> dict:
    """交卷"""
    session = _exam_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="考试会话不存在或已过期")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作此考试")

    # 标记剩余题目为跳过
    while not session.is_finished():
        session.skip_question()

    results = session.get_results()
    del _exam_sessions[session_id]

    # 存储结果到数据库
    _save_exam_result(user.id, results)

    return {"results": results}


@api_router.get("/status/{session_id}")
def api_exam_status(
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: str,
) -> dict:
    """获取考试状态"""
    session = _exam_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="考试会话不存在或已过期")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作此考试")

    if session.is_time_up():
        return {
            "time_up": True,
            "remaining_seconds": 0,
        }

    return {
        "time_up": False,
        "remaining_seconds": session.get_remaining_seconds(),
        "current_index": session.current_index + 1,
        "total": len(session.questions),
    }


def _record_learning(user_id: int, word_data: dict, correct: bool) -> None:
    """记录到学习记录"""
    try:
        from ielts_buddy.web.main import app
        container = getattr(app.state, "container", None)
        if container is not None and hasattr(container, "learning"):
            word = Word(**word_data)
            container.learning.upsert_record(user_id, word, correct, source="exam")
    except Exception:
        pass


def _save_exam_result(user_id: int, results: dict) -> None:
    """保存考试结果"""
    try:
        from ielts_buddy.web.main import app
        container = getattr(app.state, "container", None)
        if container is not None and hasattr(container, "exam"):
            from ielts_buddy.core.models import ExamSession as ExamSessionModel
            import json
            session = ExamSessionModel(
                id=results["session_id"],
                user_id=user_id,
                questions=[],
                time_limit=results["time_limit"],
                started_at=datetime.now().isoformat(timespec="seconds"),
            )
            session.finish(
                score=results["correct"],
                total=results["total"],
                accuracy=results["accuracy"],
                band_breakdown=results["band_breakdown"],
                weak_words=results["wrong_words"],
                duration=results["duration"],
            )
            container.exam.save_exam_session(user_id, session)
    except Exception:
        pass


__all__ = ["router", "api_router"]
