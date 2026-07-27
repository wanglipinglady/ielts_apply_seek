"""HTML 页面路由：dashboard / stats / (阶段 3 的 learn / review)。"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ielts_buddy.web.auth.deps import get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_stats_service
from ielts_buddy.web.stats_schemas import (
    BandProgressItem,
    DailyTrendItem,
    LevelDistributionItem,
    StatsSummary,
)
from ielts_buddy.web.stats_service import WebStatsService


router = APIRouter(tags=["pages"])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _bind_user(svc: WebStatsService, user: WebUser) -> WebStatsService:
    """拿到可选 user 后，把 user_id 绑到 service 上。"""
    svc._user_id = int(user.id)  # type: ignore[attr-defined]
    return svc


@router.get("/dashboard", response_class=HTMLResponse)
def page_dashboard(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
    svc: Annotated[WebStatsService, Depends(get_stats_service)],
) -> HTMLResponse:
    """Dashboard 页：欢迎语 + 摘要卡片。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    svc = _bind_user(svc, user)
    summary = _build_summary(svc)
    return _get_templates(request).TemplateResponse(
        request,
        "pages/dashboard.html",
        {
            "title": "Dashboard",
            "phase": 2,
            "current_user": user,
            "summary": summary,
        },
    )


@router.get("/stats", response_class=HTMLResponse)
def page_stats(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
    svc: Annotated[WebStatsService, Depends(get_stats_service)],
) -> HTMLResponse:
    """Stats 页：summary + level + band + trend 全量。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    svc = _bind_user(svc, user)

    summary = _build_summary(svc)
    level_dist = _build_level_distribution(svc)
    band = _build_band_progress(svc)
    trend = _build_trend(svc)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/stats.html",
        {
            "title": "统计",
            "phase": 2,
            "current_user": user,
            "summary": summary,
            "level_dist": level_dist,
            "band": band,
            "trend": trend,
        },
    )


# =============================================================
# 内部：从 WebStatsService 拉数据 → schema 对象
# =============================================================


def _build_summary(svc: WebStatsService) -> StatsSummary:
    total = svc.total_stats()
    today = svc.today_stats()
    due = svc.due_count()
    cur, mx = svc.get_streak()
    return StatsSummary(
        today_new_words=today.get("new_words", 0),
        today_reviewed=today.get("reviewed_words", 0),
        total_words=total.get("total_words", 0),
        total_reviews=total.get("total_reviews", 0),
        total_correct=total.get("total_correct", 0),
        total_wrong=total.get("total_wrong", 0),
        accuracy=float(total.get("accuracy", 0.0)),
        mastered=total.get("mastered", 0),
        due_count=due,
        current_streak=cur,
        max_streak=mx,
    )


def _build_level_distribution(svc: WebStatsService) -> list[LevelDistributionItem]:
    dist = svc.level_distribution()
    return [
        LevelDistributionItem(level=lv, count=dist.get(lv, 0))
        for lv in range(7)
    ]


def _build_band_progress(svc: WebStatsService) -> list[BandProgressItem]:
    rows = svc.get_band_progress()
    return [
        BandProgressItem(band=b, total=t, mastered=m, ratio=r)
        for b, t, m, r in rows
    ]


def _build_trend(svc: WebStatsService) -> list[DailyTrendItem]:
    rows = svc.get_daily_trend(days=7)
    return [
        DailyTrendItem(date=d, studied=c) for d, c, _acc in rows
    ]


__all__ = ["router"]
