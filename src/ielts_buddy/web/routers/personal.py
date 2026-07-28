"""/personal 个人词库路由。

功能：
- GET /personal: 个人词库页面
- GET /api/personal/words: 获取单词列表
- POST /api/personal/words: 添加单词
- PUT /api/personal/words/{word}: 编辑单词
- DELETE /api/personal/words/{word}: 删除单词
- GET /api/personal/categories: 获取分类列表
- POST /api/personal/categories: 创建分类
- DELETE /api/personal/categories/{name}: 删除分类
- POST /api/personal/categories/{name}/words: 添加单词到分类
- DELETE /api/personal/categories/{name}/words/{word}: 从分类移除单词
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ielts_buddy.core.models import PersonalWord
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser


router = APIRouter(tags=["personal"])
api_router = APIRouter(prefix="/api/personal", tags=["personal-api"])


class WordCreate(BaseModel):
    """添加单词请求"""
    word: str
    phonetic: Optional[str] = ""
    meaning: str
    pos: Optional[str] = ""
    band: int = 5
    topic: Optional[str] = ""
    example: Optional[str] = ""
    example_cn: Optional[str] = ""
    note: Optional[str] = ""


class WordUpdate(BaseModel):
    """编辑单词请求"""
    phonetic: Optional[str] = None
    meaning: Optional[str] = None
    pos: Optional[str] = None
    band: Optional[int] = None
    topic: Optional[str] = None
    example: Optional[str] = None
    example_cn: Optional[str] = None
    note: Optional[str] = None


class CategoryCreate(BaseModel):
    """创建分类请求"""
    name: str
    description: Optional[str] = ""


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _get_container(request: Request):
    """获取仓库容器"""
    from ielts_buddy.web.main import app
    return getattr(app.state, "container", None)


# =============================================================
# 页面路由
# =============================================================


@router.get("/personal", response_class=HTMLResponse)
def page_personal(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """个人词库页面"""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    # 获取统计信息
    try:
        word_count = container.personal_vocab.get_word_count(user.id)
        categories = container.personal_vocab.list_categories(user.id)
        category_stats = {cat.name: cat.word_count for cat in categories}
    except Exception:
        word_count = 0
        category_stats = {}

    return _get_templates(request).TemplateResponse(
        request,
        "pages/personal_vocab.html",
        {
            "title": "个人词库",
            "phase": 3,
            "current_user": user,
            "word_count": word_count,
            "category_stats": category_stats,
            "request": request,
        },
    )


# =============================================================
# API 路由：单词 CRUD
# =============================================================


@api_router.get("/words")
def api_personal_words(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    category: Annotated[Optional[str], Query(description="分类名")] = None,
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    per_page: Annotated[int, Query(ge=1, le=200, description="每页条数")] = 20,
) -> dict:
    """获取个人词库单词列表"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        words, total = container.personal_vocab.list_words(
            user.id, category=category, page=page, per_page=per_page
        )
        return {
            "words": [w.model_dump() for w in words],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/words")
def api_add_word(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    word: WordCreate,
) -> dict:
    """添加单词到个人词库"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        w = PersonalWord(
            word=word.word,
            phonetic=word.phonetic or "",
            meaning=word.meaning,
            pos=word.pos or "",
            band=word.band,
            topic=word.topic or "",
            example=word.example or "",
            example_cn=word.example_cn or "",
            note=word.note or "",
            source="manual",
        )
        word_id = container.personal_vocab.add_word(user.id, w)
        return {"success": True, "id": word_id, "word": word.word}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.put("/words/{word_name}")
def api_edit_word(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    word_name: str,
    update: WordUpdate,
) -> dict:
    """编辑单词"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        updated = container.personal_vocab.edit_word(
            user.id, word_name,
            phonetic=update.phonetic,
            meaning=update.meaning,
            pos=update.pos,
            band=update.band,
            topic=update.topic,
            example=update.example,
            example_cn=update.example_cn,
            note=update.note,
        )
        return {"success": True, "word": updated.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.delete("/words/{word_name}")
def api_delete_word(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    word_name: str,
) -> dict:
    """删除单词"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        deleted = container.personal_vocab.delete_word(user.id, word_name)
        if not deleted:
            raise HTTPException(status_code=404, detail="单词不存在")
        return {"success": True, "deleted": word_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================
# API 路由：分类管理
# =============================================================


@api_router.get("/categories")
def api_list_categories(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> dict:
    """获取分类列表"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        categories = container.personal_vocab.list_categories(user.id)
        return {
            "categories": [
                {
                    "id": cat.id,
                    "name": cat.name,
                    "description": cat.description,
                    "word_count": cat.word_count,
                    "is_system": cat.is_system,
                }
                for cat in categories
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/categories")
def api_create_category(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    category: CategoryCreate,
) -> dict:
    """创建分类"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        cat = container.personal_vocab.create_category(
            user.id, category.name, category.description or ""
        )
        return {"success": True, "category": cat.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.delete("/categories/{name}")
def api_delete_category(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    name: str,
) -> dict:
    """删除分类"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        container.personal_vocab.delete_category(user.id, name)
        return {"success": True, "deleted": name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/categories/{name}/words")
def api_add_word_to_category(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    name: str,
    word: Annotated[str, Form()],
) -> dict:
    """添加单词到分类"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        added = container.personal_vocab.add_to_category(user.id, word, name)
        return {"success": True, "word": word, "category": name, "added": added}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.delete("/categories/{name}/words/{word}")
def api_remove_word_from_category(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    name: str,
    word: str,
) -> dict:
    """从分类移除单词"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        removed = container.personal_vocab.remove_from_category(user.id, word, name)
        return {"success": True, "word": word, "category": name, "removed": removed}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================
# API 路由：错词本快捷操作
# =============================================================


# =============================================================
# API 路由：导入导出
# =============================================================


@api_router.post("/import")
async def api_import_words(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
) -> dict:
    """导入单词（支持 CSV/JSON）"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="请上传文件")

        import io
        content = await file.read()

        # 根据扩展名判断格式
        filename = file.filename or ""
        if filename.endswith(".json"):
            result = container.personal_vocab.import_words(
                user.id, io.BytesIO(content), None
            )
        else:
            # CSV 或纯文本
            result = container.personal_vocab.import_words(
                user.id, io.BytesIO(content), None
            )

        return {
            "success": True,
            "imported": result.get("imported", 0),
            "skipped": result.get("skipped", 0),
            "failed": result.get("failed", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/export")
def api_export_words(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    fmt: str = "csv",
) -> HTMLResponse:
    """导出单词"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        content = container.personal_vocab.export_words(user.id, fmt=fmt)

        if fmt == "csv":
            return HTMLResponse(
                content=content,
                headers={
                    "Content-Disposition": f"attachment; filename=personal_vocab.csv"
                },
            )
        else:
            return HTMLResponse(
                content=content,
                headers={
                    "Content-Disposition": f"attachment; filename=personal_vocab.json"
                },
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/mistakes/{word}")
def api_add_mistake(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    word_name: str,
    context: Annotated[Optional[str], Form()] = None,
) -> dict:
    """添加单词到错词本"""
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    try:
        from ielts_buddy.core.models import PersonalWord as CorePersonal, Word as CoreWord
        # 从词库获取单词信息
        from ielts_buddy.web.main import app
        vocab_svc = getattr(app.state, "vocab_service", None)
        word_data = None
        if vocab_svc:
            word_data = vocab_svc.get_word(word_name)

        if word_data:
            # PersonalWord 接受 Word 的全部字段（不包括 collocations/synonyms/etymology/is_custom）
            w = CorePersonal(
                word=word_data.word,
                phonetic=word_data.phonetic or "",
                meaning=word_data.meaning or "",
                pos=word_data.pos or "",
                band=word_data.band if hasattr(word_data, "band") and word_data.band else 5,
                topic=word_data.topic or "",
                example=word_data.example or "",
                example_cn=word_data.example_cn or "",
            )
        else:
            w = CorePersonal(word=word_name, meaning=context or "", band=5)

        result = container.personal_vocab.add_mistake(user.id, w, source="quiz_mistake")
        return {"success": True, "word": result.word}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router", "api_router"]
