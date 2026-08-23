"""/grade AI 批改路由。

功能：
- GET  /grade                : AI 批改页面
- POST /api/grade/submit      : 提交作文，走真实 LLM（CLI 的 GradingService）
- GET  /api/grade/history     : 历史批改记录（按 user 隔离）
- GET  /api/grade/stats       : 简单统计（总数 / 平均分）

实现要点：
- Web 端复用 CLI 的 ``ielts_buddy.services.grading_service.GradingService``,
  避免在 web 侧再实现一份 LLM 调用逻辑(保持单一事实来源)。
- LLM 调用同步阻塞,必须用 ``asyncio.to_thread`` 放进线程池,不阻塞 FastAPI 事件循环。
- 失败时 degrade 到旧的 mock 实现,保证前端永远有可用反馈,避免用户面对冷冰冰的 500。
- 所有结果通过 ``container.grade.save_result`` 入库(user_id 用当前 web 用户的 id),
  与 CLI ``ib grade file`` 共享同一份 grade_history 表。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ielts_buddy.core.models import GradeResult
from ielts_buddy.services.grading_service import GradingService, VALID_TASK_TYPES
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["grade"])
api_router = APIRouter(prefix="/api/grade", tags=["grade-api"])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _get_container(request: Request):
    return getattr(request.app.state, "container", None)


# =============================================================
# 辅助函数
# =============================================================


def _validate_task_type(task_type: str) -> str:
    """校验/规范化 task_type。无效值降级到 task2。"""
    return task_type if task_type in VALID_TASK_TYPES else "task2"


def _grade_result_to_mock_shape(result: GradeResult) -> dict:
    """把 LLM 返回的 GradeResult 转成前端已有的 mock-style JSON。

    前端 (grade.html) 期望的结构：
    - overall_score: float
    - task_type / topic / graded_at
    - band_scores: {task_response, coherence, lexical_resource, grammar} —— float
    - error_summary: {grammar: [samples], vocabulary: [...], coherence: [...]} —— list
    - suggestions: [str, ...]
    - word_count: int
    - annotations: [...] （附带展示，每条带 issue_type / severity / original / suggestion）
    - paragraphs: [...]（段落结构分析）

    LLM 返回的真实 schema：
    - overall_score: float
    - task_response / coherence / lexical_resource / grammar: {score, comment}
    - annotations: [SentenceAnnotation] —— 每条 issue_type / original / comment / suggestion
    - paragraphs: [ParagraphAnalysis] —— 段落分析
    - error_summary: dict[str, int] —— {"grammar": 3, "vocabulary": 2} 计数
    - suggestions / rewrite / task_type / topic / graded_at
    """
    word_count = len(result.essay_text.split()) if result.essay_text else 0

    # 错误样本列表：从 annotations 聚合，按 issue_type 分组
    error_samples: dict[str, list[str]] = {}
    for ann in result.annotations:
        # 优先 suggestion，回退到 comment
        samples = error_samples.setdefault(ann.issue_type, [])
        msg = ann.suggestion or ann.comment
        if msg and len(samples) < 10:    # 每类最多 10 条，避免前端渲染爆炸
            samples.append(msg)

    return {
        "overall_score": float(result.overall_score),
        "task_type": result.task_type,
        "topic": result.topic or "",
        "word_count": word_count,
        "band_scores": {
            "task_response": float(result.task_response.score),
            "coherence": float(result.coherence.score),
            "lexical_resource": float(result.lexical_resource.score),
            "grammar": float(result.grammar.score),
        },
        # "error_summary" 前端渲染两条路径：
        # - 老 mock: list of strings（已弃用mock 里就是 strings）
        # - 真实 LLM: 给 list[str]，从 annotations 聚合
        "error_summary": error_samples,
        # 提供更结构化的 statistics 给前端可选展示
        "error_stats": result.error_summary,
        "suggestions": list(result.suggestions),
        "rewrite": result.rewrite,
        "annotations": [a.model_dump() for a in result.annotations],
        "paragraphs": [p.model_dump() for p in result.paragraphs],
        "graded_at": result.graded_at or datetime.now().isoformat(timespec="seconds"),
    }


def _mock_grade_essay(
    essay: str, task_type: str, topic: Optional[str]
) -> dict[str, Any]:
    """LLM 调用失败时的本地 mock 兜底（保证前端永远有可用响应）。

    与原实现一致：随机波动 5.0-9.0 之内的"看起来合理"的分数。
    """
    import random

    word_count = len(essay.split())
    avg_score = 6.0
    if word_count < 150:
        avg_score -= 0.5
    elif word_count > 280:
        avg_score += 0.5

    overall = round(avg_score + random.uniform(-0.5, 0.5), 1)
    overall = max(5.0, min(9.0, overall))

    return {
        "overall_score": overall,
        "task_type": task_type,
        "topic": topic or "未指定话题",
        "band_scores": {
            "task_response": round(overall + random.uniform(-0.5, 0.5), 1),
            "coherence": round(overall + random.uniform(-0.5, 0.5), 1),
            "lexical_resource": round(overall + random.uniform(-0.5, 0.5), 1),
            "grammar": round(overall + random.uniform(-0.5, 0.5), 1),
        },
        "error_summary": {
            "grammar": ["there is → there are (主谓一致)", "more better → better (比较级错误)"],
            "vocabulary": ["important → crucial/vital", "people → individuals/citizens"],
            "coherence": ["建议使用更多衔接词：Furthermore, Moreover, In addition"],
        },
        "error_stats": {"grammar": 2, "vocabulary": 2, "coherence": 1},
        "suggestions": [
            "扩展词汇多样性，使用更多高级表达",
            "注意句子结构的丰富性，混合使用简单句和复杂句",
            "加强段落之间的逻辑衔接",
        ],
        "rewrite": "",
        "annotations": [],
        "paragraphs": [],
        "word_count": word_count,
        "graded_at": datetime.now().isoformat(timespec="seconds"),
    }


async def _call_llm_grader(
    container, user_id: int, essay: str, topic: Optional[str], task_type: str
) -> GradeResult:
    """在线程池里跑 CLI 的 GradingService.grade_essay()，不阻塞事件循环。

    线程内 GradingService 内部走 ``docs/grok.py`` subprocess,120s 超时。
    container 必须是 v3 的 FallbackContainer / 直接是 GradeRepository 的容器都行,
    GradingService 会从 cfg 选 mode;这里显式喂 user_id 避免多用户串扰。
    """
    def _blocking_call() -> GradeResult:
        # 借壳方式构造 GradingService,复用当前线程的 container 与当前 web 用户
        # 等价于 CLI 的 ``GradingService(user_id=user_id)``
        svc = GradingService.__new__(GradingService)
        svc._container = container
        svc._repo = container.grade
        svc._user_id = user_id
        svc._db_path = None
        return svc.grade_essay(essay, topic=topic, task_type=task_type)

    return await asyncio.to_thread(_blocking_call)


# =============================================================
# 页面路由
# =============================================================


@router.get("/grade", response_class=HTMLResponse)
def page_grade(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """AI 批改页面"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    return _get_templates(request).TemplateResponse(
        request,
        "pages/grade.html",
        {
            "title": "AI 批改",
            "phase": 4,
            "current_user": user,
            "request": request,
        },
    )


