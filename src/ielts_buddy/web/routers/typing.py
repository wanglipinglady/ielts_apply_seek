"""/typing 机考打字练习路由。

功能：
- GET  /typing                : 机考打字练习页面
- GET  /api/typing/material   : 拉随机素材（按 mode + 可选 band）
- POST /api/typing/submit     : 提交一次练习的 typed_text + 耗时
- GET  /api/typing/history    : 个人历史
- GET  /api/typing/stats      : 个人聚合（总数 / 平均 wpm / 平均 accuracy / 最高 wpm）

数据源：
- words     : VocabService.random_words(count, band) → 抽单词，空格分隔
- sentences : VocabService.filter_by_band(band).random.choice(过 example 字段)
              ；若 example 为空则用单词本体造一个简单句（仅本地素材，避免 LLM）
- passage   : 内置 8 篇雅思泛读短文（``DEFAULT_PASSAGES``），随机抽 1
"""
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ielts_buddy.core.models import TypingRecord
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.services import get_vocab_service
from ielts_buddy.services.vocab_service import VocabService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["typing"])
api_router = APIRouter(prefix="/api/typing", tags=["typing-api"])


VALID_MODES = ("words", "sentences", "passage")


# =============================================================
# 内置短文素材（无外部依赖，做 passage 模式兜底）
# 这些都是常见 IELTS 泛读选段的长难句风格短文片段，方便跟打练习
# =============================================================

DEFAULT_PASSAGES = [
    (
        "Education for sustainable development",
        "Modern education systems are increasingly incorporating "
        "sustainable development goals into their curricula. "
        "Schools around the world are teaching students about "
        "environmental responsibility, social equity and economic "
        "viability. By fostering critical thinking and practical "
        "skills, educators prepare young people to address the "
        "complex challenges of the twenty first century. "
        "This holistic approach ensures that tomorrow's leaders "
        "are equipped to create a more balanced and resilient society."
    ),
    (
        "The rise of remote work",
        "The global shift towards remote work has transformed "
        "the traditional office environment in profound ways. "
        "Companies have discovered that flexible arrangements can "
        "boost productivity while reducing operational costs. "
        "Workers, in turn, enjoy greater autonomy and improved "
        "work life balance, although they must also navigate the "
        "challenges of isolation and blurred boundaries between "
        "professional and personal time."
    ),
    (
        "Urban green spaces",
        "City planners are recognizing the vital importance of "
        "green spaces in densely populated urban areas. "
        "Parks, community gardens and tree lined streets not only "
        "enhance the aesthetic appeal of a neighbourhood but also "
        "contribute significantly to public health. "
        "Research has shown that regular exposure to nature can "
        "reduce stress, improve concentration and foster stronger "
        "social connections among residents."
    ),
    (
        "The impact of social media on communication",
        "Social media platforms have fundamentally altered how "
        "individuals interact and share information. "
        "While these tools offer unprecedented opportunities for "
        "connection, they also raise concerns about privacy, "
        "misinformation and the erosion of face to face conversation. "
        "As digital natives become the majority, societies must "
        "develop new frameworks that balance convenience with "
        "the preservation of meaningful dialogue."
    ),
    (
        "Climate adaptation strategies",
        "Coastal communities around the world are implementing "
        "innovative adaptation strategies in response to rising "
        "sea levels and increasingly severe weather events. "
        "These range from restoring mangrove forests that act as "
        "natural barriers to constructing elevated walkways and "
        "improving early warning systems. "
        "Such measures demonstrate that proactive planning can "
        "significantly reduce the human and economic costs of "
        "climate related disasters."
    ),
    (
        "The future of public transportation",
        "Many cities are reimagining their public transportation "
        "networks to meet the demands of the twenty first century. "
        "Electric buses, dedicated bike lanes and integrated mobile "
        "ticketing systems are becoming standard features of "
        "forward thinking urban centres. "
        "By prioritizing accessibility and environmental "
        "sustainability, these initiatives aim to make daily "
        "commuting both efficient and enjoyable for everyone."
    ),
    (
        "Lifelong learning in the digital age",
        "The concept of lifelong learning has gained considerable "
        "traction as technological change accelerates. "
        "Online platforms offer flexible courses that allow "
        "professionals to acquire new skills without interrupting "
        "their careers. "
        "This democratization of education empowers individuals "
        "to remain competitive in evolving job markets while "
        "fostering a culture of curiosity and continuous self "
        "improvement."
    ),
    (
        "Biodiversity and human wellbeing",
        "The intricate relationship between biodiversity and "
        "human wellbeing is becoming increasingly clear to "
        "scientists and policymakers alike. "
        "Diverse ecosystems provide essential services such as "
        "pollination, water purification and climate regulation. "
        "Protecting natural habitats is therefore not merely an "
        "environmental concern but a fundamental investment in "
        "the health and prosperity of present and future generations."
    ),
]


