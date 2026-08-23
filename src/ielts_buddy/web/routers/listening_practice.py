"""/listen/practice 真·听力题库路由（v3.7 P2 新增）。

PRD: docs/web-mvp/plans/phase-9-listening-practice.md §5.4

端点:
- GET  /listen/practice                       : 听力练习主页
- GET  /api/listening/practice/sections       : 4 个 Section 概览
- GET  /api/listening/practice/section/{n}    : 列出该 Section 下所有套题
- POST /api/listening/practice/start          : 抽一套题(可指定 section+set,或随机)
- GET  /api/listening/practice/question/{qid} : 单题详情(触发后台 TTS)
- POST /api/listening/practice/submit         : 提交答案
- GET  /api/listening/practice/history        : 我的历史
- GET  /api/listening/practice/stats          : 我的统计
- GET  /api/listening/practice/audio/{qid}    : 流式下载 mp3
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from ielts_buddy.services.listening_practice_service import (
    ListeningPracticeService,
    SECTION_LABELS,
    QUESTION_TYPE_LABELS,
)
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["listening-practice"])
api_router = APIRouter(
    prefix="/api/listening/practice", tags=["listening-practice-api"]
)


# =============================================================
# Helpers
# =============================================================


def _get_container(request: Request) -> Any:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="业务容器未初始化")
    return container


def _get_service(request: Request, user_id: int) -> ListeningPracticeService:
    container = _get_container(request)
    return ListeningPracticeService(container=container, user_id=user_id)


# =============================================================
# Pydantic models
# =============================================================


class SectionSummary(BaseModel):
    section: int
    name: str
    total_sets: int
    total_questions: int
    user_attempts: int
    user_accuracy: Optional[float] = None


class SectionsResponse(BaseModel):
    sections: list[SectionSummary]


class SetSummary(BaseModel):
    set_id: int
    section: int
    scenario: str
    question_count: int
    first_stem: str


class QuestionForClient(BaseModel):
    id: int
    section: int
    set_id: int
    qid: int
    scenario: str
    question_type: str
    question_type_label: str
    stem: str
    options: Optional[list[str]] = None
    audio_url: Optional[str] = None
    audio_generated_at: Optional[str] = None


class StartSetResponse(BaseModel):
    section: int
    set_id: int
    section_label: str
    scenario: str
    questions: list[QuestionForClient]


class StartRandomResponse(BaseModel):
    section: int
    set_id: int
    section_label: str
    scenario: str
    questions: list[QuestionForClient]


class StartRandomRequest(BaseModel):
    section: Optional[int] = None


class StartSectionSetRequest(BaseModel):
    section: int
    set_id: int


class SubmitAnswerRequest(BaseModel):
    question_id: int
    user_answer: str
    duration_sec: float = 0.0
    played_count: int = 1


class SubmitAnswerResponse(BaseModel):
    question_id: int
    is_correct: bool
    correct_answer: str
    explanation: str
    transcript: str
    question_type: str
    played_count: int
    attempt_id: int
    next_question_id: Optional[int] = None


class HistoryItem(BaseModel):
    attempt_id: int
    question_id: int
    section: int
    set_id: int
    qid: int
    scenario: str
    stem: str
    user_answer: str
    correct_answer: str
    is_correct: bool
    duration_sec: float
    played_count: int
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
    by_section: dict[int, SectionStat]


# =============================================================
# 页面: GET /listen/practice
# =============================================================


@router.get("/listen/practice", response_class=HTMLResponse)
def page_listening_practice(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """真·听力题库主页。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/listen_practice.html",
        {
            "title": "真·听力题库",
            "phase": 9,
            "current_user": user,
            "request": request,
            "section_labels": SECTION_LABELS,
            "question_type_labels": QUESTION_TYPE_LABELS,
        },
    )


# =============================================================
# GET /api/listening/practice/sections
# =============================================================


