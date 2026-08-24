"""小程序 W3 写作批改路由（v3.9+ / 2026-08-24）。

端点（统一前缀 /api/wx/grade）：
- POST /submit      提交作文，走 LLM
- GET  /history     历史批改
- GET  /stats       简单统计

设计：完全复用 Web 端 grade.py 的 _call_llm_grader + _grade_result_to_mock_shape。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from pydantic import BaseModel

from ielts_buddy.core.models import GradeResult
from ielts_buddy.services.grading_service import GradingService
from ielts_buddy.web.auth.deps import get_current_user
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.routers.grade import (
    _call_llm_grader,
    _grade_result_to_mock_shape,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wx/grade", tags=["wx-grade"])


# =============================================================
# Pydantic Schemas
# =============================================================


class WxGradeSubmitResponse(BaseModel):
    success: bool
    result: dict
    source: str  # "llm" 或 "mock"
    error_msg: Optional[str] = None


class WxGradeHistoryItem(BaseModel):
    record_id: int
    overall_score: float
    task_type: str
    topic: str
    word_count: int
    graded_at: str


class WxGradeHistoryResponse(BaseModel):
    total: int
    items: list[WxGradeHistoryItem]


# =============================================================
# POST /api/wx/grade/submit
# =============================================================


@router.post("/submit", response_model=WxGradeSubmitResponse)
async def wx_grade_submit(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    essay: Annotated[str, Form(min_length=50, max_length=10000)],
    task_type: Annotated[str, Form()] = "task2",
    topic: Annotated[Optional[str], Form()] = None,
) -> WxGradeSubmitResponse:
    """提交作文走 LLM（沿用 Web 端 grade.py 完整链路）。"""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    task_type_clean = task_type if task_type in ("task1", "task2") else "task2"

    source = "llm"
    error_msg: Optional[str] = None
    result_dict: Optional[dict] = None
    grade_obj: Optional[GradeResult] = None

    try:
        grade_obj = await asyncio.wait_for(
            _call_llm_grader(container, int(user.id), essay, topic, task_type_clean),
            timeout=110.0,
        )
        result_dict = _grade_result_to_mock_shape(grade_obj)
    except asyncio.TimeoutError:
        source = "mock"
        error_msg = "LLM 超时，已降级为本地估算"
        # 调用 Web 端 mock 函数（需要从 grade.py 导入）
        from ielts_buddy.web.routers.grade import _mock_grade_essay
        result_dict = _mock_grade_essay(essay, task_type_clean, topic)
    except Exception as e:
        source = "mock"
        error_msg = f"LLM 不可用：{e}"
        logger.warning(f"[wx-grade] LLM unavailable for user={user.id}: {e}")
        from ielts_buddy.web.routers.grade import _mock_grade_essay
        result_dict = _mock_grade_essay(essay, task_type_clean, topic)

    # 保存批改记录（沿用 Web 端逻辑简化版）
    try:
        from ielts_buddy.core.models import GradeDimension
        if grade_obj is not None:
            save_obj = GradeResult(
                overall_score=grade_obj.overall_score,
                task_response=grade_obj.task_response,
                coherence=grade_obj.coherence,
                lexical_resource=grade_obj.lexical_resource,
                grammar=grade_obj.grammar,
                suggestions=grade_obj.suggestions,
                rewrite=grade_obj.rewrite,
                essay_text=essay,
                topic=topic or "",
                task_type=task_type_clean,
                annotations=grade_obj.annotations,
                paragraphs=grade_obj.paragraphs,
                error_summary=grade_obj.error_summary,
                graded_at=grade_obj.graded_at,
            )
        else:
            save_obj = GradeResult(
                overall_score=float(result_dict["overall_score"]),
                task_response=GradeDimension(
                    score=float(result_dict["band_scores"]["task_response"]),
                    comment="(mock)",
                ),
                coherence=GradeDimension(
                    score=float(result_dict["band_scores"]["coherence"]),
                    comment="(mock)",
                ),
                lexical_resource=GradeDimension(
                    score=float(result_dict["band_scores"]["lexical_resource"]),
                    comment="(mock)",
                ),
                grammar=GradeDimension(
                    score=float(result_dict["band_scores"]["grammar"]),
                    comment="(mock)",
                ),
                suggestions=[],
                rewrite="",
                essay_text=essay,
                topic=topic or "",
                task_type=task_type_clean,
                graded_at=datetime.now().isoformat(timespec="seconds"),
            )
        container.grade.save_result(int(user.id), save_obj)
    except Exception as e:
        # 保存失败不影响返回
        logger.warning(f"[wx-grade] save_result failed: {e}")

    return WxGradeSubmitResponse(
        success=True,
        result=result_dict,
        source=source,
        error_msg=error_msg,
    )


# =============================================================
# GET /api/wx/grade/history
# =============================================================


@router.get("/history", response_model=WxGradeHistoryResponse)
async def wx_grade_history(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> WxGradeHistoryResponse:
    """批改历史。"""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    rows = container.grade.list_results(user_id=int(user.id), limit=limit)

    items: list[WxGradeHistoryItem] = []
    for r in rows:
        # 解析 llm_scores JSON 拿 word_count
        try:
            scores_json = r.get("llm_scores") if isinstance(r, dict) else None
            if scores_json:
                scores = json.loads(scores_json) if isinstance(scores_json, str) else scores_json
                wc = scores.get("word_count", 0)
            else:
                wc = 0
        except Exception:
            wc = 0
        items.append(WxGradeHistoryItem(
            record_id=int(r["id"]) if "id" in r else 0,
            overall_score=float(r.get("overall_score") or 0),
            task_type=str(r.get("task_type") or "task2"),
            topic=str(r.get("topic") or ""),
            word_count=int(wc),
            graded_at=str(r.get("graded_at") or ""),
        ))
    return WxGradeHistoryResponse(total=len(items), items=items)


# =============================================================
# GET /api/wx/grade/stats
# =============================================================


@router.get("/stats")
async def wx_grade_stats(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> dict:
    """简单统计：总数 + 平均分。"""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    rows = container.grade.list_results(user_id=int(user.id), limit=200)
    total = len(rows)
    if total == 0:
        return {"total": 0, "avg_score": 0.0, "best_score": 0.0, "latest_task_type": ""}
    scores = [float(r.get("overall_score") or 0) for r in rows]
    avg = sum(scores) / total
    return {
        "total": total,
        "avg_score": round(avg, 2),
        "best_score": max(scores),
        "latest_task_type": str(rows[0].get("task_type") or "task2"),
    }


__all__ = ["router"]