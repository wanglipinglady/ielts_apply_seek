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
from ielts_buddy.repositories import SQLiteRepositoryContainer
from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.routers.lookup import resolve_word_metadata
from ielts_buddy.web.services import get_container, get_vocab_service


router = APIRouter(tags=["personal"])
api_router = APIRouter(prefix="/api/personal", tags=["personal-api"])


class WordCreate(BaseModel):
    """添加单词请求

    Phase 1 (个人词库改造)：原来必填 meaning，现在改为可选。
    - 用户只填 word + note → 系统自动从词库补全
    - 词库查不到 → 用户手动补 meaning/phonetic/pos（fallback 路径）
    """
    word: str
    phonetic: Optional[str] = ""          # 选填（fallback 才用）
    meaning: Optional[str] = ""           # 改为选填（fallback 才用）
    pos: Optional[str] = ""               # 选填
    band: Optional[int] = None            # 选填（自动补）
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


class BatchWordAdd(BaseModel):
    """批量加入个人词库请求（用于文章页"勾选加入词库"功能）

    - words: ArticleWord dict 列表（来自 /api/articles/translate 返回）
    - skip_existing: True=跳过已存在的（默认 True，避免报错打断批量加入）
    """
    words: list[dict]
    skip_existing: bool = True


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _get_container(request: Request):
    """获取仓库容器"""
    return getattr(request.app.state, "container", None)


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
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
) -> dict:
    """添加单词到个人词库（Phase 1 改造：自动从词库补全）

    行为：
    1. 先用 ``vocab.get_word(word.word)`` 查内置词库
    2. 找到了 → 自动补全 phonetic / meaning / pos / band / topic / example
    3. 找不到 → 用户必须手动提供 meaning（fallback 路径），其他字段保持空
    4. 用户填写的字段（即使词库有）会**覆盖**自动补全的值（用户永远有最终决定权）
    """
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    # Step 1：查内置词库
    db_word = vocab.get_word(word.word.strip())

    # Step 2：合并字段（用户输入优先，回落到词库，再回落到空串）
    phonetic = word.phonetic or (db_word.phonetic if db_word else "")
    meaning = word.meaning or (db_word.meaning if db_word else "")
    pos = word.pos or (db_word.pos if db_word else "")
    band = word.band if word.band is not None else (db_word.band if db_word else 5)
    topic = word.topic or (db_word.topic if db_word else "")
    example = word.example or (db_word.example if db_word else "")
    example_cn = word.example_cn or (db_word.example_cn if db_word else "")

    # Step 3：fallback 校验 —— 词库查不到且用户没填 meaning → 拒
    if not meaning:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"词库中找不到 '{word.word}'，请手动填写 meaning 后再提交"
            ),
        )

    try:
        w = PersonalWord(
            word=word.word.strip(),
            phonetic=phonetic,
            meaning=meaning,
            pos=pos,
            band=band,
            topic=topic,
            example=example,
            example_cn=example_cn,
            note=word.note or "",
            source="manual",
        )
        word_id = container.personal_vocab.add_word(user.id, w)
        # 返回完整记录，前端预览卡片可以展示补全结果
        return {
            "success": True,
            "id": word_id,
            "word": w.word,
            "phonetic": w.phonetic,
            "meaning": w.meaning,
            "pos": w.pos,
            "band": w.band,
            "topic": w.topic,
            "example": w.example,
            "example_cn": w.example_cn,
            "autocompleted": db_word is not None,
        }
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


@api_router.post("/words/batch")
async def api_add_words_batch(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    body: BatchWordAdd,
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
) -> dict:
    """批量加入个人词库（文章页"勾选加入"使用）。

    流程：
    1. 遍历 body.words（每个是 ArticleWord dict）
    2. 优先用 dict 自带的 phonetic/meaning/pos/band 等；
       缺失字段走三层 fallback 补全（内置词库 → 词典 API + MyMemory → LLM）
       —— 即 ``resolve_word_metadata()``，与 ``/api/lookup/word`` 同源
    3. 个人词库已存在 → skip_existing=True 时跳过；否则报错
    4. 返回 {added: [...], skipped: [...], failed: [...]}

    注：如果三层 fallback 仍拿不到 meaning（极端情况：所有源都失败），
    该词进 failed 并返回 reason='无法补全 meaning'，不会写空释义进库。
    """
    container = _get_container(request)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")

    added: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []

    for w in body.words:
        word_text = (w.get("word") or "").strip()
        if not word_text:
            failed.append({"word": "", "reason": "empty word"})
            continue

        try:
            # 走三层 fallback 补全释义/音标/词性
            meta = await resolve_word_metadata(word_text, vocab)
            meaning = w.get("meaning_cn") or meta.get("meaning_cn") or meta.get("meaning_en") or ""
            phonetic = w.get("phonetic") or meta.get("phonetic") or ""
            pos = w.get("pos") or meta.get("pos") or ""
            band = w.get("band")
            if band is None and meta.get("band") is not None:
                band = meta["band"]
            if band is None:
                band = 5

            # 三层 fallback + 用户 context 全空 → 不入库（避免空释义污染）
            if not meaning:
                failed.append({
                    "word": word_text,
                    "reason": (
                        f"无法补全 meaning（内置词库/词典 API/LLM 均未命中，"
                        f"source={meta.get('source')}）"
                    ),
                })
                continue

            # 把同义/反义信息塞进 note，方便后续查看
            note_parts = []
            if w.get("synonyms"):
                note_parts.append(f"同义: {', '.join(w['synonyms'])}")
            if w.get("antonyms"):
                note_parts.append(f"反义: {', '.join(w['antonyms'])}")
            if w.get("near_synonyms"):
                note_parts.append(f"近义: {', '.join(w['near_synonyms'])}")
            if w.get("context_meaning"):
                note_parts.append(f"语境: {w['context_meaning']}")
            if w.get("context_sentence"):
                note_parts.append(f"原句: {w['context_sentence'][:150]}")
            note = "\n".join(note_parts)

            pw = PersonalWord(
                word=word_text,
                phonetic=phonetic,
                meaning=meaning,
                pos=pos,
                band=band,
                topic=meta.get("topic") or "",
                example=meta.get("example") or "",
                example_cn=meta.get("example_cn") or "",
                note=note,
                source="article",
            )
            container.personal_vocab.add_word(user.id, pw)
            added.append(word_text)
        except ValueError as e:
            # 已存在
            if body.skip_existing and "已存在" in str(e):
                skipped.append(word_text)
            else:
                failed.append({"word": word_text, "reason": str(e)})
        except Exception as e:
            failed.append({"word": word_text, "reason": str(e)})

    return {
        "success": True,
        "added_count": len(added),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "added": added,
        "skipped": skipped,
        "failed": failed,
    }


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
