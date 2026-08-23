"""/reading/practice Reading 题库路由（v3.8 P3.2 新增）。

PRD: docs/web-mvp/plans/phase-10-reading-and-resources.md §5.3

端点:
- GET  /reading/practice                     : 主页(4 个 Section 档位)
- GET  /api/reading/practice/sections         : 列 Section 概览 + 个人正确率
- GET  /api/reading/practice/section/{n}      : 列该 Section 下所有套题
- POST /api/reading/practice/start            : 抽指定 (section, set_id) 套题
- POST /api/reading/practice/random           : 随机抽套题
- GET  /api/reading/practice/question/{qid}   : 单题详情
- POST /api/reading/practice/submit           : 提交答案
- GET  /api/reading/practice/history          : 我的历史
- GET  /api/reading/practice/stats            : 我的统计
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ielts_buddy.services.reading_practice_service import (
    ReadingPracticeService,
    SECTION_LABELS,
    QUESTION_TYPE_LABELS,
)
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reading-practice"])
api_router = APIRouter(
    prefix="/api/reading/practice", tags=["reading-practice-api"]
)


# =============================================================
# Pydantic models
# =============================================================


class SectionSummary(BaseModel):
    section: str
    name: str
    total_sets: int
    total_passages: int
    user_attempts: int
    user_accuracy: Optional[float] = None


class SectionsResponse(BaseModel):
    sections: list[SectionSummary]


class SetSummary(BaseModel):
    set_id: int
    section: str
    first_passage: int
    question_count: int
    title: str
    topic: str


class QuestionForClient(BaseModel):
    id: int
    section: str
    set_id: int
    qid: int
    passage_number: int
    title: str
    topic: str
    question_type: str
    question_type_label: str
    word_count: int
    passage_text: str
    stem: str
    options: Optional[list[str]] = None
    source_line: Optional[int] = None


class StartSetResponse(BaseModel):
    section: str
    set_id: int
    section_label: str
    scenario: str
    questions: list[QuestionForClient]


class StartSectionSetRequest(BaseModel):
    section: str
    set_id: int


class StartRandomRequest(BaseModel):
    section: Optional[str] = None


class SubmitAnswerRequest(BaseModel):
    question_id: int
    user_answer: str
    duration_sec: float = 0.0


class SubmitAnswerResponse(BaseModel):
    question_id: int
    is_correct: bool
    correct_answer: str
    explanation: str
    transcript: str
    question_type: str
    attempt_id: int
    next_question_id: Optional[int] = None


class HistoryItem(BaseModel):
    attempt_id: int
    question_id: int
    section: str
    set_id: int
    qid: int
    title: str
    user_answer: str
    correct_answer: str
    is_correct: bool
    duration_sec: float
    created_at: str


class HistoryResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[HistoryItem]


class SectionStat(BaseModel):
    attempts: int
    correct: int
    accuracy: Optional[float] = None


class UserStatsResponse(BaseModel):
    total_attempts: int
    correct: int
    accuracy: Optional[float] = None
    by_section: dict[str, SectionStat]


# =============================================================
# Helpers
# =============================================================


def _get_container(request: Request) -> Any:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="业务容器未初始化")
    return container


def _get_service(request: Request, user_id: int) -> ReadingPracticeService:
    container = _get_container(request)
    return ReadingPracticeService(container=container, user_id=user_id)


# =============================================================
# 页面
# =============================================================


@router.get("/reading/practice", response_class=HTMLResponse)
def page_reading_practice(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/reading_practice.html",
        {
            "title": "Reading 真题题库",
            "phase": 9,
            "current_user": user,
            "request": request,
            "section_labels": SECTION_LABELS,
            "question_type_labels": QUESTION_TYPE_LABELS,
        },
    )


# =============================================================
# GET /api/reading/practice/sections
# =============================================================


@api_router.get("/sections", response_model=SectionsResponse)
async def api_sections(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> SectionsResponse:
    svc = _get_service(request, int(user.id))
    data = await asyncio.to_thread(svc.list_sections)
    return SectionsResponse(
        sections=[SectionSummary(**d) for d in data]
    )


# =============================================================
# GET /api/reading/practice/section/{section}
# =============================================================


@api_router.get("/section/{section}", response_model=list[SetSummary])
async def api_sets_by_section(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    section: str,
) -> list[SetSummary]:
    if section not in ("easy", "medium", "hard", "academic"):
        raise HTTPException(status_code=422, detail="section 必须 easy/medium/hard/academic")
    svc = _get_service(request, int(user.id))
    rows = await asyncio.to_thread(svc.list_sets, section)
    return [SetSummary(**r) for r in rows]


# =============================================================
# POST /api/reading/practice/start
# =============================================================


@api_router.post("/start", response_model=StartSetResponse)
async def api_start(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    payload: StartSectionSetRequest,
) -> StartSetResponse:
    if payload.section not in ("easy", "medium", "hard", "academic"):
        raise HTTPException(status_code=422, detail="section 非法")
    if payload.set_id < 1:
        raise HTTPException(status_code=422, detail="set_id 必须 ≥ 1")
    svc = _get_service(request, int(user.id))
    out = await asyncio.to_thread(
        svc.start_set, payload.section, payload.set_id
    )
    if out is None:
        raise HTTPException(
            status_code=404,
            detail=f"Section {payload.section} 套题 #{payload.set_id} 不存在",
        )
    return StartSetResponse(
        section=out["section"],
        set_id=out["set_id"],
        section_label=out["section_label"],
        scenario=out["scenario"],
        questions=[QuestionForClient(**q) for q in out["questions"]],
    )


# =============================================================
# POST /api/reading/practice/random
# =============================================================


@api_router.post("/random", response_model=StartSetResponse)
async def api_random(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    payload: StartRandomRequest,
) -> StartSetResponse:
    svc = _get_service(request, int(user.id))
    out = await asyncio.to_thread(
        svc.start_random_set, payload.section
    )
    if out is None:
        raise HTTPException(status_code=404, detail="题库为空")
    return StartSetResponse(
        section=out["section"],
        set_id=out["set_id"],
        section_label=out["section_label"],
        scenario=out["scenario"],
        questions=[QuestionForClient(**q) for q in out["questions"]],
    )


# =============================================================
# GET /api/reading/practice/question/{qid}
# =============================================================


@api_router.get("/question/{qid}", response_model=QuestionForClient)
async def api_question(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    qid: int,
) -> QuestionForClient:
    if qid < 1:
        raise HTTPException(status_code=422, detail="qid 非法")
    svc = _get_service(request, int(user.id))
    q = await asyncio.to_thread(svc.get_question, int(qid))
    if q is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return QuestionForClient(**q)


# =============================================================
# POST /api/reading/practice/submit
# =============================================================


@api_router.post("/submit", response_model=SubmitAnswerResponse)
async def api_submit(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    payload: SubmitAnswerRequest,
) -> SubmitAnswerResponse:
    if not (payload.user_answer or "").strip():
        raise HTTPException(status_code=422, detail="答案不能为空")
    if payload.duration_sec < 0 or payload.duration_sec > 600:
        raise HTTPException(status_code=422, detail="duration_sec 非法")
    svc = _get_service(request, int(user.id))
    out = await asyncio.to_thread(
        svc.submit_answer,
        int(payload.question_id),
        str(payload.user_answer),
        float(payload.duration_sec),
    )
    if out is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return SubmitAnswerResponse(
        question_id=out["question_id"],
        is_correct=out["is_correct"],
        correct_answer=out["correct_answer"],
        explanation=out["explanation"],
        transcript=out["transcript"],
        question_type=out["question_type"],
        attempt_id=out["attempt_id"],
        next_question_id=out["next_question_id"],
    )


# =============================================================
# GET /api/reading/practice/history
# =============================================================


@api_router.get("/history", response_model=HistoryResponse)
async def api_history(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    section: Annotated[Optional[str], Query()] = None,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> HistoryResponse:
    svc = _get_service(request, int(user.id))
    items, total = await asyncio.to_thread(
        svc.list_history, page, size, section
    )
    history_items: list[HistoryItem] = []
    for it in items:
        history_items.append(HistoryItem(
            attempt_id=int(it["id"]),
            question_id=int(it["question_id"]),
            section=str(it.get("section") or ""),
            set_id=int(it.get("set_id") or 0),
            qid=int(it.get("qid") or 0),
            title=it.get("title") or "",
            user_answer=it.get("user_answer") or "",
            correct_answer=it.get("correct_answer") or "",
            is_correct=bool(it.get("is_correct")),
            duration_sec=float(it.get("duration_sec") or 0.0),
            created_at=it.get("created_at") or "",
        ))
    return HistoryResponse(
        total=total, page=page, size=size, items=history_items,
    )


# =============================================================
# GET /api/reading/practice/stats
# =============================================================


@api_router.get("/stats", response_model=UserStatsResponse)
async def api_stats(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> UserStatsResponse:
    svc = _get_service(request, int(user.id))
    raw = await asyncio.to_thread(svc.get_user_stats)
    by_section = {}
    for sec_key, s in (raw.get("by_section") or {}).items():
        by_section[sec_key] = SectionStat(
            attempts=int(s.get("attempts", 0)),
            correct=int(s.get("correct", 0)),
            accuracy=s.get("accuracy"),
        )
    return UserStatsResponse(
        total_attempts=int(raw.get("total_attempts", 0)),
        correct=int(raw.get("correct", 0)),
        accuracy=raw.get("accuracy"),
        by_section=by_section,
    )


__all__ = ["router", "api_router"]