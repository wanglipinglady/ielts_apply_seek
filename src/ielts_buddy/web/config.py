"""Web 端配置：仅读环境变量，不与 CLI config.toml 共享。

CLI 用户的配置通过 ~/.ielts-buddy/config.toml；
Web 用户的配置通过进程环境变量（生产用 systemd EnvironmentFile，
开发用 .env）。
"""

from __future__ import annotations

import os
import secrets
import warnings
from pathlib import Path
from typing import Final


# ===== 路径 =====

def _web_root() -> Path:
    """Web 进程的工作目录。"""
    return Path(os.environ.get("IELTS_BUDDY_WEB_ROOT", ".")).expanduser().resolve()


# ===== 端口 / 主机 =====

WEB_HOST: Final[str] = os.environ.get("IELTS_BUDDY_WEB_HOST", "127.0.0.1")
WEB_PORT: Final[int] = int(os.environ.get("IELTS_BUDDY_WEB_PORT", "8000"))


# ===== JWT =====

def _resolve_jwt_secret() -> str:
    """从环境变量读 JWT 密钥；缺失则随机生成并 warn（dev 友好）。"""
    secret = os.environ.get("IELTS_BUDDY_JWT_SECRET", "").strip()
    if secret:
        if len(secret) < 32:
            warnings.warn(
                "IELTS_BUDDY_JWT_SECRET 长度 < 32 字符，生产环境请使用更长密钥",
                stacklevel=2,
            )
        return secret
    if os.environ.get("IELTS_BUDDY_ENV", "dev") == "prod":
        raise RuntimeError(
            "生产环境必须设置 IELTS_BUDDY_JWT_SECRET（≥32 字符）"
        )
    fallback = secrets.token_urlsafe(48)
    warnings.warn(
        f"JWT_SECRET 未设置，本次启动使用临时密钥；重启后所有 token 失效。"
        f"生产请设置环境变量 IELTS_BUDDY_JWT_SECRET",
        stacklevel=2,
    )
    return fallback


JWT_SECRET: Final[str] = _resolve_jwt_secret()
JWT_ALGORITHM: Final[str] = os.environ.get("IELTS_BUDDY_JWT_ALG", "HS256")
ACCESS_TOKEN_TTL_SECONDS: Final[int] = int(
    os.environ.get("IELTS_BUDDY_ACCESS_TTL", "3600")      # 1 小时
)
REFRESH_TOKEN_TTL_SECONDS: Final[int] = int(
    os.environ.get("IELTS_BUDDY_REFRESH_TTL", "604800")   # 7 天
)


def _resolve_admin_reset_token() -> str:
    """解析 admin reset 接口的预共享 token。

    - dev 环境：未设置时使用占位 ``dev-admin-token``，并 warn（方便本地开发）
    - prod 环境：未设置时抛 RuntimeError（拒绝启动不安全的服务）
    """
    secret = os.environ.get("IELTS_BUDDY_ADMIN_RESET_TOKEN", "").strip()
    if secret:
        return secret
    if os.environ.get("IELTS_BUDDY_ENV", "dev") == "prod":
        raise RuntimeError(
            "生产环境必须设置 IELTS_BUDDY_ADMIN_RESET_TOKEN "
            "（admin 重置密码接口的预共享密钥）"
        )
    fallback = "dev-admin-token"
    warnings.warn(
        "ADMIN_RESET_TOKEN 未设置，dev 环境使用占位 "
        f"{fallback!r}；生产环境必须设置独立长密钥。",
        stacklevel=2,
    )
    return fallback


ADMIN_RESET_TOKEN: Final[str] = _resolve_admin_reset_token()


# ===== Cookie =====

