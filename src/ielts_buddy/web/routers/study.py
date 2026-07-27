"""/study/random 和 /study/review 的页面路由 + HTMX 答题端点。

设计：
- 主页面 GET /study/{random,review} 返回整页（首次进入）
- HTMX 局部 POST /api/study/answer 接受用户答题结果，返回下一个题卡片段
- 全部走 ``app.state.web_stats_conn``（lifespan 阶段开，check_same_thread=False）
- 之所以不走 CLI 的 ReviewService：后者内部用 SQLiteRepositoryContainer，conn 没
  跨线程保护，FastAPI threadpool 模型下会爆 "SQLite objects created in a thread"
- 这里手写与 upsert_record / get_due_words 等价的 SQL，业务逻辑保持一致
  （艾宾浩斯 0-6 等级、next_review 间隔）
"""
from __future__ import annotations

import json
import random
import sqlite3
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
    get_stats_conn,
    get_vocab_service,
)


router = APIRouter(tags=["study"])


# 艾宾浩斯间隔（与 services/review_service.REVIEW_INTERVALS 对齐）
_REVIEW_INTERVALS = [0, 1, 2, 4, 7, 15, 30]


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


# =============================================================
# 内部：web 端的 SQL 操作（与 services/review_service 行为一致）
# =============================================================


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """确保 learning_records 表存在。lifespan 阶段已建，这里幂等保护。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS learning_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            word TEXT NOT NULL,
            word_data TEXT NOT NULL,
            memory_level INTEGER DEFAULT 0,
            next_review TEXT,
            learn_count INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0,
            first_learned TEXT,
            last_reviewed TEXT,
            is_starred INTEGER DEFAULT 0,
            is_difficult INTEGER DEFAULT 0,
            source TEXT DEFAULT 'builtin',
            UNIQUE (user_id, word)
        );
    """)
    conn.commit()


def _next_review_date(today_str: str, level: int) -> str:
    today = date.fromisoformat(today_str)
    interval = _REVIEW_INTERVALS[min(level, len(_REVIEW_INTERVALS) - 1)]
    return (today + timedelta(days=interval)).isoformat()


