"""语音训练工坊路由（v3.9 W11 新增）。

PRD: docs/web-mvp/plans/phase-11-voice-training-prd.md

端点：
- GET  /voice/training                     : 训练页面（五步循环）
- POST /api/voice-training/rewrite         : 中文 → LLM 改写英文（创建记录）
- POST /api/voice-training/{id}/retry      : 重新生成改写
- POST /api/voice-training/{id}/phonetics  : 音标/音素解析（回填 ipa_json）
- GET  /api/voice-training/word-rule       : 单词拼读规则（LLM+缓存）
- POST /api/voice-training/{id}/tts        : 生成参考语音（edge-tts→MiniMax）
- POST /api/voice-training/{id}/recording  : 上传跟读录音
- GET  /api/voice-training/{id}/audio/{kind}: 音频流（tts|recording，防 IDOR）
- GET  /api/voice-training/records         : 历史列表（分页）
- GET  /api/voice-training/{id}            : 单条详情
- PATCH /api/voice-training/{id}            : 更新纠音备注
- GET  /api/voice-training/{id}/journal-format: journal daily 模板文本
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from ielts_buddy.web import config as web_config
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.craft_rewrite_service import (
    VALID_STYLES,
    get_craft_rewrite_service,
)
from ielts_buddy.web.phonetics_service import get_phonetics_service
from ielts_buddy.web.voice_tts_service import (
    EDGE_VOICES,
    TTSServiceUnavailable,
    get_recordings_dir,
    get_voice_tts_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-training"])
api_router = APIRouter(prefix="/api/voice-training", tags=["voice-training-api"])


# =============================================================
# Helpers
# =============================================================


def _repo(request: Request):
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="业务容器未初始化")
    return container.voice_training


def _get_owned_record(request: Request, user: WebUser, record_id: int) -> dict:
    rec = _repo(request).get_record(int(user.id), record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return rec


# =============================================================
# Pydantic schemas
# =============================================================


class RewriteRequest(BaseModel):
    zh_text: str = Field(min_length=2, max_length=800)
    style: str = "natural"


class RewriteResponse(BaseModel):
    record_id: int
    en_text: Optional[str] = None
    word_count: int = 0
    dry_run: bool = False
    retryable: bool = False


class PhoneticsResponse(BaseModel):
    record_id: int
    words: list[dict]


class WordRuleResponse(BaseModel):
    word: str
    rule: str


class TTSRequest(BaseModel):
    voice: str = "en-US-AriaNeural"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class TTSResponse(BaseModel):
    record_id: int
    audio_url: str
    provider: str
    cached: bool


class RecordingResponse(BaseModel):
    record_id: int
    audio_url: str


class NotesRequest(BaseModel):
    notes: str = Field(default="", max_length=2000)


class RecordItem(BaseModel):
    id: int
    created_at: str
    source_zh: str
    rewritten_en: str
    style: str
    tts_voice: str
    notes: str
    has_tts: bool = False
    has_recording: bool = False
    has_ipa: bool = False


class RecordsResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[RecordItem]


class JournalFormatResponse(BaseModel):
    record_id: int
    markdown: str


# =============================================================
# 页面： GET /voice/training
# =============================================================


@router.get("/voice/training", response_class=HTMLResponse)
def page_voice_training(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return request.app.state.templates.TemplateResponse(
        request,
        "pages/voice_training.html",
        {
            "title": "语音训练",
            "phase": 11,
            "current_user": user,
            "request": request,
            "default_voice": web_config.VOICE_DEFAULT_VOICE,
            "max_recording_mb": web_config.VOICE_RECORDING_MAX_MB,
        },
    )


# =============================================================
# POST /api/voice-training/rewrite
# =============================================================


@api_router.post("/rewrite", response_model=RewriteResponse)
async def api_rewrite(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    body: RewriteRequest,
) -> RewriteResponse:
    """中文段落 → 创建记录 + LLM 改写。

    LLM 失败不阻塞：记录保留，返回 retryable=True 由前端引导重试。
    """
    if body.style not in VALID_STYLES:
        raise HTTPException(status_code=422, detail="style 必须是 natural/casual/formal")
    zh_text = body.zh_text.strip()
    repo = _repo(request)
    record_id = await asyncio.to_thread(
        repo.create_record,
        int(user.id), zh_text, body.style,
        tts_voice=web_config.VOICE_DEFAULT_VOICE,
    )
    svc = get_craft_rewrite_service()
    try:
        result = await asyncio.to_thread(svc.rewrite, zh_text, body.style)
    except Exception as exc:
        logger.warning("[voice-training] 改写失败(record %s): %s", record_id, exc)
        return RewriteResponse(record_id=record_id, retryable=True)
    if result.word_count > web_config.VOICE_TEXT_MAX_WORDS:
        await asyncio.to_thread(repo.attach_rewrite, int(user.id), record_id, result.en_text)
        raise HTTPException(
            status_code=422,
            detail=f"改写结果 {result.word_count} 词超出上限 {web_config.VOICE_TEXT_MAX_WORDS}，请缩短中文原文",
        )
    await asyncio.to_thread(repo.attach_rewrite, int(user.id), record_id, result.en_text)
    return RewriteResponse(
        record_id=record_id,
        en_text=result.en_text,
        word_count=result.word_count,
        dry_run=result.dry_run,
    )


# =============================================================
# POST /api/voice-training/{id}/retry
# =============================================================


@api_router.post("/{record_id}/retry", response_model=RewriteResponse)
async def api_retry_rewrite(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
) -> RewriteResponse:
    """对既有记录重新生成改写（temperature 0.7，每次不同）。"""
    rec = _get_owned_record(request, user, record_id)
    svc = get_craft_rewrite_service()
    try:
        result = await asyncio.to_thread(svc.rewrite, rec["source_zh"], rec["style"])
    except Exception as exc:
        logger.warning("[voice-training] 重写失败(record %s): %s", record_id, exc)
        return RewriteResponse(record_id=record_id, retryable=True)
    await asyncio.to_thread(_repo(request).attach_rewrite, int(user.id), record_id, result.en_text)
    return RewriteResponse(
        record_id=record_id,
        en_text=result.en_text,
        word_count=result.word_count,
        dry_run=result.dry_run,
    )


# =============================================================
# POST /api/voice-training/{id}/phonetics
# =============================================================


@api_router.post("/{record_id}/phonetics", response_model=PhoneticsResponse)
async def api_phonetics(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
) -> PhoneticsResponse:
    rec = _get_owned_record(request, user, record_id)
    en_text = (rec.get("rewritten_en") or "").strip()
    if not en_text:
        raise HTTPException(status_code=422, detail="尚无英文文本，请先完成改写")
    svc = get_phonetics_service()
    words = await asyncio.to_thread(svc.parse_text, en_text)
    import json as _json
    await asyncio.to_thread(
        _repo(request).attach_ipa, int(user.id), record_id,
        _json.dumps(words, ensure_ascii=False),
    )
    return PhoneticsResponse(record_id=record_id, words=words)


# =============================================================
# GET /api/voice-training/word-rule?word=xx
# =============================================================


@api_router.get("/word-rule", response_model=WordRuleResponse)
async def api_word_rule(
    user: Annotated[WebUser, Depends(get_current_user)],
    word: Annotated[str, Query(min_length=1, max_length=64)],
) -> WordRuleResponse:
    svc = get_phonetics_service()
    rule = await asyncio.to_thread(svc.word_rule, word)
    return WordRuleResponse(word=word, rule=rule)


# =============================================================
# POST /api/voice-training/{id}/tts
# =============================================================


@api_router.post("/{record_id}/tts", response_model=TTSResponse)
async def api_tts(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
    body: TTSRequest,
) -> TTSResponse:
    rec = _get_owned_record(request, user, record_id)
    en_text = (rec.get("rewritten_en") or "").strip()
    if not en_text:
        raise HTTPException(status_code=422, detail="尚无英文文本，请先完成改写")
    voice = body.voice if body.voice in EDGE_VOICES else web_config.VOICE_DEFAULT_VOICE
    svc = get_voice_tts_service()
    try:
        result = await svc.synthesize(en_text, voice, body.speed)
    except TTSServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # 落库相对路径（相对 ~/.ielts-buddy/voice/）
    rel = f"tts/{result.path.name}"
    await asyncio.to_thread(
        _repo(request).attach_tts, int(user.id), record_id, rel, voice
    )
    return TTSResponse(
        record_id=record_id,
        audio_url=f"/api/voice-training/{record_id}/audio/tts",
        provider=result.provider,
        cached=result.cached,
    )


# =============================================================
# POST /api/voice-training/{id}/recording
# =============================================================


@api_router.post("/{record_id}/recording", response_model=RecordingResponse)
async def api_upload_recording(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
    audio: Annotated[UploadFile, File()],
) -> RecordingResponse:
    _get_owned_record(request, user, record_id)  # 归属校验
    max_mb = web_config.VOICE_RECORDING_MAX_MB
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=422, detail="录音为空")
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=422, detail=f"录音超过 {max_mb}MB 上限")
    mime = (audio.content_type or "").lower()
    if mime and not any(s in mime for s in ("webm", "ogg", "mp4", "mpeg", "wav", "octet-stream")):
        raise HTTPException(status_code=422, detail=f"不支持的音频类型: {mime}")

    ext = ".webm"
    if "mp4" in mime:
        ext = ".mp4"
    elif "mpeg" in mime or "mp3" in mime:
        ext = ".mp3"
    elif "wav" in mime:
        ext = ".wav"
    out = get_recordings_dir() / f"{record_id}_{int(asyncio.get_event_loop().time())}{ext}"
    out.write_bytes(data)
    rel = f"recordings/{out.name}"
    await asyncio.to_thread(
        _repo(request).attach_recording, int(user.id), record_id, rel
    )
    return RecordingResponse(
        record_id=record_id,
        audio_url=f"/api/voice-training/{record_id}/audio/recording",
    )


# =============================================================
# GET /api/voice-training/{id}/audio/{kind}
# =============================================================


def _voice_root():
    from ielts_buddy.web.voice_tts_service import get_voice_root
    return get_voice_root()


def _safe_join(root, rel: str):
    """路径白名单校验，防目录穿越。"""
    if not re.fullmatch(r"(tts|recordings)/[A-Za-z0-9_.\-]+\.(mp3|webm|mp4|wav)", rel or ""):
        raise HTTPException(status_code=404, detail="文件不存在")
    p = root / rel
    if not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return p


def _mime_for(path) -> str:
    return {
        ".mp3": "audio/mpeg", ".webm": "audio/webm",
        ".mp4": "audio/mp4", ".wav": "audio/wav",
    }.get(path.suffix.lower(), "application/octet-stream")


@api_router.get("/{record_id}/audio/{kind}")
async def api_get_audio(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
    kind: str,
) -> FileResponse:
    if kind not in ("tts", "recording"):
        raise HTTPException(status_code=404, detail="音频类型不存在")
    rec = _get_owned_record(request, user, record_id)
    rel = rec.get("tts_path" if kind == "tts" else "recording_path")
    if not rel:
        raise HTTPException(status_code=404, detail="尚未生成该音频")
    path = _safe_join(_voice_root(), rel)
    return FileResponse(path, media_type=_mime_for(path))


# =============================================================
# GET /api/voice-training/records
# =============================================================


@api_router.get("/records", response_model=RecordsResponse)
async def api_records(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RecordsResponse:
    items, total = await asyncio.to_thread(
        _repo(request).list_records, int(user.id), page, size
    )
    out = [
        RecordItem(
            id=int(r["id"]),
            created_at=r.get("created_at") or "",
            source_zh=r.get("source_zh") or "",
            rewritten_en=r.get("rewritten_en") or "",
            style=r.get("style") or "natural",
            tts_voice=r.get("tts_voice") or "",
            notes=r.get("notes") or "",
            has_tts=bool(r.get("tts_path")),
            has_recording=bool(r.get("recording_path")),
            has_ipa=bool(r.get("ipa_json")),
        )
        for r in items
    ]
    return RecordsResponse(total=total, page=page, size=size, items=out)


# =============================================================
# GET /api/voice-training/{id}  （详情）
# =============================================================


@api_router.get("/{record_id}")
async def api_record_detail(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
) -> dict:
    rec = _get_owned_record(request, user, record_id)
    import json as _json
    rec = dict(rec)
    try:
        rec["ipa"] = _json.loads(rec.pop("ipa_json") or "[]")
    except Exception:
        rec["ipa"] = []
    rec["id"] = int(rec["id"])
    rec["tts_url"] = (
        f"/api/voice-training/{record_id}/audio/tts" if rec.get("tts_path") else None
    )
    rec["recording_url"] = (
        f"/api/voice-training/{record_id}/audio/recording"
        if rec.get("recording_path") else None
    )
    return rec


# =============================================================
# PATCH /api/voice-training/{id}  （纠音备注）
# =============================================================


@api_router.patch("/{record_id}")
async def api_update_notes(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
    body: NotesRequest,
) -> dict:
    _get_owned_record(request, user, record_id)
    ok = await asyncio.to_thread(
        _repo(request).update_notes, int(user.id), record_id, body.notes.strip()
    )
    return {"ok": bool(ok)}


# =============================================================
# GET /api/voice-training/{id}/journal-format
# =============================================================


@api_router.get("/{record_id}/journal-format", response_model=JournalFormatResponse)
async def api_journal_format(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    record_id: int,
) -> JournalFormatResponse:
    """拼装 journal daily 模板第 1/2 节文本，前端一键复制。"""
    rec = _get_owned_record(request, user, record_id)
    zh = (rec.get("source_zh") or "").strip()
    en = (rec.get("rewritten_en") or "").strip()
    lines = ["## 1. 今日感想（原文）", f"> {zh}", "", "## 2. English Translation (Craft 产出)", en]
    return JournalFormatResponse(record_id=record_id, markdown="\n".join(lines))