# =============================================================
# 辅助函数
# =============================================================


def _get_container(request: Request):
    return getattr(request.app.state, "container", None)


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _normalize_mode(mode: str) -> str:
    return mode if mode in VALID_MODES else "words"


def _compute_typing_metrics(
    prompt: str, typed: str, duration_sec: int
) -> dict[str, Any]:
    """服务端复核 WPM / accuracy / errors。

    与前端算法保持一致：每 5 个字符计 1 词；accuracy = correct_chars / total_chars；
    error_count = typed 与 prompt 位置对齐后不一致位置数（截断时不补 padding）。
    WPM 仅按正确字符计算（避免乱打拉高）。
    """
    # 计算 WPM: words typed in one minute → 标准 5 字符 = 1 词
    correct_chars = 0
    total_chars = max(len(prompt), 1)
    min_len = min(len(prompt), len(typed))
    for i in range(min_len):
        if prompt[i] == typed[i]:
            correct_chars += 1
    # accuracy 用 prompt 总长作分母，避免 typed 远超 prompt 时负数
    accuracy = correct_chars / total_chars if total_chars > 0 else 0.0
    errors = max(0, total_chars - correct_chars)
    wpm = (correct_chars / 5.0) / (duration_sec / 60.0) if duration_sec > 0 else 0.0
    return {
        "wpm": round(max(wpm, 0.0), 2),
        "accuracy": round(min(max(accuracy, 0.0), 1.0), 4),
        "error_count": int(errors),
        "total_chars": total_chars,
    }


def _pick_words_material(
    vocab: VocabService, count: int, band: Optional[int]
) -> str:
    words = vocab.random_words(count=count, band=band)
    # 缺单词时回退：抽任何 band 的单词填空
    if len(words) < count:
        more = vocab.random_words(count=count - len(words))
        words = list(words) + more
    return " ".join(w.word for w in words[:count])


def _pick_sentence_material(
    vocab: VocabService, count: int, band: Optional[int]
) -> str:
    pool = vocab.filter_by_band(band) if band else vocab.words()
    # 优先用 Word.example，对空 example 用 word 自身
    items = [w.example.strip() or w.word for w in pool if w.example or w.word]
    random.shuffle(items)
    return " ".join(items[:count])


def _pick_passage_material() -> str:
    return random.choice(DEFAULT_PASSAGES)[1]


# =============================================================
# 页面路由
# =============================================================


