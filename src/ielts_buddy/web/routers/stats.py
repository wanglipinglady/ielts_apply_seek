"""/api/stats/* 路由（Dashboard / Stats 页面数据源）。"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends

from ielts_buddy.web.auth.deps import get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_stats_service
from ielts_buddy.web.stats_schemas import (
    BandProgressItem,
    DailyTrendItem,
    LevelDistributionItem,
    StatsOverview,
    StatsSummary,
)
from ielts_buddy.web.stats_service import WebStatsService


api_router = APIRouter(prefix="/api/stats", tags=["stats"])


def _build_summary(svc: WebStatsService) -> StatsSummary:
    """从 WebStatsService 拉 5 个核心数字拼成 dashboard 卡片数据。

    注：WebStatsService 内部分别用直 SQL 跑，单元保证空表返回 0/空结构，
    所以这里不用 try/except。
    """
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
    dist = svc.level_distribution()  # dict[int, int]
    # 总是补齐 level 0-6（艾宾浩斯 7 级）
    return [
        LevelDistributionItem(level=lv, count=dist.get(lv, 0))
        for lv in range(7)
    ]


def _build_band_progress(svc: WebStatsService) -> list[BandProgressItem]:
    rows = svc.get_band_progress()  # list[tuple[band, total, mastered, ratio]]
    return [
        BandProgressItem(band=b, total=t, mastered=m, ratio=r)
        for b, t, m, r in rows
    ]


def _build_trend(svc: WebStatsService) -> list[DailyTrendItem]:
    rows = svc.get_daily_trend(days=7)  # list[tuple[date, studied, accuracy]]
    return [
        DailyTrendItem(date=d, studied=c) for d, c, _acc in rows
    ]


@api_router.get("/summary", response_model=StatsSummary)
def api_stats_summary(
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
    svc: Annotated[WebStatsService, Depends(get_stats_service)],
) -> StatsSummary:
    """Dashboard 用：5 张卡片的核心数字。"""
    if user is None:
        # 故意走强制认证返回 401，让前端知道需要登录
        from fastapi import HTTPException, status as _status
        raise HTTPException(
            status_code=_status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已失效",
        )
    svc._user_id = int(user.id)  # type: ignore[attr-defined]
    return _build_summary(svc)


@api_router.get("/overview", response_model=StatsOverview)
def api_stats_overview(
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
    svc: Annotated[WebStatsService, Depends(get_stats_service)],
) -> StatsOverview:
    """Stats 页面用：summary + level + band + trend 全量数据。"""
    if user is None:
        from fastapi import HTTPException, status as _status
        raise HTTPException(
            status_code=_status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已失效",
        )
    svc._user_id = int(user.id)  # type: ignore[attr-defined]
    return StatsOverview(
        summary=_build_summary(svc),
        level_distribution=_build_level_distribution(svc),
        band_progress=_build_band_progress(svc),
        trend=_build_trend(svc),
    )


__all__ = ["api_router"]
