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
from typing import Any

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


def get_stats_conn(request: Request):
    """阶段 2：StatsService 用的独立 SQLite 连接（``check_same_thread=False``）。

    注意：MySQL 模式下 web_stats_conn 为 None，此时 get_stats_service 会
    降级使用 StatsService（通过容器访问 MySQL）。
    """
    conn = getattr(request.app.state, "web_stats_conn", None)
    # MySQL 模式下 conn 为 None，这是正常的，get_stats_service 会处理
    return conn


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
    """VocabService 内部维护词库索引，整个进程共享一份。"""
    svc = VocabService()
    svc.load_all()
    return svc


def get_vocab_service() -> VocabService:
    """VocabService：词库是只读数据，全进程共享一份即可。"""
    return _vocab_service_singleton()


# =============================================================
# 统计服务（Web 端自研版 + MySQL 兼容）
# =============================================================


class WebStatsServiceWrapper:
    """统计服务包装器：支持 SQLite（WebStatsService）和 MySQL（StatsService）两种模式。

    MySQL 模式下透明降级使用 StatsService（通过容器访问）。
    """

    def __init__(
        self,
        sqlite_conn,
        container,
        user_id: int,
    ) -> None:
        self._sqlite_conn = sqlite_conn
        self._container = container
        self._user_id = user_id
        self._is_mysql = container is not None and hasattr(container, 'learning')

    def _get_sqlite_svc(self) -> WebStatsService:
        """获取 SQLite 服务（延迟构造）。"""
        if not hasattr(self, '_sqlite_svc') or self._sqlite_svc is None:
            self._sqlite_svc = WebStatsService(self._sqlite_conn, self._user_id)
        return self._sqlite_svc

    def _get_mysql_svc(self):
        """获取 MySQL 服务（延迟构造）。"""
        if not hasattr(self, '_mysql_svc') or self._mysql_svc is None:
            from ielts_buddy.services.stats_service import StatsService
            # MySQL 模式下直接用容器创建 StatsService
            self._mysql_svc = StatsService.__new__(StatsService)
            self._mysql_svc._container = self._container
            self._mysql_svc._repo = self._container.learning
            self._mysql_svc._user_id = self._user_id
        return self._mysql_svc

    def total_stats(self) -> dict[str, Any]:
        if self._is_mysql:
            return self._get_mysql_svc().total_stats()
        return self._get_sqlite_svc().total_stats()

    def today_stats(self) -> dict[str, Any]:
        if self._is_mysql:
            return self._get_mysql_svc().today_stats()
        return self._get_sqlite_svc().today_stats()

    def due_count(self) -> int:
        if self._is_mysql:
            return self._get_mysql_svc().due_count()
        return self._get_sqlite_svc().due_count()

    def level_distribution(self) -> dict[int, int]:
        if self._is_mysql:
            return self._get_mysql_svc().level_distribution()
        return self._get_sqlite_svc().level_distribution()

    def get_streak(self) -> tuple[int, int]:
        if self._is_mysql:
            return self._get_mysql_svc().get_streak()
        return self._get_sqlite_svc().get_streak()

    def get_daily_trend(self, days: int = 7) -> list[tuple[str, int, float]]:
        if self._is_mysql:
            return self._get_mysql_svc().get_daily_trend(days)
        return self._get_sqlite_svc().get_daily_trend(days)

    def get_band_progress(self) -> list[tuple[int, int, int, float]]:
        if self._is_mysql:
            return self._get_mysql_svc().get_band_progress()
        return self._get_sqlite_svc().get_band_progress()

    def get_history(self, days: int = 7) -> list[dict[str, Any]]:
        if self._is_mysql:
            return self._get_mysql_svc().get_history(days)
        return self._get_sqlite_svc().get_history(days)


def get_stats_service(
    conn=Depends(get_stats_conn),
    container=Depends(get_container),
) -> WebStatsServiceWrapper:
    """为当前 web 用户构造一个统计服务。

    - MySQL 模式：使用 StatsService 通过容器访问 MySQL
    - SQLite 模式：使用 WebStatsService 直连 SQLite
    """
    return WebStatsServiceWrapper(sqlite_conn=conn, container=container, user_id=0)


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
