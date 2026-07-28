"""/vocab/browse 词库浏览路由。

功能：
- GET /vocab/browse: 词库浏览页面
- GET /api/vocab/list: 分页获取词库列表
- GET /api/vocab/search: 搜索词库
- GET /api/vocab/stats: 获取词库统计
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.auth.deps import get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_vocab_service


router = APIRouter(tags=["vocab"])
api_router = APIRouter(prefix="/api/vocab", tags=["vocab-api"])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


# =============================================================
# 页面路由
# =============================================================


@router.get("/vocab/browse", response_class=HTMLResponse)
def page_browse(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
) -> HTMLResponse:
    """词库浏览页面"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    # 获取词库统计
    stats = _get_vocab_stats(vocab)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/vocab_browse.html",
        {
            "title": "词库浏览",
            "phase": 2,
            "current_user": user,
            "stats": stats,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


@api_router.get("/list")
def api_vocab_list(
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
    band: Annotated[Optional[int], Query(ge=5, le=9)] = None,
    topic: Annotated[Optional[str], Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=5, le=100)] = 20,
) -> dict:
    """分页获取词库列表"""
    words = vocab.all_words()

    # 按 Band 筛选
    if band is not None:
        words = [w for w in words if w.band == band]

    # 按主题筛选
    if topic:
        words = [w for w in words if w.topic == topic]

    # 统计
    total = len(words)

    # 分页
    start = (page - 1) * per_page
    end = start + per_page
    page_words = words[start:end]

    return {
        "words": [
            {
                "word": w.word,
                "phonetic": w.phonetic,
                "pos": w.pos,
                "meaning": w.meaning,
                "band": w.band,
                "topic": w.topic,
                "example": w.example,
                "example_cn": w.example_cn,
            }
            for w in page_words
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@api_router.get("/search")
def api_vocab_search(
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
    q: Annotated[str, Query(min_length=1, max_length=100)],
    band: Annotated[Optional[int], Query(ge=5, le=9)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=5, le=100)] = 20,
) -> dict:
    """搜索词库"""
    words = vocab.all_words()
    q_lower = q.lower().strip()

    # 搜索：单词、释义、例句
    filtered = [
        w for w in words
        if (
            q_lower in w.word.lower()
            or q_lower in w.meaning.lower()
            or (w.example and q_lower in w.example.lower())
        )
    ]

    # 按 Band 筛选
    if band is not None:
        filtered = [w for w in filtered if w.band == band]

    total = len(filtered)

    # 分页
    start = (page - 1) * per_page
    end = start + per_page
    page_words = filtered[start:end]

    return {
        "words": [
            {
                "word": w.word,
                "phonetic": w.phonetic,
                "pos": w.pos,
                "meaning": w.meaning,
                "band": w.band,
                "topic": w.topic,
                "example": w.example,
                "example_cn": w.example_cn,
            }
            for w in page_words
        ],
        "total": total,
        "query": q,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@api_router.get("/stats")
def api_vocab_stats(
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
) -> dict:
    """获取词库统计"""
    return _get_vocab_stats(vocab)


def _get_vocab_stats(vocab: VocabService) -> dict:
    """获取词库统计"""
    words = vocab.all_words()

    # 按 Band 统计
    band_counts = {5: 0, 6: 0, 7: 0, 8: 0, 9: 0}
    for w in words:
        if w.band in band_counts:
            band_counts[w.band] += 1

    # 按主题统计
    topic_counts: dict[str, int] = {}
    for w in words:
        topic = w.topic or "其他"
        topic_counts[topic] = topic_counts.get(topic, 0) + 1

    # 排序主题
    sorted_topics = sorted(topic_counts.items(), key=lambda x: -x[1])

    return {
        "total_words": len(words),
        "band_counts": band_counts,
        "topics": [{"name": t, "count": c} for t, c in sorted_topics],
    }


__all__ = ["router", "api_router"]
