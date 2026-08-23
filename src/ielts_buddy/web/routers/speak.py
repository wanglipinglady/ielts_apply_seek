"""/speak 口语练习 Web 化路由（v3.7 新增）。

将 CLI 端 ``ib speak`` 的三个子命令搬到 Web：

- ``GET  /speak``           口语练习主页（话题列表 / 抽题 / 词汇 三 tab）
- ``GET  /api/speak/topics``  话题列表（可按 Part 筛选）
- ``GET  /api/speak/parts``   所有可用 Part 编号
- ``GET  /api/speak/random``  按 Part 随机抽题（含 sample_answer / tips）
- ``GET  /api/speak/vocab``   按 topic 名模糊匹配，返回词汇卡
- ``GET  /api/speak/detail``  按 topic_id 取单条详情
- ``GET  /api/speak/count``   话题数量（可按 Part）

设计要点：
- 复用 CLI 端的 ``SpeakingService``（纯只读、无 LLM、无音频、无持久化）。
- Service 调用走 ``asyncio.to_thread`` 避免阻塞 FastAPI 事件循环。
- 本次不做录音 / STT / 评分 / 陪练对话（属于 P1 大工程）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ielts_buddy.services.speaking_service import SpeakingService
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["speak"])
api_router = APIRouter(prefix="/api/speak", tags=["speak-api"])


# =============================================================
# Helpers
# =============================================================


def _get_templates(request: Request) -> Any:
    return request.app.state.templates


def _get_service() -> SpeakingService:
    """构造 SpeakingService 实例。

    Service 是无状态的纯只读壳，每次请求构造一个轻量实例足够。
    内部 ``_topics`` 走模块级延迟加载，多次构造不会重复 IO。
    """
    return SpeakingService()


# =============================================================
# Response Models
# =============================================================


class TopicItem(BaseModel):
    """单个话题。"""

    topic_id: int          # 1-based 全局索引
    part: int
    topic: str
    questions: list[str]
    vocab: list[str]
    sample_answer: str
    tips: str


class RandomTopicResponse(BaseModel):
    """随机抽题响应（含 sample_answer / tips 用于前端范文渲染）。"""

    topic_id: int
    part: int
    part_label: str
    topic: str
    questions: list[str]
    vocab: list[str]
    sample_answer: str
    tips: str


class VocabCard(BaseModel):
    """话题词汇卡。"""

    part: int
    part_label: str
    topic: str
    vocab: list[str]
    questions: list[str]


class CountResponse(BaseModel):
    total: int


# =============================================================
# 页面路由
# =============================================================


_PART_LABELS = {
    1: "Part 1 (日常话题)",
    2: "Part 2 (个人陈述)",
    3: "Part 3 (深入讨论)",
}


@router.get("/speak", response_class=HTMLResponse)
def page_speak(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """口语练习主页：话题列表 / 抽题 / 词汇 三 tab。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/speak.html",
        {
            "title": "口语练习",
            "phase": 7,
            "current_user": user,
            "request": request,
            "part_labels": _PART_LABELS,
        },
    )


# =============================================================
# API 路由
# =============================================================


def _build_topic_items(topics: list[dict]) -> list[dict]:
    """给话题列表添加 1-based 全局 topic_id。"""
    out: list[dict] = []
    for idx, t in enumerate(topics, start=1):
        out.append({
            "topic_id": idx,
            "part": t["part"],
            "topic": t["topic"],
            "questions": t["questions"],
            "vocab": t["vocab"],
            "sample_answer": t["sample_answer"],
            "tips": t["tips"],
        })
    return out


@api_router.get("/topics", response_model=list[TopicItem])
async def api_topics(
    user: Annotated[WebUser, Depends(get_current_user)],
    part: Annotated[Optional[int], Query(ge=1, le=3)] = None,
) -> list[dict]:
    """话题列表（可按 Part 筛选）。

    ``part=None`` 时返回全部话题；``part=1/2/3`` 只返回该 Part。
    """
    svc = _get_service()
    topics = await asyncio.to_thread(svc.get_topics, part)
    return _build_topic_items(topics)


@api_router.get("/parts", response_model=list[int])
async def api_parts(
    user: Annotated[WebUser, Depends(get_current_user)],
) -> list[int]:
    """返回所有可用的 Part 编号（[1, 2, 3]）。"""
    svc = _get_service()
    parts = await asyncio.to_thread(svc.get_parts)
    return parts


@api_router.get("/random", response_model=RandomTopicResponse)
async def api_random(
    user: Annotated[WebUser, Depends(get_current_user)],
    part: Annotated[Optional[int], Query(ge=1, le=3)] = None,
) -> dict:
    """按 Part 随机抽一条话题（含 sample_answer + tips）。

    与 CLI ``ib speak practice`` 一致：只展示范文和技巧，
    不录音、不评分、不陪练。
    """
    svc = _get_service()
    all_topics = await asyncio.to_thread(svc.get_topics)
    topic = await asyncio.to_thread(svc.get_random_topic, part)

    if topic is None:
        raise HTTPException(status_code=404, detail="没有找到匹配的话题")

    # 计算 topic_id（与 /topics 列表的 1-based 索引一致）
    idx = all_topics.index(topic) + 1
    part_int = topic["part"]
    return {
        "topic_id": idx,
        "part": part_int,
        "part_label": _PART_LABELS.get(part_int, f"Part {part_int}"),
        "topic": topic["topic"],
        "questions": topic["questions"],
        "vocab": topic["vocab"],
        "sample_answer": topic["sample_answer"],
        "tips": topic["tips"],
    }


@api_router.get("/vocab", response_model=VocabCard)
async def api_vocab(
    user: Annotated[WebUser, Depends(get_current_user)],
    topic: Annotated[str, Query(min_length=1, max_length=100)],
) -> dict:
    """按 topic 名模糊匹配，返回词汇卡。

    与 CLI ``ib speak vocab <topic>`` 行为一致：
    不区分大小写、首次命中的 topic。
    """
    svc = _get_service()
    result = await asyncio.to_thread(svc.get_speaking_vocab, topic)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"没有找到与 '{topic}' 相关的话题",
        )
    part_int = result["part"]
    return {
        "part": part_int,
        "part_label": _PART_LABELS.get(part_int, f"Part {part_int}"),
        "topic": result["topic"],
        "vocab": result["vocab"],
        "questions": result["questions"],
    }


@api_router.get("/detail", response_model=TopicItem)
async def api_detail(
    user: Annotated[WebUser, Depends(get_current_user)],
    topic_id: Annotated[int, Query(ge=1)],
) -> dict:
    """按 topic_id 取单条话题详情。"""
    svc = _get_service()
    topic = await asyncio.to_thread(svc.get_topic_detail, topic_id)
    if topic is None:
        raise HTTPException(
            status_code=404,
            detail=f"找不到 topic_id={topic_id} 的话题",
        )
    return {
        "topic_id": topic_id,
        "part": topic["part"],
        "topic": topic["topic"],
        "questions": topic["questions"],
        "vocab": topic["vocab"],
        "sample_answer": topic["sample_answer"],
        "tips": topic["tips"],
    }


@api_router.get("/count", response_model=CountResponse)
async def api_count(
    user: Annotated[WebUser, Depends(get_current_user)],
    part: Annotated[Optional[int], Query(ge=1, le=3)] = None,
) -> dict:
    """统计话题数量（可按 Part 筛选）。"""
    svc = _get_service()
    total = await asyncio.to_thread(svc.count, part)
    return {"total": total}


__all__ = ["router", "api_router"]