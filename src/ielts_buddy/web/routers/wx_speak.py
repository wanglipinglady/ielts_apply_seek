"""小程序 W3 口语对练路由（v3.9+ / 2026-08-24）。

端点（统一前缀 /api/wx/speak/practice）：
- POST /start         抽题 + 生成 session_id
- POST /submit        录音 → 转写 → 评分 → 错词回收
- GET  /history       历史列表
- GET  /{record_id}   单条详情

设计原则（CLAUDE.md 5 条铁律）：
1. service 层完全沿用 SpeakingPracticeService（不重写逻辑）
2. 路由层只做「端到端编排」+ JSON 序列化
3. 路径前缀 /api/wx/ 与 Web /api/ 物理隔离
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request,
    UploadFile, status,
)
from pydantic import BaseModel

from ielts_buddy.services.speaking_practice_service import (
    SpeakingPracticeService, SubmitResult,
)
from ielts_buddy.web.auth.deps import get_current_user
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_container

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wx/speak/practice", tags=["wx-speak"])


# =============================================================
# Helpers
# =============================================================


def _container_or_500(request: Request):
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="业务容器未初始化")
    return container


def _service(request: Request, user_id: int) -> SpeakingPracticeService:
    container = _container_or_500(request)
    return SpeakingPracticeService(container=container, user_id=user_id)


# =============================================================
# Pydantic Schemas
# =============================================================


class WxStartPracticeResponse(BaseModel):
    session_id: str
    part: int
    part_label: str
    topic_id: int
    topic: str
    question: str
    vocab: list[str]
    sample_answer: str
    tips: str


class WxScoreBlock(BaseModel):
    fluency: float
    lexical: float
    grammar: float
    pronunciation: float
    overall_band: float


class WxWordError(BaseModel):
    original: str = ""
    correction: str = ""
    context: str = ""
    word: str = ""


class WxGrammarError(BaseModel):
    original: str = ""
    correction: str = ""
    rule: str = ""


class WxSubmitPracticeResponse(BaseModel):
    record_id: int
    session_id: str
    transcript: str
    tokens: list[dict]
    scores: WxScoreBlock
    word_errors: list[WxWordError]
    grammar_errors: list[WxGrammarError]
    highlights: list[str]
    suggestions: list[str]
    whisper_fallback: bool = False
    score_fallback: bool = False


class WxHistoryItem(BaseModel):
    record_id: int
    session_id: str
    created_at: str
    part: int
    topic: str
    question: str
    audio_duration_sec: float
    overall_band: Optional[float] = None
    word_error_count: int = 0


class WxHistoryResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[WxHistoryItem]


# =============================================================
# 1. POST /api/wx/speak/practice/start
# =============================================================


@router.post("/start", response_model=WxStartPracticeResponse)
async def wx_speak_start(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    part: Annotated[Optional[int], Query(ge=1, le=3)] = None,
) -> WxStartPracticeResponse:
    """抽一道题（沿用 Web 端 /api/speak/practice/start 行为）。"""
    svc = _service(request, int(user.id))
    result = await asyncio.to_thread(svc.start_practice, part)
    if result is None:
        raise HTTPException(status_code=404, detail="题库为空")
    return WxStartPracticeResponse(
        session_id=result.session_id,
        part=result.part,
        part_label=result.part_label,
        topic_id=result.topic_id,
        topic=result.topic,
        question=result.question,
        vocab=result.vocab,
        sample_answer=result.sample_answer,
        tips=result.tips,
    )


# =============================================================
# 2. POST /api/wx/speak/practice/submit
# =============================================================


@router.post("/submit", response_model=WxSubmitPracticeResponse)
async def wx_speak_submit(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[str, Form(min_length=4, max_length=64)],
    part: Annotated[int, Form(ge=1, le=3)],
    topic_id: Annotated[int, Form(ge=0)],
    topic_name: Annotated[str, Form(min_length=1, max_length=128)],
    question: Annotated[str, Form(min_length=1)],
    actual_duration_sec: Annotated[float, Form(ge=0.0, le=180.0)] = 0.0,
    vocab_hints: Annotated[str, Form()] = "",
    sample_answer: Annotated[str, Form()] = "",
    audio: Annotated[UploadFile, File()] = ...,  # 必填
) -> WxSubmitPracticeResponse:
    """录音 → 转写 → 评分 → 错词回收（沿用 Web 端逻辑）。"""
    # ---- 校验音频 ----
    mime = (audio.content_type or "").lower()
    if mime and not any(s in mime for s in
                       ("webm", "ogg", "wav", "mp3", "mpeg", "mp4", "octet-stream")):
        raise HTTPException(status_code=422, detail=f"不支持的音频类型: {mime}")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="音频为空")
    if len(audio_bytes) > 30 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="音频超过 30MB 上限")

    vocab_list = [w.strip() for w in vocab_hints.split(",") if w.strip()]

    svc = _service(request, int(user.id))
    out: SubmitResult = await asyncio.to_thread(
        svc.submit,
        session_id=session_id,
        part=part,
        topic_id=topic_id,
        topic_name=topic_name,
        question=question,
        audio_bytes=audio_bytes,
        audio_mime=mime or "audio/webm",
        actual_duration_sec=actual_duration_sec,
        vocab_hints=vocab_list,
        sample_answer=sample_answer,
    )

    scores = out.scores
    return WxSubmitPracticeResponse(
        record_id=out.record_id,
        session_id=out.session_id,
        transcript=out.transcript,
        tokens=out.tokens,
        scores=WxScoreBlock(
            fluency=scores.get("fluency", 6.0),
            lexical=scores.get("lexical", 6.0),
            grammar=scores.get("grammar", 6.0),
            pronunciation=scores.get("pronunciation", 6.0),
            overall_band=scores.get("overall_band", 6.0),
        ),
        word_errors=[
            WxWordError(**{
                "original": we.get("original", ""),
                "correction": we.get("correction", ""),
                "context": we.get("context", ""),
                "word": we.get("word", "") or we.get("correction", ""),
            }) for we in out.word_errors
        ],
        grammar_errors=[WxGrammarError(**ge) for ge in out.grammar_errors],
        highlights=out.highlights,
        suggestions=out.suggestions,
        whisper_fallback=out.whisper_fallback,
        score_fallback=out.score_fallback,
    )


# =============================================================
# 3. GET /api/wx/speak/practice/history
# =============================================================


@router.get("/history", response_model=WxHistoryResponse)
async def wx_speak_history(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    part: Annotated[Optional[int], Query(ge=1, le=3)] = None,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> WxHistoryResponse:
    """口语历史（沿用 Web 端 list_history 行为）。"""
    svc = _service(request, int(user.id))
    items, total = await asyncio.to_thread(svc.list_history, part, page, size)

    history_items: list[WxHistoryItem] = []
    for item in items:
        try:
            scores = json.loads(item.get("llm_scores") or "{}")
            overall = float(scores.get("overall_band")) if scores.get("overall_band") is not None else None
            word_errors = json.loads(item.get("llm_word_errors") or "[]")
        except Exception:
            overall, word_errors = None, []
        history_items.append(WxHistoryItem(
            record_id=int(item["id"]),
            session_id=item["session_id"],
            created_at=item["created_at"],
            part=int(item["part"]),
            topic=item.get("topic_name") or "",
            question=item.get("question") or "",
            audio_duration_sec=float(item.get("audio_duration_sec") or 0),
            overall_band=overall,
            word_error_count=len(word_errors),
        ))
    return WxHistoryResponse(
        total=total, page=page, size=size, items=history_items,
    )


# =============================================================
# 4. GET /api/wx/speak/practice/{record_id}
# =============================================================


@router.get("/{record_id}")
async def wx_speak_record_detail(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
) -> dict:
    """单条详情（沿用 Web 端 get_record）。"""
    svc = _service(request, int(user.id))
    item = await asyncio.to_thread(svc.get_record, record_id)
    if item is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    # JSON 字段解析
    try:
        scores = json.loads(item.get("llm_scores") or "{}")
    except Exception:
        scores = {}
    try:
        word_errors = json.loads(item.get("llm_word_errors") or "[]")
        grammar_errors = json.loads(item.get("llm_grammar_errors") or "[]")
        highlights = json.loads(item.get("llm_highlights") or "[]")
        suggestions = json.loads(item.get("llm_suggestions") or "[]")
    except Exception:
        word_errors, grammar_errors, highlights, suggestions = [], [], [], []
    return {
        "record_id": int(item["id"]),
        "session_id": item["session_id"],
        "created_at": item["created_at"],
        "part": int(item["part"]),
        "topic": item.get("topic_name") or "",
        "question": item.get("question") or "",
        "transcript": item.get("transcript") or "",
        "scores": scores,
        "word_errors": word_errors,
        "grammar_errors": grammar_errors,
        "highlights": highlights,
        "suggestions": suggestions,
        "audio_url": (
            f"/api/speak/practice/audio/{item['session_id']}"
            if item.get("audio_path") else None
        ),
    }


__all__ = ["router"]