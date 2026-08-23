"""Database health check（v3）。

提供 ``is_mysql_reachable()`` 检测 MySQL 是否可达，带 5s TTL 缓存，
避免每次请求都 ping。

Web / CLI 的 ``FallbackContainer`` 用这个函数决定走哪个 backend。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine


# 默认缓存 TTL（秒）
DEFAULT_TTL = 5.0


class _HealthCache:
    """线程安全的 MySQL 可达性缓存。"""

    def __init__(self, ttl: float = DEFAULT_TTL):
        self._ttl = ttl
        self._last_check_ts: float = 0.0
        self._last_result: bool = False
        self._lock = threading.Lock()

    def is_fresh(self) -> bool:
        return (time.monotonic() - self._last_check_ts) < self._ttl

    def get(self) -> bool:
        return self._last_result

    def set(self, ok: bool) -> None:
        self._last_check_ts = time.monotonic()
        self._last_result = ok


# 进程级单例缓存（Web + CLI 共用一个）
_cache = _HealthCache()


def is_mysql_reachable(
    engine: Optional[Engine] = None,
    *,
    timeout: float = 2.0,
    force_refresh: bool = False,
) -> bool:
    """检查 MySQL 是否可达。

    Args:
        engine: 已构造好的 SQLAlchemy Engine；None 时按配置临时构造一个。
        timeout: 单次 ping 超时（秒）。
        force_refresh: 强制刷新缓存（默认 False，5s 内复用上次结果）。

    Returns:
        True 表示可达，False 表示不可达。

    行为：
        - 命中缓存且未过期 → 直接返回上次结果
        - 否则尝试 ``SELECT 1``，捕获所有异常后返回 False
        - 缓存结果加锁写入（多线程安全）
    """
    if not force_refresh and _cache.is_fresh():
        return _cache.get()

    with _cache._lock:
        # 双重检查：另一个线程可能刚检查过
        if not force_refresh and _cache.is_fresh():
            return _cache.get()

        ok = False
        try:
            if engine is None:
                engine = _build_default_engine()
            # 用临时连接执行 ping
            from sqlalchemy.exc import SQLAlchemyError
            try:
                with engine.connect() as conn:
                    # SET STATEMENT max_statement_time = timeout*1000 ms
                    conn.execute(text("SELECT 1"))
                ok = True
            except SQLAlchemyError:
                ok = False
        except Exception:
            ok = False
        finally:
            if engine is not None and not _is_external_engine(engine):
                try:
                    engine.dispose()
                except Exception:
                    pass

        _cache.set(ok)
        return ok


def _is_external_engine(engine: Engine) -> bool:
    """外部传入的 engine 不要 dispose（避免破坏长连接池）。"""
    return getattr(engine, "_external", False)


def _build_default_engine() -> Engine:
    """按 web_config / core_config 构造一个临时 engine 用于 ping。"""
    from urllib.parse import quote_plus
    from sqlalchemy import create_engine
    from ielts_buddy.repositories.mysql_repo import (
        DEFAULT_MYSQL_HOST, DEFAULT_MYSQL_PORT, DEFAULT_MYSQL_USER,
        DEFAULT_MYSQL_PASSWORD, DEFAULT_MYSQL_DATABASE, DEFAULT_MYSQL_CHARSET,
    )
    url = (
        f"mysql+pymysql://{DEFAULT_MYSQL_USER}:{quote_plus(DEFAULT_MYSQL_PASSWORD)}"
        f"@{DEFAULT_MYSQL_HOST}:{DEFAULT_MYSQL_PORT}/{DEFAULT_MYSQL_DATABASE}"
        f"?charset={DEFAULT_MYSQL_CHARSET}"
    )
    return create_engine(url, pool_pre_ping=False, pool_recycle=3600, future=True)


def reset_cache() -> None:
    """手动清缓存（测试 / 健康检查 endpoint 用）。"""
    with _cache._lock:
        _cache._last_check_ts = 0.0
        _cache._last_result = False


__all__ = [
    "is_mysql_reachable",
    "reset_cache",
]