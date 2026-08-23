"""Web 端 Services 工厂：把"web_user_id + 仓库容器"包装成 Service 实例。

设计原则：
- Web 端 Service **不读** CLI 的 ``Config.toml``，避免 web 启动被 CLI 配置污染。
- 仓库容器在 ``app.state.container`` 上，由 ``lifespan`` 阶段 1 次性打开。
- 每个请求通过 Depends 拿当前 web_user，再把 ``user_id=web_user.id`` 透传给
  下游 Service。
- 提供 ``get_container`` / ``get_user_id`` / ``get_vocab_service`` /
  ``get_review_service`` / ``get_stats_service`` 共 5 个依赖。

阶段 2：自研 ``WebStatsService``（直接 SQL 走 ``app.state.web_stats_conn``，
``check_same_thread=False``）；不复用 ``services/stats_service.py`` 是因为
后者用 ``self._conn`` 直连，并假设连接在主线程打开，没法兼容 FastAPI 的
threadpool 模型。
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Request

from ielts_buddy.repositories import SQLiteRepositoryContainer
from ielts_buddy.services.review_service import ReviewService
from ielts_buddy.services.vocab_service import VocabService
from ielts_buddy.web.auth.deps import get_current_user
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.stats_service import WebStatsService


# =============================================================
# 容器管理
# =============================================================


def get_container(request: Request) -> SQLiteRepositoryContainer:
    """从 app.state 拿仓库容器（lifespan 阶段打开）。

    注：阶段 3 的 learn / review 操作仍走这个容器（容器里的 ``learning`` Repo
    负责 ``upsert_record`` / ``get_due_words`` 等抽象方法，MySQL / SQLite
    实现都已就位）。stats 因线程模型问题不复用。
    """
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError(
            "app.state.container 未初始化；检查 create_app() 的 lifespan"
        )
    return container


def get_user_id(
    user: WebUser = Depends(get_current_user),
) -> int:
    """当前 web 用户的 id（注入下游 Service 用作 user_id）。"""
    return int(user.id)


# =============================================================
# 词库服务（无状态、按请求构造）
# =============================================================


@lru_cache(maxsize=1)
def _vocab_service_singleton() -> VocabService:
    """VocabService 内部维护词库索引，整个进程共享一份。

    同时加载精选五档（~1k 词）+ master 大词库（4485 词），这样 web 端
    "输入单词 → 自动补全"功能才能覆盖到大部分雅思词汇。
    """
    svc = VocabService()
    svc.load_all()        # 精选 band 5-9
    svc.load_master()     # master 大词库 4485 条（与 load_all 合并去重）
    return svc


def get_vocab_service() -> VocabService:
    """VocabService：词库是只读数据，全进程共享一份即可。"""
    return _vocab_service_singleton()


# =============================================================
# 统计服务（Web 端自研版）
# =============================================================


def get_stats_service(
    container: SQLiteRepositoryContainer = Depends(get_container),
) -> WebStatsService:
    """为当前 web 用户构造一个 ``WebStatsService``。

    关键：之前依赖 ``get_stats_conn`` 拿独立 SQLite 连接（SQLite-only），
    导致 MySQL 模式下 web 端 stats 直接 RuntimeError。现在改为依赖
    ``get_container``（业务容器），从容器拿适配当前 db mode 的连接：

    - SQLite 模式：``container._conn``（sqlite3.Connection）
    - MySQL 模式：``container._engine``（sqlalchemy.Engine）

    WebStatsService 内部 duck typing 自动适配。

    注意：本依赖**不** Depends ``get_user_id``（那个是强制认证的）；
    ``user_id`` 由路由层在拿到可选 user 后注入。
    """
    # 拿不到 user 时 user_id=0 表示"无数据"，路由层会先判 None → 跳登录
    # v3：FallbackContainer 是双 backend 抽象，没有直接的 _conn/_engine；
    #     通过 ``.offline`` (SQLite) 或 ``.online`` (MySQL) 拿到真实连接
    if hasattr(container, "offline") and hasattr(container, "online"):
        # FallbackContainer
        if container.current_mode == "online" and container.online is not None:
            conn = container.online._engine
        else:
            conn = container.offline._conn
    else:
        # 老接口兼容：直接是 SQLiteRepositoryContainer / MySQLRepositoryContainer
        conn = getattr(container, "_conn", None) or getattr(container, "_engine", None)
    if conn is None:
        raise RuntimeError(
            "业务容器既无 _conn 也无 _engine，请检查 repositories 工厂实现"
        )
    return WebStatsService(conn, user_id=0)


# =============================================================
# 复习服务（阶段 3 用，先预位；走容器借壳，跨线程靠 SQLite 容器默认行为）
# =============================================================


def _make_review_service(
    container: SQLiteRepositoryContainer, user_id: int
) -> ReviewService:
    """借壳方式构造 ``ReviewService``。"""
    svc = ReviewService.__new__(ReviewService)
    svc._container = container
    svc._repo = container.learning
    svc._user_id = user_id
    return svc


def get_review_service(
    container: SQLiteRepositoryContainer = Depends(get_container),
    user_id: int = Depends(get_user_id),
) -> ReviewService:
    """为当前 web 用户构造一个 ``ReviewService``（阶段 3 使用）。"""
    return _make_review_service(container, user_id)


__all__ = [
    "get_container",
    "get_stats_conn",
    "get_user_id",
    "get_vocab_service",
    "get_stats_service",
    "get_review_service",
]