@router.get("/typing", response_class=HTMLResponse)
def page_typing(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """机考打字练习页面"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/typing.html",
        {
            "title": "机考打字",
            "phase": 6,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


class MaterialResponse(BaseModel):
    mode: str
    text: str
    total_chars: int
    word_count: int


@api_router.get("/material", response_model=MaterialResponse)
def api_typing_material(
    mode: Annotated[str, Query()] = "words",
    band: Annotated[Optional[int], Query(ge=5, le=9)] = None,
    count: Annotated[Optional[int], Query(ge=1, le=200)] = None,
    vocab: VocabService = Depends(get_vocab_service),
) -> MaterialResponse:
    """返回一段随机素材（前端 Start 时拉一次）。"""
    mode_n = _normalize_mode(mode)

    if mode_n == "words":
        cnt = count or 20
        text = _pick_words_material(vocab, cnt, band)
    elif mode_n == "sentences":
        cnt = count or 5
        text = _pick_sentence_material(vocab, cnt, band)
    else:
        text = _pick_passage_material()

    return MaterialResponse(
        mode=mode_n,
        text=text,
        total_chars=len(text),
        word_count=len(text.split()),
    )


@api_router.post("/submit")
def api_typing_submit(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    prompt_text: Annotated[str, Form(min_length=1, max_length=5000)],
    duration_sec: Annotated[int, Form(ge=1, le=3600)],
    mode: Annotated[str, Form()] = "words",
    typed_text: Annotated[str, Form(max_length=5000)] = "",
    completed: Annotated[bool, Form()] = True,
) -> dict[str, Any]:
    """提交一次机考打字练习的结果，服务端会复核指标并入库。"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    mode_n = _normalize_mode(mode)

    # 服务端复核（与前端一致）—— 防止前端算错
    metrics = _compute_typing_metrics(prompt_text, typed_text, duration_sec)

    record = TypingRecord(
        user_id=int(user.id),
        mode=mode_n,
        prompt_text=prompt_text,
        typed_text=typed_text,
        duration_sec=duration_sec,
        wpm=metrics["wpm"],
        accuracy=metrics["accuracy"],
        error_count=metrics["error_count"],
        total_chars=metrics["total_chars"],
        completed=completed,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )

    try:
        rid = container.typing.save_record(int(user.id), record)
    except Exception as e:
        logger.exception(f"[typing] save_record failed: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")

    return {
        "success": True,
        "id": rid,
        "server_metrics": metrics,
        "record": record.model_dump(),
    }


# ----------- 历史 ----------


class TypingHistoryItem(BaseModel):
    id: int
    mode: str
    duration_sec: int
    wpm: float
    accuracy: float
    error_count: int
    total_chars: int
    completed: bool
    created_at: str


@api_router.get("/history", response_model=list[TypingHistoryItem])
def api_typing_history(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    mode: Annotated[Optional[str], Query()] = None,
) -> list[TypingHistoryItem]:
    """按 user_id 隔离的历史记录。"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    mode_n = mode if mode and mode in VALID_MODES else None
    records = container.typing.get_history(int(user.id), limit, mode_n)
    items: list[TypingHistoryItem] = []
    for r in records:
        items.append(TypingHistoryItem(
            id=int(r.id) if getattr(r, "id", None) else 0,
            mode=r.mode,
            duration_sec=r.duration_sec,
            wpm=float(r.wpm),
            accuracy=float(r.accuracy),
            error_count=r.error_count,
            total_chars=r.total_chars,
            completed=r.completed,
            created_at=r.created_at or "",
        ))
    return items


@api_router.get("/stats")
def api_typing_stats(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    mode: Annotated[Optional[str], Query()] = None,
) -> dict[str, Any]:
    """聚合统计（总数 / 平均 wpm / 平均 accuracy / 最高 wpm）。"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    mode_n = mode if mode and mode in VALID_MODES else None
    try:
        records = container.typing.get_history(int(user.id), limit=1000, mode=mode_n)
        total = len(records)
        avg_wpm = (
            sum(r.wpm for r in records) / total
            if total > 0 else 0.0
        )
        avg_acc = (
            sum(r.accuracy for r in records) / total
            if total > 0 else 0.0
        )
        max_wpm = max((r.wpm for r in records), default=0.0)
        return {
            "total_count": total,
            "average_wpm": round(float(avg_wpm), 2),
            "average_accuracy": round(float(avg_acc), 4),
            "max_wpm": round(float(max_wpm), 2),
            "mode": mode_n,
        }
    except Exception as e:
        logger.warning(f"[typing.stats] 聚合失败: {e}")
        return {
            "total_count": 0,
            "average_wpm": 0.0,
            "average_accuracy": 0.0,
            "max_wpm": 0.0,
            "error": str(e),
        }


__all__ = ["router", "api_router"]
