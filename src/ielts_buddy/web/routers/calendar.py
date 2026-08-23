"""/calendar 学习日历热力图路由（v3.6 新增）。

端点：
- GET  /calendar                  : 日历热力图页面
- GET  /api/calendar/data         : 返回 [{date, minutes, level}, ...] + streak 摘要
- GET  /api/calendar/today        : 今日学习分钟数（侧边栏快速展示）

数据源聚合：
  - focus_sessions.duration_sec (专注秒数 → 分钟)
  - learning_records.last_reviewed (复习次数 → 按 1min/次 折算)
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.calendar_service import CalendarService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["calendar"])
api_router = APIRouter(prefix="/api/calendar", tags=["calendar-api"])


# =============================================================
# Helpers
# =============================================================


def _get_container(request: Request):
    return getattr(request.app.state, "container", None)


def _get_templates(request: Request):
    return request.app.state.templates


def _get_calendar_service(
    request: Request, user_id: int
) -> CalendarService:
    """从 fallback container 拿到当前 backend 的连接 + user_id 构造 service。"""
    container = _get_container(request)
    if container is None:
        raise RuntimeError("业务容器未初始化")

    # v3：FallbackContainer 双 backend（online MySQL / offline SQLite）
    # - 有 MySQL 用 engine
    # - 没 MySQL（或 fallback_sqlite 模式）用 SQLite 离线 conn
    conn = None
    if hasattr(container, "online") and container.online is not None:
        try:
            conn = container.online._engine
        except AttributeError:
            conn = None
    if conn is None:
        try:
            conn = container.offline._conn
        except AttributeError:
            conn = None
    if conn is None:
        conn = getattr(container, "_conn", None) or getattr(container, "_engine", None)
    if conn is None:
        raise RuntimeError("业务容器既无 _conn 也无 _engine")

    return CalendarService(conn, user_id=user_id)


# =============================================================
# 页面路由
# =============================================================


@router.get("/calendar", response_class=HTMLResponse)
def page_calendar(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """学习日历热力图页面。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/calendar.html",
        {
            "title": "学习日历",
            "phase": 7,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


class CalendarDay(BaseModel):
    date: str
    minutes: int
    level: int


class CalendarResponse(BaseModel):
    months: int
    start_date: str
    end_date: str
    days: list[CalendarDay]
    today_minutes: int
    today_level: int
    streak_current: int
    streak_max: int


class TodaySummary(BaseModel):
    date: str
    minutes: int
    level: int


@api_router.get("/data", response_model=CalendarResponse)
def api_calendar_data(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    months: Annotated[int, Query(ge=1, le=12)] = 3,
) -> CalendarResponse:
    """返回最近 N 月的日历热力图数据 + streak 摘要。"""
    svc = _get_calendar_service(request, int(user.id))
    days = svc.get_calendar_data(months=months)
    today_summary = svc.get_today_summary()
    streak = svc.get_streak()

    return CalendarResponse(
        months=months,
        start_date=days[0]["date"] if days else "",
        end_date=days[-1]["date"] if days else "",
        days=[CalendarDay(**d) for d in days],
        today_minutes=today_summary["minutes"],
        today_level=today_summary["level"],
        streak_current=streak["current"],
        streak_max=streak["max"],
    )


@api_router.get("/today", response_model=TodaySummary)
def api_calendar_today(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> TodaySummary:
    """今日学习分钟数（侧边栏快速展示用）。"""
    svc = _get_calendar_service(request, int(user.id))
    s = svc.get_today_summary()
    return TodaySummary(
        date=s["date"],
        minutes=s["minutes"],
        level=s["level"],
    )


__all__ = ["router", "api_router"]