# =============================================================
# API 路由
# =============================================================


@api_router.post("/submit")
async def api_grade_submit(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    essay: Annotated[str, Form(min_length=50, max_length=10000)],
    task_type: Annotated[str, Form()] = "task2",
    topic: Annotated[Optional[str], Form()] = None,
) -> dict:
    """提交作文进行 AI 批改。

    流程：
    1. 尝试调用 CLI 的 ``GradingService``（线程池） → 真实 LLM
    2. 失败（timeout / API key 缺失 / JSON 解析错误）→ degrade 到本地 mock
    3. 不论哪种情况都通过 ``container.grade.save_result`` 入库
    4. 返回 ``{"success": True, "result": {...}, "_meta": {"source": "llm"|"mock"}}``
    """
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    task_type_clean = _validate_task_type(task_type)
    word_count = len(essay.split())

    source = "llm"
    error_msg: Optional[str] = None
    result_dict: Optional[dict] = None
    grade_result_obj: Optional[GradeResult] = None

    try:
        grade_result_obj = await asyncio.wait_for(
            _call_llm_grader(container, int(user.id), essay, topic, task_type_clean),
            timeout=110.0,    # 略小于 subprocess 120s
        )
        result_dict = _grade_result_to_mock_shape(grade_result_obj)
    except asyncio.TimeoutError:
        source = "mock"
        error_msg = "LLM 调用超时（>110s），已自动降级为本地估算"
        logger.warning(f"[grade] LLM timeout for user={user.id}, degrade to mock")
        result_dict = _mock_grade_essay(essay, task_type_clean, topic)
    except RuntimeError as e:
        # GradingService 抛 RuntimeError 一般是 LLM 调用 / JSON 解析失败
        source = "mock"
        error_msg = f"LLM 不可用：{e}"
        logger.warning(f"[grade] LLM unavailable for user={user.id}: {e}")
        result_dict = _mock_grade_essay(essay, task_type_clean, topic)
    except Exception as e:
        # 兜底：任何意外都不应该阻塞前端
        source = "mock"
        error_msg = f"批改失败：{e}"
        logger.exception(f"[grade] unexpected error for user={user.id}")
        result_dict = _mock_grade_essay(essay, task_type_clean, topic)

    # 保存批改记录（最佳努力，失败不影响返回）
    try:
        from ielts_buddy.core.models import GradeDimension

        if grade_result_obj is not None:
            # LLM 路径：用真实结果构造保存对象
            save_obj = GradeResult(
                overall_score=grade_result_obj.overall_score,
                task_response=grade_result_obj.task_response,
                coherence=grade_result_obj.coherence,
                lexical_resource=grade_result_obj.lexical_resource,
                grammar=grade_result_obj.grammar,
                suggestions=grade_result_obj.suggestions,
                rewrite=grade_result_obj.rewrite,
                essay_text=essay,
                topic=topic or "",
                task_type=task_type_clean,
                annotations=grade_result_obj.annotations,
                paragraphs=grade_result_obj.paragraphs,
                error_summary=grade_result_obj.error_summary,
                graded_at=grade_result_obj.graded_at,
            )
        else:
            # Mock 路径：构造最小可用对象入库（note: 标 source=mock 方便排查）
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
                suggestions=result_dict.get("suggestions", []),
                rewrite=result_dict.get("rewrite", ""),
                essay_text=essay,
                topic=topic or "",
                task_type=task_type_clean,
                annotations=[],
                paragraphs=[],
                error_summary={k: len(v) for k, v in result_dict.get("error_summary", {}).items() if isinstance(v, list)},
                graded_at=result_dict.get("graded_at"),
            )
        container.grade.save_result(int(user.id), save_obj)
    except Exception as save_err:
        logger.warning(f"[grade] save_result failed (non-fatal): {save_err}")

    # 矫正 word_count 到结果里（mock 路径里 word_count 已含；LLM 路径里也再覆盖）
    result_dict["word_count"] = word_count

    return {
        "success": True,
        "result": result_dict,
        "_meta": {
            "source": source,            # "llm" | "mock"
            "user_id": user.id,
            "task_type": task_type_clean,
            "error": error_msg,          # 仅降级时有值
        },
    }


