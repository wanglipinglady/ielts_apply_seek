"""/plan 学习计划路由。

功能：
- GET /plan: 学习计划页面
- GET /api/plan/status: 获取计划状态
- POST /api/plan/update: 更新学习计划
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser


router = APIRouter(tags=["plan"])
api_router = APIRouter(prefix="/api/plan", tags=["plan-api"])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _get_container(request: Request):
    from ielts_buddy.web.main import app
    return getattr(app.state, "container", None)


# =============================================================
# 内存中的计划数据（生产环境应存数据库）
# =============================================================

_plans: dict[int, dict] = {}


def _get_or_create_plan(user_id: int) -> dict:
    if user_id not in _plans:
        _plans[user_id] = {
            "target_band": 7.0,
            "daily_new_words": 20,
            "daily_review": 50,
            "exam_date": None,
            "created_at": datetime.now().isoformat(),
        }
    return _plans[user_id]


# =============================================================
# 页面路由
# =============================================================


@router.get("/plan", response_class=HTMLResponse)
def page_plan(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """学习计划页面"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    plan = _get_or_create_plan(user.id)

    # 获取今日进度
    today_progress = _get_today_progress(user.id, request)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/plan.html",
        {
            "title": "学习计划",
            "phase": 4,
            "current_user": user,
            "plan": plan,
            "today_progress": today_progress,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


@api_router.get("/status")
def api_plan_status(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> dict:
    """获取计划状态"""
    plan = _get_or_create_plan(user.id)
    today_progress = _get_today_progress(user.id, request)

    # 计算距离考试天数
    days_to_exam = None
    if plan.get("exam_date"):
        try:
            exam_date = date.fromisoformat(plan["exam_date"])
            days_to_exam = (exam_date - date.today()).days
        except (ValueError, TypeError):
            days_to_exam = None

    return {
        "plan": plan,
        "today_progress": today_progress,
        "days_to_exam": days_to_exam,
    }


@api_router.post("/update")
def api_plan_update(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    target_band: Annotated[float, Form(ge=5.0, le=9.0)] = 7.0,
    daily_new_words: Annotated[int, Form(ge=5, le=100)] = 20,
    daily_review: Annotated[int, Form(ge=10, le=200)] = 50,
    exam_date: Annotated[Optional[str], Form()] = None,
) -> dict:
    """更新学习计划"""
    plan = _get_or_create_plan(user.id)
    plan.update({
        "target_band": target_band,
        "daily_new_words": daily_new_words,
        "daily_review": daily_review,
        "exam_date": exam_date if exam_date else None,
        "updated_at": datetime.now().isoformat(),
    })
    return {"success": True, "plan": plan}


def _get_today_progress(user_id: int, request: Request) -> dict:
    """获取今日进度"""
    container = _get_container(request)
    if container is None:
        return {"new_words": 0, "reviewed": 0, "due_count": 0}

    try:
        # 今日新学单词数
        new_words = container.learning.get_learned_words_today(user_id)
        new_count = len(new_words) if new_words else 0

        # 今日复习单词数
        today_str = date.today().isoformat()
        history = container.learning.get_history(user_id, days=1)
        reviewed_count = 0
        if history:
            reviewed_count = history[0].get("reviewed_words", 0)

        # 待复习数
        due_count = container.learning.get_due_count(user_id)

        return {
            "new_words": new_count,
            "reviewed": reviewed_count,
            "due_count": due_count,
        }
    except Exception:
        return {"new_words": 0, "reviewed": 0, "due_count": 0}


__all__ = ["router", "api_router"]
