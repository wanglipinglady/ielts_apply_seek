"""/resources 备考资源广场路由（v3.8 P3.1 新增）。

PRD: docs/web-mvp/plans/phase-10-reading-and-resources.md §5.6-5.7

端点:
- GET  /resources                       : 资源广场主页
- GET  /api/resources/list              : 列表(多条件过滤 + 排序 + 分页)
- GET  /api/resources/{id}              : 单条详情
- GET  /api/resources/featured          : 顶置资源(4 个 skill 各 1 条)
- GET  /api/resources/recommendation    : 今日推荐(Dashboard 用)
- GET  /api/resources/by-up             : 按 UP 主查
- GET  /api/resources/ups               : 所有 UP 主 + 资源数
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ielts_buddy.services.prep_resource_service import PrepResourceService
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["prep-resources"])
api_router = APIRouter(prefix="/api/resources", tags=["prep-resources-api"])


# =============================================================
# Pydantic models
# =============================================================


class ResourceItem(BaseModel):
    id: int
    title: str
    bv_id: str
    url: str
    author_name: str
    author_uid: Optional[int] = None
    uploader_name: Optional[str] = None
    skill: str
    video_type: str
    level: str
    method_summary: str
    source_status: str
    publish_date: Optional[str] = None
    duration_sec: int = 0
    outdated_risk: str = "low"
    format_compatible: str = "computer"
    computer_delivery_only: bool = True
    is_featured: bool = False
    recommend_score: float = 0.0
    sort_order: int = 100
    related_action_url: Optional[str] = None
    related_action_label: Optional[str] = None


class ListResponse(BaseModel):
    total: int
    items: list[ResourceItem]


class FeaturedResponse(BaseModel):
    listening: Optional[ResourceItem] = None
    reading: Optional[ResourceItem] = None
    speaking: Optional[ResourceItem] = None
    writing: Optional[ResourceItem] = None


class UpItem(BaseModel):
    author_name: str
    count: int


# =============================================================
# Helpers
# =============================================================


def _get_service(request: Request) -> PrepResourceService:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="业务容器未初始化")
    return PrepResourceService(container=container)


def _row_to_item(row: dict) -> ResourceItem:
    """DB row → Pydantic model(统一字段过滤)。"""
    # publish_date:MySQL DATE 列返 datetime.date,SQLite TEXT 返 str,
    # 统一成 "YYYY-MM-DD" 字符串,避免 Pydantic 校验失败。
    raw_date = row.get("publish_date")
    publish_date_str: Optional[str] = None
    if raw_date is not None and raw_date != "":
        if hasattr(raw_date, "isoformat"):
            publish_date_str = raw_date.isoformat()
        else:
            publish_date_str = str(raw_date)
    return ResourceItem(
        id=int(row["id"]),
        title=row.get("title") or "",
        bv_id=row.get("bv_id") or "",
        url=row.get("url") or "",
        author_name=row.get("author_name") or "",
        author_uid=int(row["author_uid"]) if row.get("author_uid") else None,
        uploader_name=row.get("uploader_name") or None,
        skill=row.get("skill") or "general",
        video_type=row.get("video_type") or "methodology",
        level=row.get("level") or "5-6",
        method_summary=row.get("method_summary") or "",
        source_status=row.get("source_status") or "verified_repost",
        publish_date=publish_date_str,
        duration_sec=int(row.get("duration_sec") or 0),
        outdated_risk=row.get("outdated_risk") or "low",
        format_compatible=row.get("format_compatible") or "computer",
        computer_delivery_only=bool(row.get("computer_delivery_only", True)),
        is_featured=bool(row.get("is_featured", False)),
        recommend_score=float(row.get("recommend_score") or 0.0),
        sort_order=int(row.get("sort_order") or 100),
        related_action_url=row.get("related_action_url") or None,
        related_action_label=row.get("related_action_label") or None,
    )


# =============================================================
# 页面: GET /resources
# =============================================================


@router.get("/resources", response_class=HTMLResponse)
def page_resources(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """资源广场主页。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/resources.html",
        {
            "title": "备考资源广场",
            "phase": 9,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# GET /api/resources/list
# =============================================================


@api_router.get("/list", response_model=ListResponse)
async def api_list_resources(
    request: Request,
    skill: Annotated[Optional[str], Query()] = None,
    level: Annotated[Optional[str], Query()] = None,
    source_status: Annotated[Optional[str], Query()] = None,
    is_featured: Annotated[Optional[bool], Query()] = None,
    sort_by: Annotated[str, Query()] = "recommend_score",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> ListResponse:
    svc = _get_service(request)
    rows = svc.list_resources(
        skill=skill, level=level, source_status=source_status,
        is_featured=is_featured, sort_by=sort_by,
        limit=limit, offset=offset,
    )
    total = svc.count_resources(
        skill=skill, level=level, source_status=source_status,
        is_featured=is_featured,
    )
    return ListResponse(
        total=total,
        items=[_row_to_item(r) for r in rows],
    )


# =============================================================
# GET /api/resources/featured
# (必须在 /{id} 之前声明,否则会被 {id} 路径吃掉)
# =============================================================


@api_router.get("/featured", response_model=FeaturedResponse)
async def api_featured(
    request: Request,
) -> FeaturedResponse:
    """4 个 skill 各取 1 条顶置资源。"""
    svc = _get_service(request)
    out = FeaturedResponse()
    for skill_name in ("listening", "reading", "speaking", "writing"):
        rows = svc.list_featured(skill=skill_name, limit=1)
        if rows:
            setattr(out, skill_name, _row_to_item(rows[0]))
    return out


# =============================================================
# GET /api/resources/recommendation
# =============================================================


@api_router.get("/recommendation", response_model=Optional[ResourceItem])
async def api_recommendation(
    request: Request,
    user_level: Annotated[Optional[str], Query()] = None,
    skill: Annotated[Optional[str], Query()] = None,
) -> Optional[ResourceItem]:
    """今日推荐(供 Dashboard 调)。"""
    svc = _get_service(request)
    row = svc.get_today_recommendation(
        user_level=user_level or "5-6",
        skill=skill,
    )
    return _row_to_item(row) if row else None


# =============================================================
# GET /api/resources/by-up
# =============================================================


@api_router.get("/by-up", response_model=list[ResourceItem])
async def api_by_up(
    request: Request,
    author_name: Annotated[str, Query(min_length=1, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[ResourceItem]:
    svc = _get_service(request)
    rows = svc.list_by_up(author_name=author_name, limit=limit)
    return [_row_to_item(r) for r in rows]


# =============================================================
# GET /api/resources/ups
# =============================================================


@api_router.get("/ups", response_model=list[UpItem])
async def api_ups(
    request: Request,
) -> list[UpItem]:
    """列出所有 UP 主 + 资源数。"""
    svc = _get_service(request)
    rows = svc.list_distinct_ups()
    return [UpItem(**r) for r in rows]


# =============================================================
# GET /api/resources/{id}
# (必须在所有字面量路径之后,否则会吞掉 /featured 等)
# =============================================================


@api_router.get("/{id}", response_model=ResourceItem)
async def api_get_resource(
    request: Request,
    id: int,
) -> ResourceItem:
    svc = _get_service(request)
    row = svc.get_resource(id)
    if row is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return _row_to_item(row)


__all__ = ["router", "api_router"]