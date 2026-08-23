"""/mistakes 错词本路由（v3.6 新增）。

按 wrong_count DESC 展示用户所有错过的单词 + 一键加入 personal_vocab.mistakes
分类（其实答错时已经自动加，本端点提供手动加入入口供学习统计场景使用）。

端点：
- GET  /mistakes                         : 错词本页面
- GET  /api/mistakes/words               : 错词列表（按 wrong_count DESC）
- GET  /api/mistakes/stats               : 错词聚合统计
- POST /api/mistakes/{word}/add          : 手动加入 personal_vocab.mistakes 分类
- POST /api/mistakes/{word}/mark-correct : 标记某词已掌握（清 wrong_count=0）

数据源：
  - learning_records.wrong_count > 0
  - personal_vocab + vocab_category_words(mistakes 分类)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.services.mistake_service import MistakeService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mistakes"])
api_router = APIRouter(prefix="/api/mistakes", tags=["mistakes-api"])


# =============================================================
# Helpers
# =============================================================


def _get_container(request: Request):
    return getattr(request.app.state, "container", None)


def _get_mistake_service(request: Request, user_id: int) -> MistakeService:
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="业务容器未初始化")
    return MistakeService(container, user_id)


def _enrich_word_dict(raw: dict, vocab_svc) -> dict:
    """把 learning_records 行 dict 补全成前端可用的错词 dict。

    raw 字段:id / user_id / word / word_data(JSON) / memory_level /
            next_review / learn_count / correct_count / wrong_count /
            first_learned / last_reviewed / is_starred / is_difficult /
            source / updated_at / sync_status

    输出字段:word / meaning / phonetic / band / topic / example /
            wrong_count / correct_count / learn_count /
            memory_level / last_reviewed / error_rate / is_difficult /
            is_starred / source
    """
    word_text = raw.get("word", "")
    word_data_raw = raw.get("word_data", "")
    word_data: dict = {}
    if isinstance(word_data_raw, dict):
        word_data = word_data_raw
    elif isinstance(word_data_raw, str) and word_data_raw:
        try:
            word_data = json.loads(word_data_raw)
        except (json.JSONDecodeError, TypeError):
            word_data = {}

    # fallback: 从 vocab_service 取完整字段（保证 meaning/phonetic/example 不为空）
    if vocab_svc and word_text and not word_data.get("meaning"):
        try:
            full = vocab_svc.get_word(word_text)
            if full:
                word_data = {
                    "word": full.word,
                    "phonetic": getattr(full, "phonetic", "") or "",
                    "meaning": getattr(full, "meaning", "") or "",
                    "pos": getattr(full, "pos", "") or "",
                    "band": getattr(full, "band", 5) or 5,
                    "topic": getattr(full, "topic", "") or "",
                    "example": getattr(full, "example", "") or "",
                    "example_cn": getattr(full, "example_cn", "") or "",
                }
        except Exception:
            pass

    learn_count = int(raw.get("learn_count", 0) or 0)
    wrong_count = int(raw.get("wrong_count", 0) or 0)
    error_rate = (
        round(wrong_count / learn_count, 4) if learn_count > 0 else 0.0
    )

    return {
        "word": word_text,
        "meaning": word_data.get("meaning", ""),
        "phonetic": word_data.get("phonetic", ""),
        "pos": word_data.get("pos", ""),
        "band": word_data.get("band", 5),
        "topic": word_data.get("topic", ""),
        "example": word_data.get("example", ""),
        "example_cn": word_data.get("example_cn", ""),
        "wrong_count": wrong_count,
        "correct_count": int(raw.get("correct_count", 0) or 0),
        "learn_count": learn_count,
        "memory_level": int(raw.get("memory_level", 0) or 0),
        "last_reviewed": raw.get("last_reviewed"),
        "error_rate": error_rate,
        "is_difficult": bool(raw.get("is_difficult", 0)),
        "is_starred": bool(raw.get("is_starred", 0)),
        "source": raw.get("source", "builtin"),
    }


# =============================================================
# Pydantic 模型
# =============================================================


class MistakeWord(BaseModel):
    word: str
    meaning: str = ""
    phonetic: str = ""
    pos: str = ""
    band: int = 5
    topic: str = ""
    example: str = ""
    example_cn: str = ""
    wrong_count: int = 0
    correct_count: int = 0
    learn_count: int = 0
    memory_level: int = 0
    last_reviewed: Optional[str] = None
    error_rate: float = 0.0
    is_difficult: bool = False
    is_starred: bool = False
    source: str = "builtin"


class MistakeListResponse(BaseModel):
    total: int
    min_wrong: int
    days: Optional[int] = None
    words: list[MistakeWord]


class MistakeStats(BaseModel):
    distinct_words: int
    total_wrong_count: int
    last_7d_wrong: int
    top_offenders: list[dict]


# =============================================================
# 页面路由
# =============================================================


@router.get("/mistakes", response_class=HTMLResponse)
def page_mistakes(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """错词本页面（按 wrong_count DESC）。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/mistakes.html",
        {
            "title": "错词本",
            "phase": 7,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


@api_router.get("/words", response_model=MistakeListResponse)
async def api_list_mistakes(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    min_wrong: Annotated[int, Query(ge=1, le=50)] = 1,
    days: Annotated[Optional[int], Query(ge=1, le=365)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> MistakeListResponse:
    """返回错词列表（按 wrong_count DESC）。"""
    from ielts_buddy.services.vocab_service import VocabService

    container = _get_container(request)
    vocab_svc = VocabService() if container else None

    svc = _get_mistake_service(request, int(user.id))
    raw_list = await svc.alist_wrong_words(
        min_wrong=min_wrong, days=days, limit=limit
    )
    enriched = [_enrich_word_dict(r, vocab_svc) for r in raw_list]
    return MistakeListResponse(
        total=len(enriched),
        min_wrong=min_wrong,
        days=days,
        words=[MistakeWord(**w) for w in enriched],
    )


@api_router.get("/stats", response_model=MistakeStats)
async def api_mistake_stats(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> MistakeStats:
    """错词本聚合统计。"""
    svc = _get_mistake_service(request, int(user.id))
    stats = await svc.aget_stats()
    return MistakeStats(**stats)


@api_router.post("/{word}/add")
async def api_add_mistake(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    word: str,
) -> JSONResponse:
    """手动加入 personal_vocab.mistakes 分类（答错时已自动加,这里用于补救)。"""
    from ielts_buddy.core.models import PersonalWord, Word

    container = _get_container(request)
    if container is None or not hasattr(container, "personal_vocab"):
        raise HTTPException(status_code=500, detail="业务容器未就绪")

    # 尝试从 vocab_service 取完整 Word
    word_obj: Word | None = None
    try:
        from ielts_buddy.services.vocab_service import VocabService
        vs = VocabService()
        word_obj = vs.get_word(word)
    except Exception:
        word_obj = None

    if word_obj:
        pw = PersonalWord(
            word=word_obj.word,
            phonetic=getattr(word_obj, "phonetic", "") or "",
            meaning=getattr(word_obj, "meaning", "") or "",
            pos=getattr(word_obj, "pos", "") or "",
            band=getattr(word_obj, "band", 5) or 5,
            topic=getattr(word_obj, "topic", "") or "",
            example=getattr(word_obj, "example", "") or "",
            example_cn=getattr(word_obj, "example_cn", "") or "",
        )
    else:
        pw = PersonalWord(word=word, meaning="", band=5)

    try:
        result = container.personal_vocab.add_mistake(
            int(user.id), pw, source="manual_mistake"
        )
        return JSONResponse({"success": True, "word": result.word})
    except Exception as e:
        logger.exception(f"[mistakes] add_mistake failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/{word}/mark-correct")
async def api_mark_correct(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    word: str,
) -> JSONResponse:
    """标记某词已掌握(把 wrong_count 清 0,memory_level 设为 6)。"""
    container = _get_container(request)
    if container is None or not hasattr(container, "learning"):
        raise HTTPException(status_code=500, detail="业务容器未就绪")

    try:
        # 直接调 repo 的 reset_mistake(SQLite/MySQL 都通用)
        ok = await asyncio.to_thread(
            container.learning.reset_mistake, int(user.id), word
        )
        if not ok:
            raise HTTPException(
                status_code=404, detail=f"没有 '{word}' 的学习记录"
            )
        return JSONResponse({"success": True, "word": word})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[mistakes] mark_correct failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router", "api_router"]