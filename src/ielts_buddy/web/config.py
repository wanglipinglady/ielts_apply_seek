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
    """Web 端数据库模式（v3：默认 online，自动 fallback 到 sqlite）。

    默认 ``online``：连远程 MySQL（118.190.148.121:3306/ietls_learn_online）。
    启动时尝试连接 MySQL：
      - 成功 → app.state.mode = "online"
      - 失败 → 自动降级到本地 SQLite（~/.ielts-buddy/ielts_buddy.db）

    通过环境变量 ``IELTS_BUDDY_WEB_DB_MODE`` 可强制指定模式：
      - ``online`` / ``mysql`` → 远程 MySQL（默认）
      - ``sqlite`` / ``memory`` → 强制本地 SQLite
    """
    env = os.environ.get("IELTS_BUDDY_WEB_DB_MODE", "online").strip().lower()
    if env in ("online", "mysql"):
        return "online"
    if env in ("sqlite", "memory"):
        return "sqlite"
    warnings.warn(
        f"IELTS_BUDDY_WEB_DB_MODE={env!r} 非法，回退到 online",
        stacklevel=2,
    )
    return "online"


WEB_DB_MODE: Final[str] = _resolve_db_mode()
WEB_DB_URL: Final[str] = os.environ.get("IELTS_BUDDY_WEB_DB_URL", "")


def get_web_db_path() -> str:
    """Web 端 SQLite 数据库路径（v3：与 CLI 共用同一个文件）。

    优先级：
    1. 环境变量 ``IELTS_BUDDY_WEB_SQLITE_PATH``
    2. ``~/.ielts-buddy/ielts_buddy.db``（v3：CLI 与 Web 共用）
       （老版本叫 ``web_data.db``，仍存在作为 fallback 缓存）
    """
    p = os.environ.get("IELTS_BUDDY_WEB_SQLITE_PATH", "").strip()
    if p:
        return p
    return str(Path("~/.ielts-buddy/ielts_buddy.db").expanduser())


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


def _env_bool(key: str, default: bool) -> bool:
    """读环境变量解析为 bool。
    接受 1/true/yes/on(大小写不敏感)→ True;其它→ False。
    缺失或空串时回退到 default。
    """
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# =============================================================
# v3.7 P1：口语对练 Whisper.cpp 配置
# =============================================================
# 模型:small.en / base.en / tiny.en / small / base
# PRD 决策:选 small.en(英文优化版,M4 + Core ML 30s 音频 ~5s 内的转写精度)
WHISPER_MODEL: Final[str] = os.environ.get("IELTS_BUDDY_WHISPER_MODEL", "small.en").strip()
# 语种:MVP 强制 en(雅思口语只有英文)
WHISPER_LANGUAGE: Final[str] = os.environ.get("IELTS_BUDDY_WHISPER_LANGUAGE", "en").strip()
# Core ML 加速(Apple Silicon ANE;非 M 系列自动忽略)
WHISPER_CORE_ML: Final[bool] = _env_bool("IELTS_BUDDY_WHISPER_CORE_ML", True)
# CPU 推理线程数(M4 8 核建议 4;数据库读写密集时可降)
WHISPER_THREADS: Final[int] = int(os.environ.get("IELTS_BUDDY_WHISPER_THREADS", "4").strip() or "4")
# 录音保留天数;web 启动期会同步触发一次清理(PRD §5.6)
SPEAKING_AUDIO_RETENTION_DAYS: Final[int] = int(
    os.environ.get("IELTS_BUDDY_SPEAKING_AUDIO_RETENTION_DAYS", "7").strip() or "7"
)
# 单次录音长度上限(秒)
SPEAKING_MAX_DURATION_SEC: Final[int] = int(
    os.environ.get("IELTS_BUDDY_SPEAKING_MAX_DURATION_SEC", "120").strip() or "120"
)


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
    "WHISPER_MODEL",
    "WHISPER_LANGUAGE",
    "WHISPER_CORE_ML",
    "WHISPER_THREADS",
    "SPEAKING_AUDIO_RETENTION_DAYS",
    "SPEAKING_MAX_DURATION_SEC",
]
