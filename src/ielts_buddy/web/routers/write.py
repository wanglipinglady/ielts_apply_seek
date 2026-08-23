"""/write 写作辅助路由（A 档：把 WritingService 暴露到 web）。

端点：
- GET  /write                        : 写作辅助页面（4 个 tab：话题 / 句型 / 同义词 / 词汇）
- GET  /api/write/categories         : 所有话题分类（education / environment / ...）
- GET  /api/write/topics             : 话题列表，支持 ?category=xxx 筛选
- GET  /api/write/topics/{topic_id}  : 单个话题详情（按索引，从 1 开始）
- GET  /api/write/template-types     : 所有模板类型（introduction / body / conclusion / transition）
- GET  /api/write/templates          : 句型模板列表，支持 ?type=xxx 筛选
- GET  /api/write/synonyms           : 同义替换，支持 ?word=xxx 模糊匹配
- GET  /api/write/vocab              : 话题高分词汇，支持 ?topic=xxx 模糊匹配

数据源：WritingService（只读、零 LLM、零副作用，纯 importlib.resources 读 JSON）。
所有 service 调用都用 ``await asyncio.to_thread(svc.xxx)`` 包一层：
``importlib.resources.files`` 是同步文件读盘，必须丢到线程池里跑。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ielts_buddy.services.writing_service import WritingService
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["write"])
api_router = APIRouter(prefix="/api/write", tags=["write-api"])


# =============================================================
# Helpers
# =============================================================


def _get_templates(request: Request):
    return request.app.state.templates


def _new_service() -> WritingService:
    """每个请求 new 一个 service；service 是无状态壳，构造便宜。"""
    return WritingService()


# =============================================================
# 页面路由
# =============================================================


@router.get("/write", response_class=HTMLResponse)
def page_write(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """写作辅助页面（4 个 tab）。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/write.html",
        {
            "title": "写作辅助",
            "phase": 7,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


class TopicItem(BaseModel):
    topic: str
    question: str
    category: str
    keywords: list[str]
    band7_vocab: list[str]


class TemplateItem(BaseModel):
    type: str
    template: str
    translation: str
    example: str


class SynonymItem(BaseModel):
    common: str
    synonyms: list[str]
    context: str


class VocabResponse(BaseModel):
    topic: str
    question: str
    category: str
    keywords: list[str]
    band7_vocab: list[str]


@api_router.get("/categories", response_model=list[str])
async def api_categories(
    user: Annotated[WebUser, Depends(get_current_user)],
) -> list[str]:
    """所有话题分类（education / environment / health / ...）。"""
    svc = _new_service()
    return await asyncio.to_thread(svc.get_categories)


@api_router.get("/topics", response_model=list[TopicItem])
async def api_topics(
    user: Annotated[WebUser, Depends(get_current_user)],
    category: Annotated[Optional[str], Query(max_length=64)] = None,
) -> list[TopicItem]:
    """话题列表，可按 category 筛选。"""
    svc = _new_service()
    rows = await asyncio.to_thread(svc.get_topics, category)
    return [TopicItem(**r) for r in rows]


@api_router.get("/topics/{topic_id}", response_model=Optional[TopicItem])
async def api_topic_detail(
    user: Annotated[WebUser, Depends(get_current_user)],
    topic_id: Annotated[int, Path(ge=1)],
) -> Optional[TopicItem]:
    """单个话题详情（按索引，从 1 开始）。"""
    svc = _new_service()
    row = await asyncio.to_thread(svc.get_topic_detail, topic_id)
    if row is None:
        return None
    return TopicItem(**row)


@api_router.get("/template-types", response_model=list[str])
async def api_template_types(
    user: Annotated[WebUser, Depends(get_current_user)],
) -> list[str]:
    """所有句型模板类型（introduction / body / conclusion / transition）。"""
    svc = _new_service()
    return await asyncio.to_thread(svc.get_template_types)


@api_router.get("/templates", response_model=list[TemplateItem])
async def api_templates(
    user: Annotated[WebUser, Depends(get_current_user)],
    type: Annotated[Optional[str], Query(max_length=32, alias="type")] = None,
) -> list[TemplateItem]:
    """句型模板列表，可按 type 筛选。"""
    svc = _new_service()
    rows = await asyncio.to_thread(svc.get_templates, type)
    return [TemplateItem(**r) for r in rows]


@api_router.get("/synonyms", response_model=list[SynonymItem])
async def api_synonyms(
    user: Annotated[WebUser, Depends(get_current_user)],
    word: Annotated[Optional[str], Query(max_length=64)] = None,
) -> list[SynonymItem]:
    """同义替换列表，支持按常用词模糊匹配。"""
    svc = _new_service()
    rows = await asyncio.to_thread(svc.get_synonyms, word)
    return [SynonymItem(**r) for r in rows]


@api_router.get("/vocab", response_model=Optional[VocabResponse])
async def api_vocab(
    user: Annotated[WebUser, Depends(get_current_user)],
    topic: Annotated[str, Query(min_length=1, max_length=128)],
) -> Optional[VocabResponse]:
    """话题对应的高分词汇（keywords + band7_vocab），按 topic 模糊匹配。"""
    svc = _new_service()
    row = await asyncio.to_thread(svc.get_writing_vocab, topic)
    if row is None:
        return None
    return VocabResponse(**row)


__all__ = ["router", "api_router"]