REFRESH_COOKIE_NAME: Final[str] = os.environ.get(
    "IELTS_BUDDY_REFRESH_COOKIE", "ib_refresh"
)
ACCESS_COOKIE_NAME: Final[str] = os.environ.get(
    "IELTS_BUDDY_ACCESS_COOKIE", "ib_access"
)
COOKIE_SECURE: Final[bool] = os.environ.get("IELTS_BUDDY_ENV", "dev") == "prod"
COOKIE_SAMESITE: Final[str] = os.environ.get(
    "IELTS_BUDDY_COOKIE_SAMESITE", "lax"
)


# ===== 数据库 =====

def _resolve_db_mode() -> str:
    """Web 端数据库模式。

    默认 ``sqlite``：账号与业务数据统一存于 ``~/.ielts-buddy/web_data.db``，
    零配置即可运行，重启服务不会丢账号（web_users 与业务表共存于同一文件）。

    生产环境通过环境变量 ``IELTS_BUDDY_WEB_DB_MODE=online`` 切换到 MySQL。
    """
    env = os.environ.get("IELTS_BUDDY_WEB_DB_MODE", "sqlite").strip().lower()
    if env in ("online", "mysql"):
        return "online"
    if env in ("sqlite", "memory"):
        return "sqlite"
    warnings.warn(
        f"IELTS_BUDDY_WEB_DB_MODE={env!r} 非法，回退到 sqlite",
        stacklevel=2,
    )
    return "sqlite"


WEB_DB_MODE: Final[str] = _resolve_db_mode()
WEB_DB_URL: Final[str] = os.environ.get("IELTS_BUDDY_WEB_DB_URL", "")


def get_web_db_path() -> str:
    """Web 端 SQLite 数据库路径（每次调用动态读取环境变量）。

    优先级：
    1. 环境变量 ``IELTS_BUDDY_WEB_SQLITE_PATH``
    2. ``~/.ielts-buddy/web_data.db``（与 CLI 的 ``data.db`` 物理隔离）
    """
    p = os.environ.get("IELTS_BUDDY_WEB_SQLITE_PATH", "").strip()
    if p:
        return p
    return str(Path("~/.ielts-buddy/web_data.db").expanduser())


# ===== CORS =====

CORS_ORIGINS: Final[tuple[str, ...]] = tuple(
    o.strip()
    for o in os.environ.get("IELTS_BUDDY_CORS_ORIGINS", "").split(",")
    if o.strip()
) or ("http://127.0.0.1:8000", "http://localhost:8000")


# ===== LLM (联网查词 / 文章翻译共用) =====

LLM_ENABLED: Final[bool] = bool(
    os.environ.get("IELTS_BUDDY_LLM_API_KEY", "").strip()
    or os.environ.get("IELTS_BUDDY_LLM_BASE_URL", "").strip()
)
LLM_API_KEY: Final[str] = os.environ.get("IELTS_BUDDY_LLM_API_KEY", "").strip()
LLM_BASE_URL: Final[str] = os.environ.get(
    "IELTS_BUDDY_LLM_BASE_URL", "https://api.minimaxi.com/v1"
)
LLM_MODEL: Final[str] = os.environ.get(
    "IELTS_BUDDY_LLM_MODEL", "MiniMax-M2.7-highspeed"
)
LLM_TIMEOUT_SECONDS: Final[float] = float(
    os.environ.get("IELTS_BUDDY_LLM_TIMEOUT", "30")
)
# dry-run 模式：未设置 API key 时，返回 mock 数据，让前端能正常显示
LLM_DRY_RUN: Final[bool] = not bool(LLM_API_KEY)


__all__ = [
    "WEB_HOST",
    "WEB_PORT",
    "JWT_SECRET",
    "JWT_ALGORITHM",
    "ACCESS_TOKEN_TTL_SECONDS",
    "REFRESH_TOKEN_TTL_SECONDS",
    "ADMIN_RESET_TOKEN",
    "REFRESH_COOKIE_NAME",
    "COOKIE_SECURE",
    "COOKIE_SAMESITE",
    "WEB_DB_MODE",
    "WEB_DB_URL",
    "get_web_db_path",
    "CORS_ORIGINS",
]
