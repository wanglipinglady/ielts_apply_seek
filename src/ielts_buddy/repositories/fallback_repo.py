"""Fallback Container（v3）：MySQL 主存 + SQLite 自动降级。

核心思想：
  - 启动期根据 ``IELTS_BUDDY_WEB_DB_MODE`` 配置 + MySQL 可达性决定主 backend
  - 主 backend 失败时自动 fallback 到 SQLite（fallback_sqlite 模式）
  - 写操作同时双写：主 backend 失败时写到 SQLite 并标记 ``sync_status='pending_upload'``
  - 后台 SyncWorker 定期把 pending_upload 推 MySQL，把 MySQL 新增拉到本地 SQLite

实现要点：
  - 透传所有方法到当前激活的 container
  - 双 backend 实例共存；运行时根据 ``current_mode`` 切换
  - 切换不影响 SQLite cache 的内容
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.exc import SQLAlchemyError

from ielts_buddy.repositories.mysql_repo import MySQLRepositoryContainer
from ielts_buddy.repositories.sqlite_repo import SQLiteRepositoryContainer

logger = logging.getLogger(__name__)


class FallbackContainer:
    """MySQL + SQLite 双 backend 容器。

    始终持有两个底层容器：
      - ``_online``：MySQL（可能为 None —— 用户强制 sqlite 模式时）
      - ``_offline``：SQLite（始终存在）

    ``current_mode`` 取值：
      - ``"online"``：所有读写走 MySQL；SQLite 仅作缓存
      - ``"fallback_sqlite"``：MySQL 不可达，写 SQLite + 标 pending_upload
    """

    def __init__(
        self,
        mysql_container: Optional[MySQLRepositoryContainer],
        sqlite_container: SQLiteRepositoryContainer,
    ):
        self._online = mysql_container
        self._offline = sqlite_container
        self._current_mode = "online" if mysql_container else "fallback_sqlite"
        self._last_mysql_check_ts: float = 0.0
        self._last_mysql_ok: bool = mysql_container is not None

    # ---- 子仓储透传 ----
    @property
    def learning(self):
        return self._active.learning

    @property
    def personal_vocab(self):
        return self._active.personal_vocab

    @property
    def exam(self):
        return self._active.exam

    @property
    def grade(self):
        return self._active.grade

    @property
    def typing(self):
        return self._active.typing

    @property
    def focus_sessions(self):
        return self._active.focus_sessions

    @property
    def user(self):
        return self._active.user

    @property
    def vocab_cache(self):
        return self._active.vocab_cache

    @property
    def article(self):
        return self._active.article

    @property
    def speaking_practice(self):
        """v3.7 P1:口语对练历史仓储透传。"""
        return self._active.speaking_practice

    @property
    def listening_practice(self):
        """v3.7 P2:真·听力题库仓储透传。"""
        return self._active.listening_practice

    @property
    def online(self) -> Optional[MySQLRepositoryContainer]:
        """MySQL container；强制 sqlite 模式下为 None。"""
        return self._online

    @property
    def offline(self) -> SQLiteRepositoryContainer:
        """SQLite container；始终存在。"""
        return self._offline

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @property
    def mysql_reachable(self) -> bool:
        return self._last_mysql_ok

    @property
    def _active(self):
        """当前激活的 backend（用于透传读）。"""
        if self._current_mode == "online" and self._online is not None:
            return self._online
        return self._offline

    # ---- 显式执行 ----
    def try_mysql(self) -> bool:
        """主动 ping MySQL，更新可达性。返回最新状态。"""
        if self._online is None:
            self._last_mysql_ok = False
            return False
        try:
            with self._online._engine.connect() as conn:
                from sqlalchemy import text
                conn.execute(text("SELECT 1"))
            self._last_mysql_ok = True
            if self._current_mode != "online":
                self._switch_to_online()
            return True
        except SQLAlchemyError as e:
            logger.warning("MySQL ping 失败: %s", e)
            self._last_mysql_ok = False
            if self._current_mode != "fallback_sqlite":
                self._switch_to_fallback()
            return False

    def _switch_to_online(self):
        old = self._current_mode
        self._current_mode = "online"
        logger.info("DB mode: %s → online（MySQL 恢复）", old)

    def _switch_to_fallback(self):
        old = self._current_mode
        self._current_mode = "fallback_sqlite"
        logger.warning("DB mode: %s → fallback_sqlite（MySQL 不可达）", old)

    # ---- 模式切换 ----
    def force_online(self):
        """运维手动切回 online（用于 /api/admin/db-mode 接口）。"""
        if self._online is None:
            raise RuntimeError("未配置 MySQL container，无法切到 online")
        self._switch_to_online()

    def force_offline(self):
        """运维手动切到 fallback。"""
        self._switch_to_fallback()

    # ---- 生命周期 ----
    def close(self) -> None:
        if self._online is not None:
            try:
                self._online.close()
            except Exception:
                pass
        try:
            self._offline.close()
        except Exception:
            pass


def create_fallback_container(
    *,
    sqlite_db_path: Path,
    mysql_url: str = "",
    prefer_mode: str = "online",
) -> FallbackContainer:
    """创建 FallbackContainer。

    Args:
        sqlite_db_path: 本地 SQLite 路径（必填）。
        mysql_url: 完整 MySQL URL；空串走 mysql_repo 默认。
        prefer_mode: ``"online"`` / ``"sqlite"`` / ``"fallback_sqlite"``。
                     online 模式：尝试连 MySQL，连不上再降级。
                     sqlite 模式：强制只连 SQLite。
                     fallback_sqlite：启动时假设 MySQL 不可达。

    Returns:
        构造好的 FallbackContainer（已做连接测试）。
    """
    # SQLite 始终建好
    sqlite = SQLiteRepositoryContainer(sqlite_db_path)

    # MySQL 按需建
    mysql: Optional[MySQLRepositoryContainer] = None
    if prefer_mode in ("online", "fallback_sqlite"):
        try:
            mysql = MySQLRepositoryContainer(
                connection_url=mysql_url or None
            )
        except Exception as e:
            logger.warning("MySQL container 创建失败: %s", e)
            mysql = None

    # 构造 fallback container
    container = FallbackContainer(
        mysql_container=mysql,
        sqlite_container=sqlite,
    )

    # 启动期健康检查
    if prefer_mode == "online":
        if mysql is not None and container.try_mysql():
            container._current_mode = "online"
            logger.info("✓ 启动期 MySQL 在线 → mode=online")
        else:
            container._current_mode = "fallback_sqlite"
            container._last_mysql_ok = False
            logger.warning("⚠ 启动期 MySQL 不可达 → mode=fallback_sqlite")
    elif prefer_mode == "sqlite":
        container._current_mode = "fallback_sqlite"
        container._last_mysql_ok = False
    elif prefer_mode == "fallback_sqlite":
        container._current_mode = "fallback_sqlite"
        container._last_mysql_ok = False

    return container


__all__ = ["FallbackContainer", "create_fallback_container"]