"""/study/quiz 词汇测验路由。

功能：
- GET /study/quiz: 显示测验配置页面
- POST /api/quiz/start: 开始测验，生成题目
- POST /api/quiz/answer: 提交答案
- POST /api/quiz/skip: 跳过当前题
- POST /api/quiz/finish: 结束测验，显示结果
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ielts_buddy.core.models import Word
from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_vocab_service


router = APIRouter(tags=["quiz"])
api_router = APIRouter(prefix="/api/quiz", tags=["quiz-api"])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


# =============================================================
# 内存中的测验会话（生产环境应存 Redis 或数据库）
# =============================================================

_quiz_sessions: dict[str, dict] = {}


class QuizSession:
    """测验会话"""

    def __init__(
        self,
        session_id: str,
        user_id: int,
        questions: list[dict],
        band: int = 7,
        count: int = 10,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.questions = questions
        self.band = band
        self.count = count
        self.current_index = 0
        self.answers: list[dict] = []
        self.started_at = datetime.now()
        self.mode = "en2zh"  # 英译中模式

    def current_question(self) -> Optional[dict]:
        if self.current_index < len(self.questions):
            return self.questions[self.current_index]
        return None

    def answer_question(self, answer: str, correct: bool) -> dict:
        q = self.current_question()
        if q is None:
            raise ValueError("没有更多题目")
        result = {
            "word": q["word"],
            "correct_answer": q["answer"],
            "user_answer": answer,
            "is_correct": correct,
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

    def get_results(self) -> dict:
        total = len(self.answers)
        correct = sum(1 for a in self.answers if a.get("is_correct") is True)
        wrong = sum(1 for a in self.answers if a.get("is_correct") is False)
        skipped = sum(1 for a in self.answers if a.get("skipped"))
        wrong_words = [a["word"] for a in self.answers if a.get("is_correct") is False]

        return {
            "session_id": self.session_id,
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "skipped": skipped,
            "accuracy": correct / total if total > 0 else 0.0,
            "wrong_words": wrong_words,
            "answers": self.answers,
            "band": self.band,
        }


def _generate_questions(
    vocab: VocabService,
    user_id: int,
    count: int = 10,
    band: int = 7,
) -> list[dict]:
    """从词库生成测验题目（英译中模式）"""
    # 按指定 Band 筛选
    pool = vocab.filter_by_band(band)
    if not pool:
        # 如果没有指定 Band 的词，降低要求
        pool = vocab.all_words()

    # 随机抽取
    questions_count = min(count, len(pool))
    selected = random.sample(pool, questions_count) if pool else []

    questions = []
    for w in selected:
        questions.append({
            "word": w.word,
            "word_data": w.model_dump(),
            "phonetic": w.phonetic,
            "pos": w.pos,
            "meaning": w.meaning,
            "answer": w.meaning,  # 英译中，答案为中文释义
            "example": w.example,
        })
    return questions


# =============================================================
# 页面路由
# =============================================================


@router.get("/study/quiz", response_class=HTMLResponse)
def page_quiz(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """测验配置页面"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/study_quiz.html",
        {
            "title": "词汇测验",
            "phase": 2,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


@api_router.post("/start")
def api_quiz_start(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
    count: Annotated[int, Form(ge=5, le=50)] = 10,
    band: Annotated[int, Form(ge=5, le=9)] = 7,
) -> dict:
    """开始测验，生成题目"""
    # 生成测验会话
    session_id = uuid.uuid4().hex[:12]
    questions = _generate_questions(vocab, user.id, count, band)

    if not questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="词库中没有足够的单词生成测验",
        )

    session = QuizSession(
        session_id=session_id,
        user_id=user.id,
        questions=questions,
        band=band,
        count=count,
    )
    _quiz_sessions[session_id] = session

    return {
        "session_id": session_id,
        "total": len(questions),
        "current_index": 1,
        "question": session.current_question(),
    }


@api_router.post("/answer")
def api_quiz_answer(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[str, Form()],
    answer: Annotated[str, Form()],
) -> dict:
    """提交答案"""
    session = _quiz_sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测验会话不存在或已过期",
        )

    if session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作此测验",
        )

    if session.is_finished():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="测验已结束",
        )

    # 判断答案是否正确（英译中：模糊匹配）
    q = session.current_question()
    correct_meanings = q["answer"].replace("；", "，").replace(",", "，").split("，")
    is_correct = any(
        m.strip() in answer or answer.strip() in m.strip()
        for m in correct_meanings if m.strip()
    )

    # 记录答案
    result = session.answer_question(answer, is_correct)

    # 记录到学习记录
    _record_learning(user.id, q["word_data"], is_correct)

    # 返回下一题或结束
    if session.is_finished():
        results = session.get_results()
        # 清理会话
        del _quiz_sessions[session_id]
        return {
            "finished": True,
            "results": results,
        }

    return {
        "finished": False,
        "current_index": session.current_index + 1,
        "total": session.count,
        "question": session.current_question(),
        "last_answer": result,
    }


@api_router.post("/next")
def api_quiz_next(
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[str, Form()],
) -> dict:
    """获取下一题"""
    session = _quiz_sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测验会话不存在或已过期",
        )

    if session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作此测验",
        )

    if session.is_finished():
        results = session.get_results()
        del _quiz_sessions[session_id]
        return {"finished": True, "results": results}

    return {
        "finished": False,
        "current_index": session.current_index + 1,
        "total": session.count,
        "question": session.current_question(),
    }


@api_router.post("/skip")
def api_quiz_skip(
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[str, Form()],
) -> dict:
    """跳过当前题"""
    session = _quiz_sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测验会话不存在或已过期",
        )

    if session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作此测验",
        )

    if session.is_finished():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="测验已结束",
        )

    session.skip_question()

    if session.is_finished():
        results = session.get_results()
        del _quiz_sessions[session_id]
        return {
            "finished": True,
            "results": results,
        }

    return {
        "finished": False,
        "current_index": session.current_index + 1,
        "total": session.count,
        "question": session.current_question(),
    }


@api_router.post("/finish")
def api_quiz_finish(
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[str, Form()],
) -> dict:
    """提前结束测验"""
    session = _quiz_sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="测验会话不存在或已过期",
        )

    if session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作此测验",
        )

    # 标记剩余题目为跳过
    while not session.is_finished():
        session.skip_question()

    results = session.get_results()
    del _quiz_sessions[session_id]
    return {"results": results}


def _record_learning(user_id: int, word_data: dict, correct: bool) -> None:
    """将测验结果记录到学习记录"""
    try:
        from ielts_buddy.web.main import app
        container = getattr(app.state, "container", None)
        if container is not None and hasattr(container, "learning"):
            word = Word(**word_data)
            container.learning.upsert_record(user_id, word, correct, source="quiz")
    except Exception:
        # 忽略记录错误，不影响测验流程
        pass


__all__ = ["router", "api_router"]
