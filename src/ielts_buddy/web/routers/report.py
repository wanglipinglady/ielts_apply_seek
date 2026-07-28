"""/report 报告生成路由。

功能：
- GET /report: 报告中心页面
- GET /api/report/weekly: 获取周报
- GET /api/report/monthly: 获取月报
- POST /api/report/generate: 生成新报告
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser


router = APIRouter(tags=["report"])
api_router = APIRouter(prefix="/api/report", tags=["report-api"])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _get_container(request: Request):
    from ielts_buddy.web.main import app
    return getattr(app.state, "container", None)


# =============================================================
# 页面路由
# =============================================================


@router.get("/report", response_class=HTMLResponse)
def page_report(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """报告中心页面"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    # 生成近期报告列表
    reports = _generate_report_list(user.id, request)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/report.html",
        {
            "title": "报告中心",
            "phase": 4,
            "current_user": user,
            "reports": reports,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


@api_router.get("/weekly")
def api_weekly_report(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    start_date: Optional[str] = None,
) -> dict:
    """获取周报"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    # 确定起始日期
    if start_date:
        try:
            start = date.fromisoformat(start_date)
        except ValueError:
            start = date.today() - timedelta(days=6)
    else:
        start = date.today() - timedelta(days=6)

    end = start + timedelta(days=6)

    try:
        report = _build_weekly_report(user.id, container, start, end)
        return {"success": True, "report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/monthly")
def api_monthly_report(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict:
    """获取月报"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    today = date.today()
    year = year or today.year
    month = month or today.month

    try:
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)

        report = _build_monthly_report(user.id, container, start, end)
        return {"success": True, "report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/generate")
def api_generate_report(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    report_type: Annotated[str, Form()] = "weekly",
) -> dict:
    """生成新报告"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    today = date.today()

    if report_type == "weekly":
        start = today - timedelta(days=6)
        end = today
        report = _build_weekly_report(user.id, container, start, end)
    else:
        start = date(today.year, today.month, 1)
        if today.month == 12:
            end = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(today.year, today.month + 1, 1) - timedelta(days=1)
        report = _build_monthly_report(user.id, container, start, end)

    return {"success": True, "report": report}


# =============================================================
# 内部函数
# =============================================================


def _generate_report_list(user_id: int, request: Request) -> list[dict]:
    """生成报告列表"""
    reports = []

    # 最近一周
    today = date.today()
    for i in range(4):
        week_start = today - timedelta(days=6 + i * 7)
        week_end = week_start + timedelta(days=6)
        reports.append({
            "type": "weekly",
            "title": f"周报 W{(today.isocalendar()[1] - i)}",
            "period": f"{week_start.strftime('%m-%d')} ~ {week_end.strftime('%m-%d')}",
            "generated": week_end.isoformat(),
            "status": "generated" if i > 0 else "current",
        })

    # 最近一月
    for i in range(3):
        month = today.month - i
        year = today.year
        if month <= 0:
            month += 12
            year -= 1
        reports.append({
            "type": "monthly",
            "title": f"月报 {year}-{month:02d}",
            "period": f"{year}-{month:02d}",
            "generated": f"{year}-{month:02d}-01",
            "status": "generated",
        })

    return reports


def _build_weekly_report(
    user_id: int,
    container,
    start: date,
    end: date,
) -> dict:
    """构建周报数据"""
    # 获取本周学习历史
    history = container.learning.get_history(user_id, days=7)
    start_str = start.isoformat()

    # 过滤本周数据
    week_data = [h for h in history if h.get("date", "") >= start_str]
    if not week_data:
        week_data = history[:7] if history else []

    # 计算统计数据
    total_new = sum(h.get("new_words", 0) for h in week_data)
    total_reviewed = sum(h.get("reviewed_words", 0) for h in week_data)
    total = total_new + total_reviewed

    # 获取总体统计
    total_words = container.learning.get_learned_count(user_id)
    due_count = container.learning.get_due_count(user_id)

    return {
        "type": "weekly",
        "period": f"{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}",
        "summary": {
            "total_words_learned": total_new,
            "total_reviews": total_reviewed,
            "total_words_mastered": total_words,
            "due_count": due_count,
        },
        "daily_data": week_data,
        "generated_at": datetime.now().isoformat(),
    }


def _build_monthly_report(
    user_id: int,
    container,
    start: date,
    end: date,
) -> dict:
    """构建月报数据"""
    # 获取本月学习历史
    days = (end - start).days + 1
    history = container.learning.get_history(user_id, days=days)
    start_str = start.isoformat()

    # 过滤本月数据
    month_data = [h for h in history if h.get("date", "") >= start_str]
    if not month_data:
        month_data = history[:days] if history else []

    # 计算统计数据
    total_new = sum(h.get("new_words", 0) for h in month_data)
    total_reviewed = sum(h.get("reviewed_words", 0) for h in month_data)
    total = total_new + total_reviewed

    # 获取总体统计
    total_words = container.learning.get_learned_count(user_id)
    due_count = container.learning.get_due_count(user_id)

    return {
        "type": "monthly",
        "period": f"{start.strftime('%Y-%m')} ({start.strftime('%m-%d')} ~ {end.strftime('%m-%d')})",
        "summary": {
            "total_words_learned": total_new,
            "total_reviews": total_reviewed,
            "total_words_mastered": total_words,
            "due_count": due_count,
            "avg_daily": round(total_new / days, 1) if days > 0 else 0,
        },
        "daily_data": month_data,
        "generated_at": datetime.now().isoformat(),
    }


__all__ = ["router", "api_router"]
