"""/articles 文章翻译 + 生词分析路由。

功能：
- GET /articles: 文章翻译页（输入文章 → 翻译 → 生词标注 → 加入词库）
- POST /api/articles/translate: 一站式翻译 + 生词自动标注 + LLM 词义聚类分析
- POST /api/articles/save: 保存翻译+分析结果到学习历史
- GET /api/articles/history: 列出用户最近的文章记录
- GET /api/articles/{id}: 查询完整记录（原文 + 翻译 + 生词列表）
- DELETE /api/articles/{id}: 删除历史文章

设计要点：
1. POST /translate 是同步端点，但 LLM 调用走 ``asyncio.to_thread`` 不阻塞事件循环
2. 生词识别 = 内置词库 band ≥ 7 + 高频常见词自动标 + 用户手动勾选叠加
3. LLM 翻译 + 生词分析走两次独立调用，便于分别失败重试
4. 保存到 articles 表（diff_words_json 存 ArticleWord 列表 JSON）
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from ielts_buddy.core.models import ArticleWord
from ielts_buddy.repositories import SQLiteRepositoryContainer
from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.auth.deps import get_current_user, get_current_user_optional
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.llm_service import get_llm_service
from ielts_buddy.web.routers.lookup import resolve_word_metadata
from ielts_buddy.web.services import get_vocab_service


router = APIRouter(tags=["articles"])
api_router = APIRouter(prefix="/api/articles", tags=["articles-api"])


# =============================================================
# 常量
# =============================================================


# 输入长度上限（800 词；与用户决定一致）
MAX_WORDS = 800
MAX_CHARS = 5000

# 生词自动识别阈值：内置词库 band ≥ 7 的词标记为生词
# （band 7+ 通常对应 C1/C2 难度，符合"较难词汇"语义）
DIFF_BAND_THRESHOLD = 7

# LLM 分析时每次最多分析的生词数（避免 prompt 超长）
ANALYZE_BATCH_SIZE = 30


# =============================================================
# Pydantic 模型
# =============================================================


class TranslateRequest(BaseModel):
    """翻译请求体"""
    source_text: str = Field(..., min_length=10, max_length=MAX_CHARS * 6)
    title: str = Field(default="", max_length=100)
    min_band: int = Field(default=DIFF_BAND_THRESHOLD, ge=5, le=9,
                          description="band ≥ 此值的词标记为生词（默认 7）")
    extra_words: list[str] = Field(default_factory=list,
                                   description="用户手动追加的生词列表")


class SaveArticleRequest(BaseModel):
    """保存翻译结果请求"""
    title: str = Field(default="", max_length=100)
    source_text: str = Field(..., min_length=10)
    translation: str = Field(default="")
    diff_words: list[ArticleWord] = Field(default_factory=list)
    translation_source: str = "llm"
    analysis_source: str = "fallback"


# =============================================================
# 工具函数
# =============================================================


def _get_container(request: Request) -> SQLiteRepositoryContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="数据库未初始化")
    return container


def _tokenize_english(text: str) -> list[str]:
    """简单英文分词：小写化 + 去掉标点 + 去停用词。

    返回原形列表（不去后缀；不做词形还原，避免复杂度）。
    用户可手动追加任意词；后端只做粗粒度 dedupe。
    """
    # 拆词：小写 + 按非字母数字切分
    raw_tokens = re.findall(r"[a-zA-Z']+", text.lower())
    # 简单停用词（极高频功能词，通常不做生词分析）
    STOP = {
        "a", "an", "the", "and", "or", "but", "if", "in", "on", "at",
        "to", "for", "of", "with", "by", "from", "as", "is", "are",
        "was", "were", "be", "been", "being", "am", "do", "does",
        "did", "have", "has", "had", "having", "i", "you", "he",
        "she", "it", "we", "they", "them", "this", "that", "these",
        "those", "will", "would", "should", "can", "could", "may",
        "might", "must", "shall", "not", "no", "so", "very", "too",
        "just", "also", "than", "then", "now", "here", "there",
        "when", "where", "why", "how", "what", "which", "who",
        "whom", "whose", "all", "each", "every", "both", "few",
        "more", "most", "other", "some", "such", "any", "into",
        "out", "up", "down", "about", "above", "below", "after",
        "before", "between", "through", "during", "without", "within",
        "along", "across", "against", "its", "his", "her", "their",
        "our", "my", "your", "me", "us", "him", "off", "over",
        "under", "again", "once", "ever", "never", "always",
        "often", "sometimes", "usually", "really", "well", "still",
        "only", "even", "much", "many", "little", "own", "same",
    }
    out: list[str] = []
    seen: set[str] = set()
    for tok in raw_tokens:
        tok = tok.strip("'")
        if len(tok) < 3 or tok in STOP:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _extract_context_sentence(text: str, word: str) -> str:
    """提取单词所在的最短一句原文（用于生词上下文展示）。"""
    word_lower = word.lower()
    # 简单按 . ! ? 分句
    sentences = re.split(r'(?<=[.!?])\s+', text.replace('\n', ' ').strip())
    for s in sentences:
        if word_lower in s.lower():
            return s.strip()[:200]
    return ""


def _auto_detect_diff_words(
    text: str,
    vocab: VocabService,
    min_band: int,
    extra_words: list[str],
) -> list[ArticleWord]:
    """自动识别生词：内置词库命中 + band 过滤 + 去重 + 用户额外追加。

    注意：此函数仅做同步的内置词库查表 O(N)；
    用户手动追加的词在 ``_auto_detect_diff_words_async`` 里**异步**走三层 fallback。

    Returns:
        ArticleWord 列表（auto_marked=True），每个词带 band/meaning/phonetic。
    """
    tokens = _tokenize_english(text)
    diff_words: list[ArticleWord] = []
    seen: set[str] = set()

    # 1) 内置词库命中 + band ≥ 阈值
    for tok in tokens:
        if tok in seen:
            continue
        db_word = vocab.get_word(tok)
        if db_word and db_word.band >= min_band and db_word.meaning:
            seen.add(tok)
            diff_words.append(ArticleWord(
                word=db_word.word,
                phonetic=db_word.phonetic or "",
                pos=db_word.pos or "",
                meaning_cn=db_word.meaning,
                band=db_word.band,
                context_sentence=_extract_context_sentence(text, tok),
                auto_marked=True,
                analysis_source="builtin",
            ))

    # 2) 用户手动追加的词（占位记录；释义/音标/词性在 async 阶段补全）
    for extra in extra_words:
        e = extra.strip().lower()
        if not e or e in seen:
            continue
        seen.add(e)
        db_word = vocab.get_word(e)
        diff_words.append(ArticleWord(
            word=e,
            phonetic=db_word.phonetic if db_word else "",
            pos=db_word.pos if db_word else "",
            meaning_cn=db_word.meaning if db_word else "",
            band=db_word.band if db_word else None,
            context_sentence=_extract_context_sentence(text, e),
            auto_marked=False,  # 用户手动追加
            analysis_source="builtin" if db_word else "pending_lookup",
        ))

    return diff_words


async def _enrich_user_added_words(
    diff_words: list[ArticleWord],
    vocab: VocabService,
) -> list[ArticleWord]:
    """对用户手动追加的词（``analysis_source='pending_lookup'``）走三层 fallback 补全。

    复用 ``resolve_word_metadata()``：内置词库 → 词典 API + MyMemory → LLM。
    不阻塞主流程：手动追加的词不多（≤ 几十个），并行 fallback 调用是合理的。
    如果某个词三层都没拿到意义，仍以空字段返回，由用户在 UI 看到并手动补充。
    """
    pending = [dw for dw in diff_words if dw.analysis_source == "pending_lookup"]
    if not pending:
        return diff_words

    metas = await asyncio.gather(
        *(resolve_word_metadata(dw.word, vocab) for dw in pending)
    )

    by_word = {dw.word: dw for dw in pending}
    for meta in metas:
        w = meta.get("word", "").strip().lower()
        if not w or w not in by_word:
            continue
        dw = by_word[w]
        # 用户填的字段优先；fallback 只填空字段
        if not dw.phonetic and meta.get("phonetic"):
            dw.phonetic = meta["phonetic"]
        if not dw.pos and meta.get("pos"):
            dw.pos = meta["pos"]
        if not dw.meaning_cn:
            dw.meaning_cn = meta.get("meaning_cn") or meta.get("meaning_en") or ""
        if dw.band is None and meta.get("band") is not None:
            dw.band = meta["band"]
        dw.analysis_source = meta.get("source") or "fallback"
    return diff_words


def _merge_llm_analysis(
    diff_words: list[ArticleWord],
    analyses,
) -> list[ArticleWord]:
    """把 LLM 返回的 WordAnalysis 合并回 ArticleWord。

    - 每个 ArticleWord 按 word 找对应分析项
    - 写入 synonyms/antonyms/near_synonyms/context_meaning
    - analysis_source 标记为 'llm'
    """
    by_word = {a.word.strip().lower(): a for a in analyses}
    for dw in diff_words:
        a = by_word.get(dw.word.lower())
        if a is None:
            continue
        dw.synonyms = a.synonyms or []
        dw.antonyms = a.antonyms or []
        dw.near_synonyms = a.near_synonyms or []
        if a.context_meaning:
            dw.context_meaning = a.context_meaning
        dw.analysis_source = "llm"
    return diff_words


# =============================================================
# 页面路由
# =============================================================


@router.get("/articles", response_class=HTMLResponse)
def page_articles(
    request: Request,
    user: Annotated[Optional[WebUser], Depends(get_current_user_optional)],
) -> HTMLResponse:
    """文章翻译+生词分析页"""
    templates: Jinja2Templates = request.app.state.templates

    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    container = _get_container(request)
    try:
        article_count = container.article.count(user.id)
        recent = container.article.list_recent(user.id, limit=10)
        # 简化 recent 为列表卡片用
        recent_cards = [
            {
                "id": a.id,
                "title": a.title or (a.source_text[:30] + "..."),
                "word_count": a.word_count,
                "diff_word_count": len(json.loads(a.diff_words_json or "[]")),
                "created_at": a.created_at,
            }
            for a in recent
        ]
    except Exception:
        article_count = 0
        recent_cards = []

    return templates.TemplateResponse(
        request,
        "pages/articles.html",
        {
            "title": "文章翻译",
            "phase": 4,
            "current_user": user,
            "article_count": article_count,
            "recent_cards": recent_cards,
            "request": request,
        },
    )


# =============================================================
# API：翻译 + 生词分析（一次性）
# =============================================================


@api_router.post("/translate")
async def api_translate_article(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    body: TranslateRequest,
    vocab: Annotated[VocabService, Depends(get_vocab_service)],
) -> dict:
    """一站式：翻译文章 + 自动识别生词 + LLM 分析同义/反义/近义。

    流程：
    1. 校验长度（≤800 词 / ≤30k 字符）
    2. LLM 翻译（同步调用 → asyncio.to_thread 不阻塞）
    3. 自动识别生词（词库 band ≥ min_band + 用户额外追加）
    4. LLM 一次性分析生词的同义/反义/近义/语境含义
    5. 合并结果返回（**不自动保存**；由前端调 /save 显式保存）

    Returns:
        {
            "title": ...,
            "source_text": ...,
            "translation": "...",
            "translation_source": "llm",
            "word_count": N,
            "diff_words": [ArticleWord, ...],
            "stats": {"diff_count": M, "llm_analyzed": K}
        }
    """
    text = body.source_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="原文不能为空")

    word_count = len(re.findall(r"\b[a-zA-Z']+\b", text))
    if word_count > MAX_WORDS:
        raise HTTPException(
            status_code=400,
            detail=f"文章过长（{word_count} 词），最大支持 {MAX_WORDS} 词"
        )

    # 1) 自动识别生词（同步，O(N)）
    diff_words = _auto_detect_diff_words(text, vocab, body.min_band, body.extra_words)

    # 1.5) 用户手动追加的词走三层 fallback 补全（异步）
    #     —— 复用 resolve_word_metadata()：内置词库 → 词典 API + MyMemory → LLM
    diff_words = await _enrich_user_added_words(diff_words, vocab)

    # 2) 并行：LLM 翻译 + LLM 生词分析（两次独立调用）
    llm = get_llm_service()
    analysis_source_final = "llm" if llm.is_available() else "fallback"

    async def _do_translate() -> tuple[str, str]:
        """返回 (translation_text, source_label)"""
        if not llm.is_available():
            return (
                f"[DRY-RUN 翻译] {text[:200]}...\n\n（设置 IELTS_BUDDY_LLM_API_KEY 后由 LLM 翻译）",
                "mock",
            )
        try:
            result = await asyncio.to_thread(llm.translate, text, "zh")
            return (result.translation, result.source)
        except Exception as e:
            return (f"[翻译失败: {e}]", "error")

    async def _do_analyze():
        """对生词做 LLM 同义/反义/近义分析（批量处理避免 prompt 超长）"""
        if not diff_words:
            return []
        if not llm.is_available():
            # mock 模式：每个词返回占位（前端可识别 source=mock）
            return [
                {
                    "word": w.word,
                    "synonyms": [],
                    "antonyms": [],
                    "near_synonyms": [],
                    "context_meaning": "",
                    "source": "mock",
                }
                for w in diff_words
            ]
        # 分批调用，避免单次 prompt 超长
        all_analyses = []
        for i in range(0, len(diff_words), ANALYZE_BATCH_SIZE):
            batch = diff_words[i:i + ANALYZE_BATCH_SIZE]
            words = [dw.word for dw in batch]
            try:
                analyses = await asyncio.to_thread(llm.analyze_words, words, text)
                all_analyses.extend(analyses)
            except Exception as e:
                # 单批失败不影响整体
                all_analyses.extend([
                    {
                        "word": w.word,
                        "synonyms": [],
                        "antonyms": [],
                        "near_synonyms": [],
                        "context_meaning": f"[分析失败: {e}]",
                        "source": "error",
                    }
                    for w in batch
                ])
        return all_analyses

    # asyncio.gather 并行执行（翻译 + 生词分析独立）
    translation_result, raw_analyses = await asyncio.gather(
        _do_translate(),
        _do_analyze(),
    )
    translation_text, translation_source = translation_result

    # 3) 合并 LLM 分析到 ArticleWord（按 word 匹配）
    # _do_analyze 返回的可能是 WordAnalysis 对象（真实 LLM 路径）
    # 或 dict（mock / error fallback 路径），需统一处理。
    from ielts_buddy.web.llm_service import WordAnalysis
    analyses_typed: list[WordAnalysis] = []
    for a in raw_analyses:
        if isinstance(a, WordAnalysis):
            analyses_typed.append(a)
        elif isinstance(a, dict):
            analyses_typed.append(WordAnalysis(
                word=a.get("word", ""),
                synonyms=a.get("synonyms") or [],
                antonyms=a.get("antonyms") or [],
                near_synonyms=a.get("near_synonyms") or [],
                context_meaning=a.get("context_meaning") or "",
                source=a.get("source") or "llm",
            ))
        else:
            # 兜底：未知类型，按空分析处理
            analyses_typed.append(WordAnalysis(word=str(a), source="error"))
    diff_words = _merge_llm_analysis(diff_words, analyses_typed)

    # 关键：FastAPI 默认序列化可能把字符串里的 raw \n / \t 当字面量传给客户端，
    # 浏览器 fetch().json() 会报 "Invalid control character"。
    # 在此处强制把字符串里的 ASCII 控制字符替换为对应字符（用 ` ` 代替），
    # 确保响应是合法 JSON（前端拿到的字符串不会再含控制字符）。
    def _safe_str(s: str) -> str:
        if not s:
            return s
        # 把 \r\n / \n / \r / \t 等统一替换为单空格
        return s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")

    safe_translation = _safe_str(translation_text)
    safe_diff_words = [
        {**dw.model_dump(),
         "meaning_cn": _safe_str(dw.meaning_cn),
         "context_sentence": _safe_str(dw.context_sentence),
         "context_meaning": _safe_str(dw.context_meaning),
         "phonetic": _safe_str(dw.phonetic),
         "pos": _safe_str(dw.pos),
         "word": _safe_str(dw.word)}
        for dw in diff_words
    ]

    return {
        "title": _safe_str(body.title or text[:50]),
        "source_text": _safe_str(text),
        "translation": safe_translation,
        "translation_source": translation_source,
        "analysis_source": analysis_source_final,
        "word_count": word_count,
        "diff_words": safe_diff_words,
        "stats": {
            "diff_count": len(diff_words),
            "llm_analyzed": sum(
                1 for dw in diff_words if dw.analysis_source == "llm"
            ),
            "user_marked": sum(1 for dw in diff_words if not dw.auto_marked),
        },
    }


# =============================================================
# API：保存到历史
# =============================================================


@api_router.post("/save")
def api_save_article(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    body: SaveArticleRequest,
) -> dict:
    """保存文章翻译 + 生词分析到 articles 表。"""
    container = _get_container(request)
    try:
        article_id = container.article.create(
            user_id=user.id,
            title=body.title or "",
            source_text=body.source_text,
            translation=body.translation or "",
            word_count=len(re.findall(r"\b[a-zA-Z']+\b", body.source_text)),
            diff_words=body.diff_words,
            translation_source=body.translation_source or "llm",
            analysis_source=body.analysis_source or "fallback",
        )
        return {"success": True, "id": article_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================
# API：历史与详情
# =============================================================


@api_router.get("/history")
def api_list_articles(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict:
    """列出用户最近的文章记录（简化卡片数据）。"""
    container = _get_container(request)
    try:
        articles = container.article.list_recent(user.id, limit=limit)
        cards = []
        for a in articles:
            diff = json.loads(a.diff_words_json or "[]")
            cards.append({
                "id": a.id,
                "title": a.title or (a.source_text[:30] + "..."),
                "word_count": a.word_count,
                "diff_word_count": len(diff),
                "translation_source": a.translation_source,
                "analysis_source": a.analysis_source,
                "created_at": a.created_at,
            })
        return {"articles": cards}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{article_id}")
def api_get_article(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    article_id: int,
) -> dict:
    """查询单篇文章的完整记录（含生词 JSON）。"""
    container = _get_container(request)
    article = container.article.get_by_id(user.id, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    try:
        diff_words = json.loads(article.diff_words_json or "[]")
    except (json.JSONDecodeError, TypeError):
        diff_words = []
    return {
        "id": article.id,
        "title": article.title,
        "source_text": article.source_text,
        "translation": article.translation,
        "word_count": article.word_count,
        "diff_words": diff_words,
        "translation_source": article.translation_source,
        "analysis_source": article.analysis_source,
        "created_at": article.created_at,
    }


@api_router.delete("/{article_id}")
def api_delete_article(
    request: Request,
    user: Annotated[WebUser, Depends(get_current_user)],
    article_id: int,
) -> dict:
    """删除历史文章。"""
    container = _get_container(request)
    try:
        deleted = container.article.delete(user.id, article_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="文章不存在")
        return {"success": True, "deleted": article_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router", "api_router"]