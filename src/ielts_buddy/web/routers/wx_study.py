"""小程序 W2 学习模块路由（v3.9+ / 2026-08-24）。

端点（统一前缀 /api/wx/study）：
- GET  /vocab/list            词库浏览
- POST /vocab/random          随机抽 N 个词
- POST /vocab/quiz/submit      提交测验答案
- GET  /review/due            今日待复习（艾宾浩斯到期）
- POST /review/submit         提交复习答案
- GET  /mistakes              错词本

设计原则（CLAUDE.md 5 条铁律）：
1. service 层完全沿用 ReviewService（不重写逻辑）
2. 路由层只做「端到端编排」+ JSON 序列化
3. 新增字段默认可选，不破坏现有 Web 端调用
4. 路径前缀 /api/wx/ 与 Web /api/ 物理隔离
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ielts_buddy.core.models import Word
from ielts_buddy.services.mistake_service import MistakeService
from ielts_buddy.services.review_service import ReviewService
from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.auth.deps import get_current_user
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_container, get_vocab_service, get_review_service


router = APIRouter(prefix="/api/wx/study", tags=["wx-study"])


# =============================================================
# Helpers
# =============================================================


def _container_or_500(request: Request):
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="业务容器未初始化",
        )
    return container


# 注意：ReviewService 必须用 Depends 注入（不能手动构造）
# 详见 web/services.py:137
def _review_service_from_deps(review_svc: ReviewService = Depends(get_review_service)) -> ReviewService:
    return review_svc


# =============================================================
# Pydantic Schemas
# =============================================================


class VocabRandomRequest(BaseModel):
    band: Optional[int] = Field(default=None, ge=5, le=9)
    count: int = Field(default=10, ge=1, le=50)


class VocabQuizSubmitRequest(BaseModel):
    word: str = Field(min_length=1, max_length=128)
    user_answer: str = Field(min_length=1, max_length=512)
    correct: bool
    mode: str = Field(default="en2zh", pattern="^(en2zh|zh2en)$")


class ReviewSubmitRequest(BaseModel):
    word: str = Field(min_length=1, max_length=128)
    correct: bool


# =============================================================
# 1. GET /api/wx/study/vocab/list
# =============================================================


@router.get("/vocab/list")
async def wx_vocab_list(
    user: Annotated[WebUser, Depends(get_current_user)],
    band: Optional[int] = Query(default=None, ge=5, le=9),
    topic: Optional[str] = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=5, le=100),
) -> dict:
    """词库浏览（沿用 Web /api/vocab/list 行为）。"""
    vocab: VocabService = get_vocab_service()  # 无 request 参数
    pool = vocab.filter_by_band(band) if band else vocab.all_words()
    if topic:
        pool = [w for w in pool if w.topic == topic]

    total = len(pool)
    start = (page - 1) * per_page
    items = pool[start:start + per_page]

    return {
        "words": [_word_to_dict(w) for w in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


# =============================================================
# 2. POST /api/wx/study/vocab/random
# =============================================================


@router.post("/vocab/random")
async def wx_vocab_random(
    body: VocabRandomRequest,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> dict:
    """随机抽 N 个词（用于「抽词」Tab）。不写学习记录。"""
    vocab: VocabService = get_vocab_service()  # 无 request 参数
    pool = vocab.filter_by_band(body.band) if body.band else vocab.all_words()
    if not pool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"没有可用的词（band={body.band}）",
        )
    sampled = random.sample(pool, min(body.count, len(pool)))
    return {
        "words": [_word_to_dict(w) for w in sampled],
        "count": len(sampled),
    }


# =============================================================
# 3. POST /api/wx/study/vocab/quiz/submit
# =============================================================


@router.post("/vocab/quiz/submit")
async def wx_vocab_quiz_submit(
    body: VocabQuizSubmitRequest,
    user: Annotated[WebUser, Depends(get_current_user)],
    review_svc: ReviewService = Depends(get_review_service),
) -> dict:
    """提交测验答案，写入 learning_records（艾宾浩斯联动）。"""
    vocab: VocabService = get_vocab_service()
    svc = review_svc  # 用 Depends 注入的实例（user_id 已绑定）

    word_obj = vocab.get_word(body.word)
    if word_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"单词 {body.word!r} 不在词库中",
        )

    # 调 ReviewService.record_learn（沿用现有逻辑，艾宾浩斯算法在 service 内）
    try:
        svc.record_learn(word_obj, correct=body.correct, source=f"wx_quiz_{body.mode}")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"写学习记录失败: {e}",
        )

    rec = svc._get_record(body.word)
    next_review = getattr(rec, "next_review", None) if rec else None
    next_review_str = (
        next_review.isoformat()
        if next_review and hasattr(next_review, "isoformat")
        else (
            next_review
            if isinstance(next_review, str)
            else (date.today() + timedelta(days=1)).isoformat()
        )
    )
    return {
        "word": body.word,
        "is_correct": body.correct,
        "memory_level": int(getattr(rec, "memory_level", 0)) if rec else 0,
        "next_review_at": next_review_str,
    }


# =============================================================
# 4. GET /api/wx/study/review/due
# =============================================================


@router.get("/review/due")
async def wx_review_due(
    user: Annotated[WebUser, Depends(get_current_user)],
    band: Optional[int] = Query(default=None, ge=5, le=9),
    limit: int = Query(default=50, ge=1, le=200),
    review_svc: ReviewService = Depends(get_review_service),
) -> dict:
    """今日待复习（艾宾浩斯到期）。"""
    raw = review_svc.get_due_words(limit=limit)

    # 过滤 + 拼装小程序需要的字段
    vocab: VocabService = get_vocab_service()
    due_words = []
    for item in raw:
        word = item.get("word") if isinstance(item, dict) else getattr(item, "word", None)
        if not word:
            continue
        # 取 vocabulary 的释义（前端展示）
        word_obj = vocab.get_word(word)
        due_words.append({
            "word": word,
            "meaning": (word_obj.meaning if word_obj else ""),
            "phonetic": (word_obj.phonetic if word_obj else ""),
            "band": (word_obj.band if word_obj else None),
            "memory_level": item.get("memory_level", 0) if isinstance(item, dict) else getattr(item, "memory_level", 0),
            "next_review_at": (
                item.get("next_review").isoformat()
                if isinstance(item, dict) and item.get("next_review") and hasattr(item["next_review"], "isoformat")
                else str(item.get("next_review", "")) if isinstance(item, dict) else str(getattr(item, "next_review", ""))
            ),
        })

    if band:
        due_words = [w for w in due_words if w["band"] == band]

    return {
        "due_words": due_words,
        "count": len(due_words),
        "today": date.today().isoformat(),
    }


# =============================================================
# 5. POST /api/wx/study/review/submit
# =============================================================


@router.post("/review/submit")
async def wx_review_submit(
    body: ReviewSubmitRequest,
    user: Annotated[WebUser, Depends(get_current_user)],
    review_svc: ReviewService = Depends(get_review_service),
) -> dict:
    """提交复习答案。"""
    vocab: VocabService = get_vocab_service()
    svc = review_svc

    word_obj = vocab.get_word(body.word)
    if word_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"单词 {body.word!r} 不在词库中",
        )

    try:
        svc.record_learn(word_obj, correct=body.correct, source="wx_review")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"复习记录失败: {e}",
        )

    rec = svc._get_record(body.word)
    next_review = getattr(rec, "next_review", None) if rec else None
    next_review_str = (
        next_review.isoformat()
        if next_review and hasattr(next_review, "isoformat")
        else (
            next_review
            if isinstance(next_review, str)
            else (date.today() + timedelta(days=1)).isoformat()
        )
    )
    return {
        "word": body.word,
        "memory_level": int(getattr(rec, "memory_level", 0)) if rec else 0,
        "next_review_at": next_review_str,
    }


# =============================================================
# 6. GET /api/wx/study/mistakes — 错词本
# =============================================================


@router.get("/mistakes")
async def wx_review_mistakes(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """错词本（沿用 Web /api/mistakes/words 行为）。

    数据源：learning_records.wrong_count > 0（MistakeService.list_wrong_words）。
    """
    container = _container_or_500(request)
    user_id = int(user.id)

    mistake_svc = MistakeService(container, user_id)
    raw = mistake_svc.list_wrong_words(min_wrong=1, limit=limit)

    # 补全释义 + 归一化字段
    vocab: VocabService = get_vocab_service()
    items = []
    for m in raw:
        word = m.get("word") if isinstance(m, dict) else getattr(m, "word", None)
        if not word:
            continue
        word_obj = vocab.get_word(word)
        # last_reviewed 可能是 datetime/str
        last_rev = m.get("last_reviewed") if isinstance(m, dict) else getattr(m, "last_reviewed", None)
        last_rev_str = (
            last_rev.isoformat() if hasattr(last_rev, "isoformat") else str(last_rev or "")
        )
        items.append({
            "word": word,
            "meaning": (word_obj.meaning if word_obj else ""),
            "wrong_count": m.get("wrong_count", 0) if isinstance(m, dict) else getattr(m, "wrong_count", 0),
            "last_reviewed": last_rev_str,
        })

    return {
        "mistakes": items,
        "count": len(items),
    }


# =============================================================
# Internal helpers
# =============================================================


def _word_to_dict(w: Word) -> dict:
    return {
        "word": w.word,
        "phonetic": w.phonetic or "",
        "meaning": w.meaning or "",
        "pos": w.pos or "",
        "band": w.band,
        "topic": w.topic or "",
        "example": getattr(w, "example", None) or "",
    }


def _fallback_mistakes(container, user_id: int, limit: int) -> list[dict]:
    """老版 repo fallback：直接 SQL。"""
    try:
        rows = container.learning._conn.execute(
            """SELECT word, wrong_count, last_reviewed
               FROM learning_records
               WHERE user_id = ? AND wrong_count > 0
               ORDER BY wrong_count DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [
            {"word": r[0], "wrong_count": r[1] or 0, "last_reviewed": r[2] or ""}
            for r in rows
        ]
    except Exception:
        return []


__all__ = ["router"]