# ----------- 历史 ----------


class GradeHistoryItem(BaseModel):
    id: int
    overall_score: float
    task_type: str
    topic: str
    graded_at: str
    error_count: dict[str, int]


@api_router.get("/history", response_model=list[GradeHistoryItem])
def api_grade_history(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    task_type: Annotated[Optional[str], Query()] = None,
) -> list[GradeHistoryItem]:
    """历史批改记录（按 user_id 隔离）。"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        records = container.grade.get_history(int(user.id), limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取历史失败: {e}")

    items: list[GradeHistoryItem] = []
    for r in records:
        if task_type and r.task_type != task_type:
            continue
        items.append(GradeHistoryItem(
            id=int(r.id) if hasattr(r, "id") and r.id is not None else 0,
            overall_score=float(r.overall_score),
            task_type=r.task_type,
            topic=r.topic,
            graded_at=r.graded_at or "",
            error_count=dict(r.error_summary) if r.error_summary else {},
        ))
    return items


@api_router.get("/stats")
def api_grade_stats(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """聚合统计（数量 / 平均分）。

    走 ``container.grade.get_average_score(user_id)`` repo 方法,再加一次
    ``container.grade.get_history(user_id, 1)`` 探测空数据,避免在 FallbackContainer
    上踩到 ``svc._conn`` 属性不存在的问题（CLI service 写法要求 SQLite 直连）。
    """
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        # 平均分（Repository 已经处理好）
        avg = container.grade.get_average_score(int(user.id))
        # 总数:history 取 1000 条然后 len；够用且兼容 SQLite/MySQL/Fallback
        # （CLI 显示的也是 ``get_history(limit=...)`` + len）
        records = container.grade.get_history(int(user.id), limit=1000)
        total = len(records)
        return {
            "total_count": total,
            "average_score": round(float(avg or 0.0), 2),
        }
    except Exception as e:
        # 容错返回 0（首次访问等无数据场景）
        logger.warning(f"[grade.stats] 聚合统计失败: {e}")
        return {"total_count": 0, "average_score": 0.0, "error": str(e)}


__all__ = ["router", "api_router"]
