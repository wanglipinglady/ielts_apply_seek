"""/speak/practice 口语对练路由（v3.7 P1 新增）。

PRD: docs/web-mvp/plans/phase-8-speaking-practice.md §5

端点:
- GET  /speak/practice                : 对练页面
- POST /api/speak/practice/start      : 抽题 + 生成 session_id
- POST /api/speak/practice/submit     : 录音 → 转写 → 评分 → 错词回收(单端点)
- GET  /api/speak/practice/history    : 历史列表(分页 + part 过滤)
- GET  /api/speak/practice/{record_id}: 单条详情
- GET  /api/speak/practice/audio/{sid} : 流式下载录音(防 IDOR,需自校验)

限制:
- 上传音频 ≤ 120s(PRD §4.2 决策 + .env 可配)
- 仅 webm/opus/wav/mp4/mp3;空文件 / 过大 → 422
- session_id 找不到 → 404(默认 30 分钟有效期内)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from ielts_buddy.services.speaking_practice_service import (
    SpeakingPracticeService,
    SubmitResult,
    get_audio_root,
)
from ielts_buddy.web import config as web_config
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_container

logger = logging.getLogger(__name__)

router = APIRouter(tags=["speaking-practice"])
api_router = APIRouter(prefix="/api/speak/practice", tags=["speaking-practice-api"])


# =============================================================
# Helpers
# =============================================================


def _get_container(request: Request) -> Any:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="业务容器未初始化")
    return container


def _get_service(request: Request, user_id: int) -> SpeakingPracticeService:
    container = _get_container(request)
    return SpeakingPracticeService(container=container, user_id=user_id)


# =============================================================
# Pydantic models
# =============================================================


class StartPracticeResponse(BaseModel):
    session_id: str
    part: int
    part_label: str
    topic_id: int
    topic: str
    question: str
    vocab: list[str]
    sample_answer: str
    tips: str


class ScoreBlock(BaseModel):
    fluency: float
    lexical: float
    grammar: float
    pronunciation: float
    overall_band: float


class WordError(BaseModel):
    original: str = ""
    correction: str = ""
    context: str = ""
    word: str = ""


class GrammarError(BaseModel):
    original: str = ""
    correction: str = ""
    rule: str = ""


class SubmitResponse(BaseModel):
    record_id: int
    session_id: str
    transcript: str
    tokens: list[dict]
    scores: ScoreBlock
    word_errors: list[WordError]
    grammar_errors: list[GrammarError]
    highlights: list[str]
    suggestions: list[str]
    whisper_fallback: bool = False
    score_fallback: bool = False


class HistoryItem(BaseModel):
    record_id: int
    session_id: str
    created_at: str
    part: int
    topic: str
    question: str
    audio_duration_sec: float
    overall_band: Optional[float] = None
    word_error_count: int = 0
    audio_url: Optional[str] = None


class HistoryResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[HistoryItem]


# =============================================================
# 页面: GET /speak/practice
# =============================================================


@router.get("/speak/practice", response_class=HTMLResponse)
def page_speaking_practice(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """口语对练主页。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/speak_practice.html",
        {
            "title": "口语对练",
            "phase": 8,
            "current_user": user,
            "request": request,
            "max_duration_sec": web_config.SPEAKING_MAX_DURATION_SEC,
        },
    )


# =============================================================
# POST /api/speak/practice/start
# =============================================================


@api_router.post("/start", response_model=StartPracticeResponse)
async def api_start_practice(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    part: Annotated[Optional[int], Query(ge=1, le=3)] = None,
) -> StartPracticeResponse:
    """抽一道题,生成 session_id 返回。"""
    svc = _get_service(request, int(user.id))
    result = await asyncio.to_thread(svc.start_practice, part)
    if result is None:
        raise HTTPException(status_code=404, detail="题库为空,无法抽题")
    return StartPracticeResponse(
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
# POST /api/speak/practice/submit
# =============================================================


@api_router.post("/submit", response_model=SubmitResponse)
async def api_submit_practice(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: Annotated[str, Form(min_length=4, max_length=64)],
    part: Annotated[int, Form(ge=1, le=3)],
    topic_id: Annotated[int, Form(ge=0)],
    topic_name: Annotated[str, Form(min_length=1, max_length=128)],
    question: Annotated[str, Form(min_length=1)],
    actual_duration_sec: Annotated[float, Form(ge=0.0, le=180.0)] = 0.0,
    vocab_hints: Annotated[str, Form()] = "",        # 逗号分隔
    sample_answer: Annotated[str, Form()] = "",
    audio: Annotated[UploadFile, File()] = ...,     # 必填
) -> SubmitResponse:
    """完整流水线:音频 → 转写 → 评分 → 错词回收。
    
    全部走 asyncio.to_thread,FastAPI 事件循环不会被阻塞。
    """
    # ---- 1. 校验 ----
    max_dur = web_config.SPEAKING_MAX_DURATION_SEC
    if actual_duration_sec > max_dur + 5:  # +5s 容忍浏览器计时误差
        raise HTTPException(
            status_code=422,
            detail=f"录音时长 {actual_duration_sec:.1f}s 超出上限 {max_dur}s",
        )
    mime = (audio.content_type or "").lower()
    if mime and not any(s in mime for s in
                       ("webm", "ogg", "wav", "mp3", "mpeg", "mp4", "octet-stream")):
        raise HTTPException(status_code=422, detail=f"不支持的音频类型: {mime}")

    # 读 bytes(限 30 MB,防 DoS)
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="音频为空")
    if len(audio_bytes) > 30 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="音频文件超过 30MB 上限")

    # 解析 vocab_hints
    vocab_list = [
        w.strip() for w in vocab_hints.split(",") if w.strip()
    ]

    svc = _get_service(request, int(user.id))
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

    return _submit_to_response(out)