def _upsert_record(
    conn: sqlite3.Connection,
    user_id: int,
    word: Word,
    correct: bool,
    source: str = "web",
) -> None:
    """upsert 学习记录（与 SQLiteLearningRepository.upsert_record 行为一致）。"""
    _ensure_schema(conn)
    now = datetime.now().isoformat(timespec="seconds")
    today = date.today().isoformat()

    row = conn.execute(
        "SELECT memory_level FROM learning_records WHERE user_id = ? AND word = ?",
        (user_id, word.word),
    ).fetchone()

    if row is None:
        level = 1 if correct else 0
        next_review = _next_review_date(today, level)
        conn.execute(
            """INSERT INTO learning_records
               (user_id, word, word_data, memory_level, next_review,
                learn_count, correct_count, wrong_count,
                first_learned, last_reviewed, source)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
            (
                user_id, word.word, word.model_dump_json(), level, next_review,
                1 if correct else 0,
                0 if correct else 1,
                now, now, source,
            ),
        )
    else:
        level = row["memory_level"]
        if correct:
            level = min(level + 1, len(_REVIEW_INTERVALS) - 1)
        else:
            level = max(level - 1, 0)
        next_review = _next_review_date(today, level)
        conn.execute(
            """UPDATE learning_records SET
               memory_level = ?,
               next_review = ?,
               learn_count = learn_count + 1,
               correct_count = correct_count + ?,
               wrong_count = wrong_count + ?,
               last_reviewed = ?
               WHERE user_id = ? AND word = ?""",
            (
                level, next_review,
                1 if correct else 0,
                0 if correct else 1,
                now, user_id, word.word,
            ),
        )
    conn.commit()


def _due_count(conn: sqlite3.Connection, user_id: int) -> int:
    _ensure_schema(conn)
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM learning_records "
        "WHERE user_id = ? AND next_review <= ?",
        (user_id, today),
    ).fetchone()
    return row["c"]


def _pick_due_word(
    conn: sqlite3.Connection, user_id: int
) -> Optional[Word]:
    _ensure_schema(conn)
    today = date.today().isoformat()
    row = conn.execute(
        """SELECT * FROM learning_records
           WHERE user_id = ? AND next_review <= ?
           ORDER BY memory_level ASC, next_review ASC
           LIMIT 1""",
        (user_id, today),
    ).fetchone()
    if row is None:
        return None
    word_data = json.loads(row["word_data"])
    return Word(**word_data)


# =============================================================
# 内部：选题
# =============================================================


def _pick_new_word(
    vocab: VocabService,
    conn: sqlite3.Connection,
    user_id: int,
) -> Optional[Word]:
    """从词库随机抽一个 user 还没学过的词（band 5-9 随机）。"""
    _ensure_schema(conn)
    band = random.choice([5, 6, 7, 8, 9])
    pool = vocab.filter_by_band(band)
    if not pool:
        return None
    rows = conn.execute(
        "SELECT word FROM learning_records WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    learned = {r["word"] for r in rows}
    candidates = [w for w in pool if w.word not in learned]
    if not candidates:
        return None
    return random.choice(candidates)


# =============================================================
# 页面：随机学习
# =============================================================


@router.get("/study/random", response_class=HTMLResponse)
def page_study_random(
    request: Request,
    user: Annotated[WebUser | None, Depends(get_current_user_optional)],
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
    conn: Annotated[sqlite3.Connection, Depends(get_stats_conn)],
) -> HTMLResponse:
    """随机学习主页：选一题渲染。未登录跳 /login。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    word = _pick_new_word(vocab, conn, user.id)
    return _get_templates(request).TemplateResponse(
        request,
        "pages/study_random.html",
        {
            "title": "随机学习",
            "phase": 3,
            "current_user": user,
            "word": word,
            "mode": "random",
        },
    )


# =============================================================
# 页面：复习
# =============================================================


@router.get("/study/review", response_class=HTMLResponse)
def page_study_review(
    request: Request,
    user: Annotated[WebUser | None, Depends(get_current_user_optional)],
    conn: Annotated[sqlite3.Connection, Depends(get_stats_conn)],
) -> HTMLResponse:
    """复习主页：从待复习队列取一题。未登录跳 /login。"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    word = _pick_due_word(conn, user.id)
    due_remaining = _due_count(conn, user.id)
    return _get_templates(request).TemplateResponse(
        request,
        "pages/study_review.html",
        {
            "title": "复习",
            "phase": 3,
            "current_user": user,
            "word": word,
            "mode": "review",
            "due_remaining": due_remaining,
        },
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
    conn: Annotated[sqlite3.Connection, Depends(get_stats_conn)],
) -> HTMLResponse:
    """记录一次答题结果并返回下一题的卡片片段。"""
    w = vocab.get_word(word)
    if w is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"词库中找不到单词 '{word}'",
        )

    # 写学习记录
    _upsert_record(conn, user.id, w, correct=correct, source="web")

    # 选下一题
    if mode == "random":
        next_word = _pick_new_word(vocab, conn, user.id)
        ctx_due = None
        empty_msg = "今日新词已学完 ✅ 休息一下，明天继续。" if next_word is None else None
    elif mode == "review":
        next_word = _pick_due_word(conn, user.id)
        ctx_due = _due_count(conn, user.id)
        empty_msg = "今日复习已完成 🎉" if next_word is None else None
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未知 mode: {mode}",
        )

    # 返回完整卡片组件（包含 #study-card 容器）
    return _get_templates(request).TemplateResponse(
        request,
        "partials/_study_card.html",
        {
            "word": next_word,
            "mode": mode,
            "due_remaining": ctx_due,
            "empty_msg": empty_msg,
        },
    )


__all__ = ["router"]