@api_router.get("/sections", response_model=SectionsResponse)
async def api_sections(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> SectionsResponse:
    """4 个 Section 概览。"""
    svc = _get_service(request, int(user.id))
    data = await asyncio.to_thread(svc.list_sections)
    return SectionsResponse(
        sections=[SectionSummary(**d) for d in data]
    )


# =============================================================
# GET /api/listening/practice/section/{section}
# =============================================================


@api_router.get("/section/{section}", response_model=list[SetSummary])
async def api_sets_by_section(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    section: int,
) -> list[SetSummary]:
    """列出某 Section 下所有套题。"""
    if section < 1 or section > 4:
        raise HTTPException(status_code=422, detail="section 必须 1-4")
    svc = _get_service(request, int(user.id))
    rows = await asyncio.to_thread(svc.list_sets, int(section))
    return [SetSummary(**r) for r in rows]


# =============================================================
# POST /api/listening/practice/start
# =============================================================


@api_router.post("/start", response_model=StartSetResponse)
async def api_start(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    payload: StartSectionSetRequest,
) -> StartSetResponse:
    """抽指定 (section, set_id) 的套题。"""
    if payload.section not in (1, 2, 3, 4):
        raise HTTPException(status_code=422, detail="section 必须 1-4")
    if payload.set_id < 1:
        raise HTTPException(status_code=422, detail="set_id 必须 ≥ 1")
    svc = _get_service(request, int(user.id))
    out = await asyncio.to_thread(
        svc.start_set, int(payload.section), int(payload.set_id)
    )
    if out is None:
        raise HTTPException(
            status_code=404,
            detail=f"Section {payload.section} 套题 #{payload.set_id} 不存在",
        )
    return StartSetResponse(
        section=out.section,
        set_id=out.set_id,
        section_label=SECTION_LABELS.get(out.section, f"Section {out.section}"),
        scenario=out.scenario,
        questions=[QuestionForClient(**q) for q in out.questions],
    )


# =============================================================
# POST /api/listening/practice/random
# =============================================================


@api_router.post("/random", response_model=StartRandomResponse)
async def api_random(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    payload: StartRandomRequest,
) -> StartRandomResponse:
    """随机抽一套题(可指定 section)。"""
    svc = _get_service(request, int(user.id))
    out = await asyncio.to_thread(
        svc.start_random_set,
        int(payload.section) if payload.section is not None else None,
    )
    if out is None:
        raise HTTPException(status_code=404, detail="题库为空")
    return StartRandomResponse(
        section=out.section,
        set_id=out.set_id,
        section_label=SECTION_LABELS.get(out.section, f"Section {out.section}"),
        scenario=out.scenario,
        questions=[QuestionForClient(**q) for q in out.questions],
    )


# =============================================================
# GET /api/listening/practice/question/{qid}
# =============================================================


@api_router.get("/question/{qid}", response_model=QuestionForClient)
async def api_question(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    qid: int,
) -> QuestionForClient:
    """单题详情。后台触发 TTS(若有 transcript 且无 audio)。"""
    svc = _get_service(request, int(user.id))
    q = await asyncio.to_thread(svc.get_question, int(qid))
    if q is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return QuestionForClient(**q)


# =============================================================
# POST /api/listening/practice/submit
# =============================================================


@api_router.post("/submit", response_model=SubmitAnswerResponse)
async def api_submit(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    payload: SubmitAnswerRequest,
) -> SubmitAnswerResponse:
    """提交单题答案。"""
    if not (payload.user_answer or "").strip():
        raise HTTPException(status_code=422, detail="答案不能为空")
    if payload.duration_sec < 0 or payload.duration_sec > 600:
        raise HTTPException(status_code=422, detail="duration_sec 非法")
    if payload.played_count < 1 or payload.played_count > 20:
        raise HTTPException(status_code=422, detail="played_count 非法")
    svc = _get_service(request, int(user.id))
    out = await asyncio.to_thread(
        svc.submit_answer,
        int(payload.question_id),
        str(payload.user_answer),
        float(payload.duration_sec),
        int(payload.played_count),
    )
    if out is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return SubmitAnswerResponse(
        question_id=out.question_id,
        is_correct=out.is_correct,
        correct_answer=out.correct_answer,
        explanation=out.explanation,
        transcript=out.transcript,
        question_type=out.question_type,
        played_count=out.played_count,
        attempt_id=out.attempt_id,
        next_question_id=out.next_question_id,
    )


# =============================================================
# GET /api/listening/practice/history
# =============================================================


@api_router.get("/history", response_model=HistoryResponse)
async def api_history(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    section: Annotated[Optional[int], Query(ge=1, le=4)] = None,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> HistoryResponse:
    svc = _get_service(request, int(user.id))
    items, total = await asyncio.to_thread(
        svc.list_history, page, size, int(section) if section else None
    )
    history_items: list[HistoryItem] = []
    for it in items:
        history_items.append(HistoryItem(
            attempt_id=int(it["id"]),
            question_id=int(it["question_id"]),
            section=int(it.get("section") or 0),
            set_id=int(it.get("set_id") or 0),
            qid=int(it.get("qid") or 0),
            scenario=it.get("scenario") or "",
            stem=it.get("stem") or "",
            user_answer=it.get("user_answer") or "",
            correct_answer=it.get("correct_answer") or "",
            is_correct=bool(it.get("is_correct")),
            duration_sec=float(it.get("duration_sec") or 0.0),
            played_count=int(it.get("played_count") or 1),
            created_at=it.get("created_at") or "",
        ))
    return HistoryResponse(
        total=total, page=page, size=size, items=history_items,
    )


# =============================================================
# GET /api/listening/practice/stats
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
        try:
            sec_int = int(sec_key)
        except (TypeError, ValueError):
            continue
        by_section[sec_int] = SectionStat(
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


# =============================================================
# GET /api/listening/practice/audio/{qid}
# =============================================================


@api_router.get("/audio/{qid}")
async def api_audio(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    qid: int,
) -> StreamingResponse:
    """流式返回 mp3(任意登录用户可听;题库是跨用户共享资源)。"""
    if qid < 1:
        raise HTTPException(status_code=422, detail="qid 非法")
    svc = _get_service(request, int(user.id))
    audio_path = await asyncio.to_thread(svc.get_audio_path, int(qid))
    if audio_path is None or not audio_path.exists():
        raise HTTPException(status_code=404, detail="音频不存在或尚未生成")
    mime = "audio/mpeg"

    def iterfile():
        with audio_path.open("rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(iterfile(), media_type=mime)


__all__ = ["router", "api_router"]