# =============================================================
# GET /api/speak/practice/history
# =============================================================


@api_router.get("/history", response_model=HistoryResponse)
async def api_history(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    part: Annotated[Optional[int], Query(ge=1, le=3)] = None,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> HistoryResponse:
    svc = _get_service(request, int(user.id))
    items, total = await asyncio.to_thread(
        svc.list_history, part, page, size
    )
    history_items: list[HistoryItem] = []
    for item in items:
        # 解析 scores JSON 拿 overall_band 和 word_error_count
        try:
            import json as _json
            scores = _json.loads(item.get("llm_scores") or "{}")
            overall = float(scores.get("overall_band")) if scores.get("overall_band") is not None else None
            word_errors = _json.loads(item.get("llm_word_errors") or "[]")
        except Exception:
            overall, word_errors = None, []
        history_items.append(HistoryItem(
            record_id=int(item["id"]),
            session_id=item["session_id"],
            created_at=item["created_at"],
            part=int(item["part"]),
            topic=item.get("topic_name") or "",
            question=item.get("question") or "",
            audio_duration_sec=float(item.get("audio_duration_sec") or 0),
            overall_band=overall,
            word_error_count=len(word_errors),
            audio_url=(
                f"/api/speak/practice/audio/{item['session_id']}"
                if item.get("audio_path") else None
            ),
        ))
    return HistoryResponse(
        total=total, page=page, size=size, items=history_items
    )


# =============================================================
# GET /api/speak/practice/{record_id}
# =============================================================


@api_router.get("/{record_id}")
async def api_record_detail(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
) -> JSONResponse:
    svc = _get_service(request, int(user.id))
    item = await asyncio.to_thread(svc.get_record, record_id)
    if item is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    # 把 JSON 字段解析回 list/dict
    return JSONResponse(_record_to_dict(item, request))


# =============================================================
# GET /api/speak/practice/audio/{session_id}
# =============================================================


@api_router.get("/audio/{session_id}")
async def api_get_audio(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    session_id: str,
) -> StreamingResponse:
    """流式返回录音文件(限本人 user_id,防 IDOR)。"""
    svc = _get_service(request, int(user.id))
    audio_path = await asyncio.to_thread(svc.get_audio_path, session_id)
    if audio_path is None or not audio_path.exists():
        raise HTTPException(status_code=404, detail="录音已过期或不存在")

    mime = _ext_to_mime(audio_path.suffix.lower())

    def iterfile():
        with audio_path.open("rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(iterfile(), media_type=mime)


# =============================================================
# Helpers
# =============================================================


def _submit_to_response(out: SubmitResult) -> SubmitResponse:
    scores = out.scores
    return SubmitResponse(
        record_id=out.record_id,
        session_id=out.session_id,
        transcript=out.transcript,
        tokens=out.tokens,
        scores=ScoreBlock(
            fluency=scores.get("fluency", 6.0),
            lexical=scores.get("lexical", 6.0),
            grammar=scores.get("grammar", 6.0),
            pronunciation=scores.get("pronunciation", 6.0),
            overall_band=scores.get("overall_band", 6.0),
        ),
        word_errors=[WordError(**{
            "original": we.get("original", ""),
            "correction": we.get("correction", ""),
            "context": we.get("context", ""),
            "word": we.get("word", "") or we.get("correction", ""),
        }) for we in out.word_errors],
        grammar_errors=[GrammarError(**ge) for ge in out.grammar_errors],
        highlights=out.highlights,
        suggestions=out.suggestions,
        whisper_fallback=out.whisper_fallback,
        score_fallback=out.score_fallback,
    )


def _record_to_dict(item: dict, request: Request) -> dict:
    """把 raw DB 行 dict(带 JSON 字符串字段)转成完整 dict。"""
    import json as _json
    def safe_load(s, default):
        try:
            return _json.loads(s) if s else default
        except Exception:
            return default
    sid = item.get("session_id", "")
    return {
        "record_id": int(item["id"]),
        "session_id": sid,
        "user_id": int(item["user_id"]),
        "part": int(item["part"]),
        "topic_id": item.get("topic_id"),
        "topic_name": item.get("topic_name", ""),
        "question": item.get("question", ""),
        "created_at": item.get("created_at", ""),
        "audio_duration_sec": float(item.get("audio_duration_sec") or 0),
        "audio_mime": item.get("audio_mime", "audio/webm"),
        "audio_url": (
            f"/api/speak/practice/audio/{sid}"
            if item.get("audio_path") else None
        ),
        "transcript": item.get("transcript", ""),
        "tokens": safe_load(item.get("transcript_tokens"), []),
        "scores": safe_load(item.get("llm_scores"), {}),
        "word_errors": safe_load(item.get("llm_word_errors"), []),
        "grammar_errors": safe_load(item.get("llm_grammar_errors"), []),
        "highlights": safe_load(item.get("llm_highlights"), []),
        "suggestions": safe_load(item.get("llm_suggestions"), []),
        "whisper_model": item.get("whisper_model", ""),
        "used_core_ml": bool(item.get("used_core_ml", 0)),
        "score_fallback": bool(item.get("score_fallback", 0)),
    }


def _ext_to_mime(ext: str) -> str:
    return {
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".mp4": "audio/mp4",
    }.get(ext, "application/octet-stream")


__all__ = ["router", "api_router"]
