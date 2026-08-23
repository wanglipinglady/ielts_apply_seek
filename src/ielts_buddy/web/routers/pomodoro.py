"""/pomodoro 番茄钟路由（v3.6 新增）。

功能：
- GET  /pomodoro                  : 番茄钟页面
- POST /api/pomodoro/start        : 开始一次专注会话，返回 session_id
- POST /api/pomodoro/{id}/complete: 结束一次会话（写入实际时长 + 备注）
- GET  /api/pomodoro/history      : 个人历史（最近 N 条）
- GET  /api/pomodoro/today        : 今日累计（用于侧边栏角标 / 今日统计卡）

设计要点：
- start 与 complete 拆成两次请求：用户点「开始」→ 后端立刻落库（duration_sec=0）
- 防止用户关页面 / 断网导致数据丢失；中途放弃也能补回 start_session_id
- 完成后端校验 planned_sec (60-7200) / duration_sec (>= 0)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from ielts_buddy.core.models import FocusSession
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pomodoro"])
api_router = APIRouter(prefix="/api/pomodoro", tags=["pomodoro-api"])


VALID_ACTIVITIES = ("vocab", "writing", "exam", "typing", "reading", "other")
ACTIVITY_NAMES_CN = {
    "vocab": "背单词",
    "writing": "写作",
    "exam": "模考",
    "typing": "打字",
    "reading": "阅读",
    "other": "其它",
}


# =============================================================
# 辅助函数
# =============================================================


def _get_container(request: Request):
    return getattr(request.app.state, "container", None)


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _normalize_activity(activity: str) -> str:
    return activity if activity in VALID_ACTIVITIES else "other"


# =============================================================
# 页面路由
# =============================================================


@router.get("/pomodoro", response_class=HTMLResponse)
def page_pomodoro(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """番茄钟页面。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/pomodoro.html",
        {
            "title": "番茄钟",
            "phase": 7,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


class StartResponse(BaseModel):
    session_id: int
    planned_sec: int
    started_at: str


class FocusSessionItem(BaseModel):
    id: int
    activity: str
    activity_cn: str
    planned_sec: int
    duration_sec: int
    interrupted: bool
    note: Optional[str] = ""
    started_at: str
    ended_at: str


class TodaySummary(BaseModel):
    date: str
    total: int
    total_sec: int
    completed: int
    abandoned: int


@api_router.post("/start", response_model=StartResponse)
def api_pomodoro_start(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    planned_sec: Annotated[int, Form(ge=60, le=7200)] = 1500,
    activity: Annotated[str, Form()] = "other",
    note: Annotated[str, Form(max_length=500)] = "",
) -> StartResponse:
    """开始一次专注会话；立刻落库(duration_sec=0)。"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    activity_n = _normalize_activity(activity)
    session = FocusSession(
        user_id=int(user.id),
        activity=activity_n,
        planned_sec=planned_sec,
        note=note,
        started_at=datetime.now().isoformat(timespec="seconds"),
    )
    try:
        sid = container.focus_sessions.start_session(int(user.id), session)
    except Exception as e:
        logger.exception(f"[pomodoro] start_session failed: {e}")
        raise HTTPException(status_code=500, detail=f"开始失败: {e}")

    return StartResponse(
        session_id=sid,
        planned_sec=planned_sec,
        started_at=session.started_at or "",
    )


@api_router.post("/{session_id}/complete")
def api_pomodoro_complete(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[int, Path(ge=1)],
    duration_sec: Annotated[int, Form(ge=0, le=7200)],
    interrupted: Annotated[bool, Form()] = False,
    note: Annotated[str, Form(max_length=500)] = "",
) -> dict[str, Any]:
    """结束一次专注会话；写入实际时长 + 备注 + 中途放弃标记。"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        ok = container.focus_sessions.complete_session(
            int(user.id),
            session_id,
            duration_sec=duration_sec,
            interrupted=interrupted,
            note=note,
        )
    except Exception as e:
        logger.exception(f"[pomodoro] complete_session failed: {e}")
        raise HTTPException(status_code=500, detail=f"结束失败: {e}")

    if not ok:
        raise HTTPException(status_code=404, detail="找不到该会话（可能已被删除）")

    return {
        "success": True,
        "session_id": session_id,
        "duration_sec": duration_sec,
        "interrupted": interrupted,
    }


@api_router.get("/history", response_model=list[FocusSessionItem])
def api_pomodoro_history(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[FocusSessionItem]:
    """个人最近 N 条专注记录。"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    sessions = container.focus_sessions.get_history(int(user.id), limit)
    items: list[FocusSessionItem] = []
    for s in sessions:
        items.append(FocusSessionItem(
            id=int(getattr(s, "id", 0) or 0),
            activity=s.activity,
            activity_cn=ACTIVITY_NAMES_CN.get(s.activity, s.activity),
            planned_sec=s.planned_sec,
            duration_sec=s.duration_sec,
            interrupted=s.interrupted,
            note=s.note or "",
            started_at=s.started_at or "",
            ended_at=s.ended_at or "",
        ))
    return items


@api_router.get("/today", response_model=TodaySummary)
def api_pomodoro_today(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> TodaySummary:
    """今日累计。"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    summary = container.focus_sessions.get_today_summary(int(user.id))
    return TodaySummary(
        date=summary.get("date", ""),
        total=int(summary.get("total", 0)),
        total_sec=int(summary.get("total_sec", 0)),
        completed=int(summary.get("completed", 0)),
        abandoned=int(summary.get("abandoned", 0)),
    )


__all__ = ["router", "api_router"]