"""/study/random 和 /study/review 的页面路由 + HTMX 答题端点。

设计：
- 主页面 GET /study/{random,review} 返回整页（首次进入）
- HTMX 局部 POST /api/study/answer 接受用户答题结果，返回下一个题卡片段
- 全部走业务容器 ``app.state.container``（SQLite/MySQL 都自动适配）
- 之前依赖 ``get_stats_conn``（SQLite-only），导致 MySQL 模式下整个 study 模块
  崩溃；现在统一走业务容器的 ``learning`` Repository。
"""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ielts_buddy.core.models import Word
from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import (
    get_container,
    get_vocab_service,
)


router = APIRouter(tags=["study"])


# 艾宾浩斯间隔（与 services/review_service.REVIEW_INTERVALS 对齐）
_REVIEW_INTERVALS = [0, 1, 2, 4, 7, 15, 30]


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


# =============================================================
# 内部：业务容器的 learning repo（MySQL/SQLite 自动适配）
# =============================================================


def _pick_new_word(
    vocab: VocabService,
    container,
    user_id: int,
) -> Optional[Word]:
    """从词库随机抽一个 user 还没学过的词（band 5-9 随机）。"""
    band = random.choice([5, 6, 7, 8, 9])
    pool = vocab.filter_by_band(band)
    if not pool:
        return None
    learned = container.learning.get_learned_words(user_id)
    learned_set = set(learned)
    candidates = [w for w in pool if w.word not in learned_set]
    if not candidates:
        return None
    return random.choice(candidates)


def _pick_due_word(container, user_id: int) -> Optional[Word]:
    """从待复习队列选一题。"""
    words = container.learning.get_due_words(user_id, limit=1)
    if not words:
        return None
    try:
        word_data = json.loads(words[0]["word_data"])
        return Word(**word_data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _due_count(container, user_id: int) -> int:
    return container.learning.get_due_count(user_id)


# =============================================================
# 页面：随机学习
# =============================================================


@router.get("/study/random", response_class=HTMLResponse)
def page_study_random(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
    container=Depends(get_container),
) -> HTMLResponse:
    """随机学习主页：选一题渲染。未登录跳 /login。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    w = _pick_new_word(vocab, container, user.id)
    ctx = {
        "title": "随机学习",
        "phase": 3,
        "current_user": user,
        "word": w,
        "mode": "random",
        "due_count": _due_count(container, user.id),
        "empty_msg": None if w else "词库暂无可学单词。",
        "request": request,
    }
    return _get_templates(request).TemplateResponse(
        request, "pages/study_random.html", ctx
    )


@router.get("/study/review", response_class=HTMLResponse)
def page_study_review(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
    container=Depends(get_container),
) -> HTMLResponse:
    """复习主页：从待复习队列取一题。未登录跳 /login。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    w = _pick_due_word(container, user.id)
    ctx = {
        "title": "复习",
        "phase": 3,
        "current_user": user,
        "word": w,
        "mode": "review",
        "due_count": _due_count(container, user.id),
        "empty_msg": None if w else "暂无待复习单词 🎉",
        "request": request,
    }
    return _get_templates(request).TemplateResponse(
        request, "pages/study_review.html", ctx
    )


# =============================================================
# HTMX 局部端点：答题后返回下一题片段
# =============================================================


@router.post("/api/study/answer", response_class=HTMLResponse)
def api_study_answer(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    word: Annotated[str, Form()],
    correct: Annotated[bool, Form()],
    mode: Annotated[str, Form()],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
    container=Depends(get_container),
) -> HTMLResponse:
    """记录一次答题结果并返回下一题的卡片片段。"""
    w = vocab.get_word(word)
    if w is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"词库中找不到单词 '{word}'",
        )

    # 写学习记录（业务容器的 learning repo，SQLite/MySQL 都通用）
    container.learning.upsert_record(user.id, w, correct=correct, source="web")

    # v3.6 错词本：答错自动入 personal_vocab.mistakes 分类
    if not correct and hasattr(container, "personal_vocab"):
        try:
            from ielts_buddy.services.mistake_service import MistakeService
            MistakeService(container, int(user.id)).record_mistake(
                w, source=f"{mode}_mistake"
            )
        except Exception:
            import logging
            logging.getLogger("ielts_buddy.web.study").warning(
                "[study] record_mistake failed for %r", w.word, exc_info=True
            )

    # 选下一题
    if mode == "random":
        next_word = _pick_new_word(vocab, container, user.id)
        ctx_due = None
        empty_msg = "今日新词已学完 ✅ 休息一下，明天继续。" if next_word is None else None
    elif mode == "review":
        next_word = _pick_due_word(container, user.id)
        ctx_due = _due_count(container, user.id)
        empty_msg = "今日复习已完成 🎉" if next_word is None else None
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未知 mode: {mode}",
        )

    ctx = {
        "title": "学习",
        "phase": 3,
        "current_user": user,
        "word": next_word,
        "mode": mode,
        "due_count": ctx_due if ctx_due is not None else _due_count(container, user.id),
        "empty_msg": empty_msg,
        "request": request,
    }
    # 只返回 _study_card.html 片段（不含 base.html），HTMX 用 outerHTML
    # 替换到 #study-card 节点，避免每次答题都嵌套整个页面（侧边栏重复）
    return _get_templates(request).TemplateResponse(
        request, "partials/_study_card.html", ctx
    )


__all__ = ["router"]