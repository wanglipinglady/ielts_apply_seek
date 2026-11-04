"""Web 端配置：仅读环境变量，不与 CLI config.toml 共享。

CLI 用户的配置通过 ~/.ielts-buddy/config.toml；
Web 用户的配置通过进程环境变量（生产用 systemd EnvironmentFile，
开发用 .env）。
"""

from __future__ import annotations

import logging
import os
import secrets
import warnings
from pathlib import Path
from typing import Final


logger = logging.getLogger(__name__)


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


# ===== 微信小程序登录（v3.9+ / 2026-08-24 新增）=====

# 微信小程序 AppID / AppSecret，用于 code2session 校验
WECHAT_APPID: Final[str] = os.environ.get("IELTS_BUDDY_WECHAT_APPID", "").strip()
WECHAT_SECRET: Final[str] = os.environ.get("IELTS_BUDDY_WECHAT_SECRET", "").strip()

# code2session 端点（官方）
# 文档：https://developers.weixin.qq.com/miniprogram/dev/api-backend/open-api/login/auth.code2Session.html
WECHAT_CODE2SESSION_URL: Final[str] = (
    "https://api.weixin.qq.com/sns/jscode2session"
)

# dev 模式开关：dev 下允许前端传 mock openid，prod 必须真实走 code2session
# 避免 prod 环境因配置不全而把"假用户"写进生产库
WECHAT_DEV_ALLOW_MOCK: Final[bool] = (
    os.environ.get("IELTS_BUDDY_ENV", "dev") != "prod"
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


def _validate_llm_api_key(raw: str) -> tuple[str, str]:
    """校验 LLM API key 是否是"占位符 / 被截断"的值。

    生产事故复盘（2026-11-04 文章翻译 401）：
    ``.env`` 与 systemd EnvironmentFile 里的 key 被误写成 9 字符占位符，
    而配置层只判断"非空" → ``LLM_ENABLED=True`` → 每次调用都返回
    401 authorized_error → 前端把原始报错塞进翻译正文，
    用户完全看不出是"配置写坏了"。

    这里在启动时就识别明显不可用的 key 并**大声告警**（不抛异常：
    LLM 坏掉不应该让登录 / 学习等无关功能一起挂掉），
    结论写进 ``LLM_STATUS``，由 ``/healthz`` 暴露给运维。

    Returns:
        (清洗后的 key, 可疑原因；无问题时原样返回 + 空字符串)
    """
    key = raw.strip()
    if not key:
        return key, ""

    reasons: list[str] = []
    if len(key) < 32:
        reasons.append(f"长度仅 {len(key)} 字符")
    if "..." in key or "\u2026" in key:
        reasons.append("含省略号（占位符特征）")
    if not reasons:
        return key, ""

    reason = "；".join(reasons)
    msg = (
        f"IELTS_BUDDY_LLM_API_KEY 疑似无效（{reason}）。"
        "所有 LLM 调用都会 401 authorized_error，"
        "请修正 .env / systemd EnvironmentFile 里的 key 后重启服务。"
    )
    if os.environ.get("IELTS_BUDDY_ENV", "dev") == "prod":
        logger.error(msg)
    else:
        warnings.warn(msg, stacklevel=2)
    return key, reason


LLM_API_KEY, _LLM_KEY_SUSPECT = _validate_llm_api_key(
    os.environ.get("IELTS_BUDDY_LLM_API_KEY", "")
)
LLM_ENABLED: Final[bool] = bool(
    LLM_API_KEY or os.environ.get("IELTS_BUDDY_LLM_BASE_URL", "").strip()
)
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

# LLM 就绪状态（供 /healthz 暴露，运维不用点按钮试就知道 key 坏没坏）
LLM_STATUS: Final[dict] = {
    "configured": bool(LLM_API_KEY),
    "key_length": len(LLM_API_KEY),
    "key_suspect": _LLM_KEY_SUSPECT,
    "model": LLM_MODEL,
    "base_url": LLM_BASE_URL,
    "dry_run": LLM_DRY_RUN,
}

# v4.0：阅读出题专用超时。
# 出题是"长输出"任务（3 篇 passage + 10-14 道题），线上实测单次 ~41s；
# 而通用 LLM_TIMEOUT_SECONDS 默认 30s → 出题必然 "Request timed out" 降级到 mock。
# 这里给阅读出题单独放宽到 180s（MiniMax 侧不会因此变慢，超时只是上限）。
READING_LLM_TIMEOUT_SECONDS: Final[float] = float(
    os.environ.get("IELTS_BUDDY_READING_LLM_TIMEOUT", "180")
)


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
# v4.0：生产服务器的 whisper 模型
#   - 服务器连不上 huggingface.co（Network is unreachable），模型只能走
#     ModelScope 镜像下载：
#       https://modelscope.cn/models/KBLab/kb-whisper-small/resolve/master/ggml-model.bin
#     → 放到 /root/.local/share/pywhispercpp/models/ggml-small.en.bin
#   - tiny.en（77MB）精度不够（"Good morning" 会转成 "Got morning"），
#     所以用 small.en（487MB），已实测下载并转写成功
#   - 本地 Mac 开发也用 small.en
WHISPER_MODEL: Final[str] = os.environ.get(
    "IELTS_BUDDY_WHISPER_MODEL", "small-multi"
).strip()
# whisper ggml 模型存放目录（pywhispercpp 默认 ~/.local/share/pywhispercpp/models）
WHISPER_MODELS_DIR: Final[str] = os.environ.get(
    "IELTS_BUDDY_WHISPER_MODELS_DIR",
    "/root/.local/share/pywhispercpp/models",
).strip()
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

# v3.7 P2 真·听力题库配置
#
# v4.0 修正：初版用的是 chat.completions + modalities=["text","audio"]，
# 但 MiniMax 的 chat 端点**不支持音频模态**，线上一直报
#   'Chat' object has no attribute 'post'
#   unknown model 'speech-01'
# 现在改用 MiniMax 私有的 T2A v2 端点 POST {base}/t2a_v2。
# 线上实测可用：
#   model=speech-02-hd, voice_id=English_Trustworth_Man → 返回 hex mp3
#   （旧默认 male-en-1 在当前账号下不存在，会返回 "voice id not exist"）
TTS_VOICE: Final[str] = os.environ.get(
    "IELTS_BUDDY_TTS_VOICE", "English_Trustworth_Man"
).strip()
TTS_MODEL: Final[str] = os.environ.get("IELTS_BUDDY_TTS_MODEL", "speech-02-hd").strip()
# T2A v2 端点基址（不含 /t2a_v2 路径后缀）
TTS_API_BASE: Final[str] = os.environ.get(
    "IELTS_BUDDY_TTS_API_BASE", "https://api.minimaxi.com/v1"
).strip()
TTS_TIMEOUT_SECONDS: Final[float] = float(
    os.environ.get("IELTS_BUDDY_TTS_TIMEOUT", "60")
)
# 听力音频保留天数(默认 30;启动期同步清理)
LISTENING_AUDIO_RETENTION_DAYS: Final[int] = int(
    os.environ.get("IELTS_BUDDY_LISTENING_AUDIO_RETENTION_DAYS", "30").strip() or "30"
)
# 启动期是否自动种子题库(默认 True;False 用于测试)
LISTENING_AUTO_SEED: Final[bool] = _env_bool("IELTS_BUDDY_LISTENING_AUTO_SEED", True)
# 启动期每个 Section 种子套数(默认 10/8/7/5 = 30 套)
LISTENING_SEED_S1: Final[int] = int(os.environ.get("IELTS_BUDDY_LISTENING_SEED_S1", "10").strip() or "10")
LISTENING_SEED_S2: Final[int] = int(os.environ.get("IELTS_BUDDY_LISTENING_SEED_S2", "8").strip() or "8")
LISTENING_SEED_S3: Final[int] = int(os.environ.get("IELTS_BUDDY_LISTENING_SEED_S3", "7").strip() or "7")
LISTENING_SEED_S4: Final[int] = int(os.environ.get("IELTS_BUDDY_LISTENING_SEED_S4", "5").strip() or "5")


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
    "WHISPER_MODELS_DIR",
    "WHISPER_LANGUAGE",
    "WHISPER_CORE_ML",
    "WHISPER_THREADS",
    "SPEAKING_AUDIO_RETENTION_DAYS",
    "SPEAKING_MAX_DURATION_SEC",
    # v3.7 P2
    "TTS_VOICE",
    "TTS_MODEL",
    "TTS_API_BASE",
    "TTS_TIMEOUT_SECONDS",
    "READING_LLM_TIMEOUT_SECONDS",
    "LISTENING_AUDIO_RETENTION_DAYS",
    "LISTENING_AUTO_SEED",
    "LISTENING_SEED_S1",
    "LISTENING_SEED_S2",
    "LISTENING_SEED_S3",
    "LISTENING_SEED_S4",
]
