"""/grade AI 批改路由。

功能：
- GET /grade: AI 批改页面
- POST /api/grade: 提交作文进行批改
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser


router = APIRouter(tags=["grade"])
api_router = APIRouter(prefix="/api/grade", tags=["grade-api"])


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _get_container(request: Request):
    from ielts_buddy.web.main import app
    return getattr(app.state, "container", None)


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
def api_grade_submit(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    essay: Annotated[str, Form(min_length=50)],
    task_type: Annotated[str, Form()] = "task2",
    topic: Annotated[Optional[str], Form()] = None,
) -> dict:
    """提交作文进行 AI 批改"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        # 模拟 AI 批改（实际项目中应调用 LLM API）
        result = _mock_grade_essay(essay, task_type, topic)

        # 保存批改记录（最佳努力，失败不影响返回）
        try:
            from ielts_buddy.core.models import GradeResult
            grade_result = GradeResult(
                overall_score=result["overall_score"],
                task_type=task_type,
                topic=topic or "",
                essay_text=essay,
                result_json=result,
            )
            container.grade.save_result(user.id, grade_result)
        except Exception as save_err:
            print(f"[grade] 保存记录失败 (non-fatal): {save_err}")

        return {
            "success": True,
            "result": result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _mock_grade_essay(essay: str, task_type: str, topic: Optional[str]) -> dict:
    """模拟 AI 批改（实际项目中应调用 LLM API）

    返回格式与 PRD 中定义的批改结果一致
    """
    # 简单的模拟评分逻辑
    word_count = len(essay.split())
    avg_score = 6.0

    # 根据字数调整
    if word_count < 150:
        avg_score -= 0.5
    elif word_count > 280:
        avg_score += 0.5

    # 添加随机波动
    import random
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
        "suggestions": [
            "扩展词汇多样性，使用更多高级表达",
            "注意句子结构的丰富性，混合使用简单句和复杂句",
            "加强段落之间的逻辑衔接",
        ],
        "word_count": word_count,
        "graded_at": "2026-07-27",
    }


__all__ = ["router", "api_router"]
