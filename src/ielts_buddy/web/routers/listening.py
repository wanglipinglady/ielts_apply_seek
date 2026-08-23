"""/listen 听力路由（B 档 Web 化）。

> 注意：仓库内**没有**任何音频资源文件，所以本 MVP **不做音频播放**，
> 只是把 CLI ``ListeningService`` 的功能 web 化（资源列表 + 单词听写答题）。

端点：
- GET  /listen                      : 听力页面（资源浏览 / 单词听写 两个 tab）
- GET  /api/listening/resources     : 资源列表，支持 type / difficulty 过滤
- GET  /api/listening/detail        : 资源详情，按 idx 查询
- GET  /api/listening/dictation     : 生成听写题
- POST /api/listening/record        : 提交听写答题，每个词写入 learning_records

听写答题数据持久化复用现有 ``learning_records`` 表（与 CLI 一致），
通过 ``ReviewService.record_learn()`` 写入，source="builtin"。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ielts_buddy.core.models import Word
from ielts_buddy.services.listening_service import ListeningService
from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_review_service, get_vocab_service
from ielts_buddy.services.review_service import ReviewService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["listening"])
api_router = APIRouter(prefix="/api/listening", tags=["listening-api"])


# =============================================================
# Helpers
# =============================================================


def _get_templates(request: Request):
    return request.app.state.templates


def _make_listening_service() -> ListeningService:
    """ListeningService 是无状态的（内部只懒加载资源 JSON）。

    每个请求新建一份即可，避免 module-level 单例在测试间泄漏。
    """
    return ListeningService()


# =============================================================
# 页面路由
# =============================================================


@router.get("/listen", response_class=HTMLResponse)
def page_listen(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """听力页面：资源浏览 / 单词听写 两个 tab。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/listening.html",
        {
            "title": "听力",
            "phase": 7,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# 响应模型（API）
# =============================================================


class ResourceItem(BaseModel):
    """听力资源条目。"""

    idx: int            # 1-based 序号（与 CLI ib listen resources 一致）
    type: str
    difficulty: str
    title: str
    url: str
    description: str
    topics: list[str] = []
    free: bool = True


class DictationQuestion(BaseModel):
    """听写题。"""

    word: str
    phonetic: str = ""
    definition: str = ""


class DictationResponse(BaseModel):
    """听写出题响应。"""

    count: int
    questions: list[DictationQuestion]


class DictationAnswer(BaseModel):
    """单题答案（前端提交）。"""

    word: str
    answer: str = ""


class RecordRequest(BaseModel):
    """听写答题提交请求。"""

    answers: list[DictationAnswer]


class RecordResponse(BaseModel):
    """听写答题提交响应。"""

    total: int
    correct: int
    wrong: int
    correct_words: list[str] = []
    wrong_words: list[str] = []


# =============================================================
# API 路由
# =============================================================


@api_router.get("/resources", response_model=list[ResourceItem])
async def api_resources(
    user: Annotated[WebUser, Depends(get_current_user)],
    type: Annotated[Optional[str], Query()] = None,
    difficulty: Annotated[Optional[str], Query()] = None,
) -> list[ResourceItem]:
    """资源列表，支持按 type / difficulty 过滤。"""
    svc = _make_listening_service()
    items = await asyncio.to_thread(
        svc.get_resources, type=type, difficulty=difficulty
    )

    # 计算每个 item 在全集中的 idx（1-based），与 CLI 行为对齐
    all_items = await asyncio.to_thread(svc.get_resources)

    out: list[ResourceItem] = []
    for r in items:
        try:
            idx = all_items.index(r) + 1
        except ValueError:
            idx = 0
        out.append(
            ResourceItem(
                idx=idx,
                type=r.get("type", ""),
                difficulty=r.get("difficulty", ""),
                title=r.get("title", ""),
                url=r.get("url", ""),
                description=r.get("description", ""),
                topics=list(r.get("topics", []) or []),
                free=bool(r.get("free", True)),
            )
        )
    return out


@api_router.get("/detail", response_model=ResourceItem)
async def api_detail(
    user: Annotated[WebUser, Depends(get_current_user)],
    idx: Annotated[int, Query(ge=1)],
) -> ResourceItem:
    """按 idx 获取资源详情（1-based）。"""
    svc = _make_listening_service()
    item = await asyncio.to_thread(svc.get_resource_detail, idx)
    if item is None:
        # 与 CLI ``ib listen detail N`` 越界行为一致：返回 None / 404
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="资源不存在")

    return ResourceItem(
        idx=idx,
        type=item.get("type", ""),
        difficulty=item.get("difficulty", ""),
        title=item.get("title", ""),
        url=item.get("url", ""),
        description=item.get("description", ""),
        topics=list(item.get("topics", []) or []),
        free=bool(item.get("free", True)),
    )


@api_router.get("/dictation", response_model=DictationResponse)
async def api_dictation(
    user: Annotated[WebUser, Depends(get_current_user)],
    count: Annotated[int, Query(ge=1, le=50)] = 10,
    band: Annotated[Optional[int], Query(ge=5, le=9)] = None,
) -> DictationResponse:
    """生成听写题。

    - 从 VocabService 拿候选词（按 band 可选过滤）
    - 调 ListeningService.generate_dictation 抽取 count 道题
    """
    vocab_svc: VocabService = get_vocab_service()
    pool = await asyncio.to_thread(
        lambda: vocab_svc.random_words(count=count * 3, band=band)
        if band is not None
        else vocab_svc.random_words(count=count * 3)
    )

    listening_svc = _make_listening_service()
    questions = await asyncio.to_thread(
        listening_svc.generate_dictation, pool, count
    )

    return DictationResponse(
        count=len(questions),
        questions=[
            DictationQuestion(
                word=q["word"],
                phonetic=q.get("phonetic", "") or "",
                definition=q.get("definition", "") or "",
            )
            for q in questions
        ],
    )


@api_router.post("/record", response_model=RecordResponse)
async def api_record(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    payload: RecordRequest,
    vocab_svc: Annotated[VocabService, Depends(get_vocab_service)],
    review_svc: Annotated[ReviewService, Depends(get_review_service)],
) -> RecordResponse:
    """提交听写答题：逐题比对 + 写 learning_records。"""
    correct_words: list[str] = []
    wrong_words: list[str] = []
    total = 0

    for item in payload.answers:
        word_text = (item.word or "").strip()
        if not word_text:
            continue
        user_answer = (item.answer or "").strip().lower()
        target = word_text.lower()
        is_correct = user_answer == target and target != ""

        # 从 vocab_service 查完整 Word 对象（record_learn 要 Word 实例）
        word_obj: Word | None = await asyncio.to_thread(
            vocab_svc.get_word, word_text
        )
        if word_obj is None:
            # 没在 vocab 索引里找到 → 用最小 Word 记录（保证 learning_records 落库）
            word_obj = Word(word=word_text, meaning="", band=5)

        try:
            await asyncio.to_thread(
                review_svc.record_learn, word_obj, is_correct, "builtin"
            )
        except Exception as e:
            logger.exception(
                f"[listening] record_learn failed for '{word_text}': {e}"
            )
            # 跳过此题，记为不对
            is_correct = False

        total += 1
        if is_correct:
            correct_words.append(word_text)
        else:
            wrong_words.append(word_text)

    return RecordResponse(
        total=total,
        correct=len(correct_words),
        wrong=len(wrong_words),
        correct_words=correct_words,
        wrong_words=wrong_words,
    )


__all__ = ["router", "api_router"]
