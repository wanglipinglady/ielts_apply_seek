"""密码哈希 + JWT 签发/校验。

设计要点：
1. **密码**用 bcrypt（直接用 bcrypt 库，不走 passlib —— passlib 已停止维护，
   1.7.4 与 bcrypt 4.x+ 不兼容）。
2. **JWT**用 PyJWT，HS256。access / refresh 走不同 `aud` 字段区分用途，
   避免 access token 被误用作 refresh。
3. **异常**显式化：`InvalidTokenError` / `TokenExpiredError` 让上层精确捕获。

不依赖 DB / FastAPI，方便单测。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Final

import bcrypt
import jwt

from ielts_buddy.web import config as web_config


# =============================================================
# 1. 密码哈希
# =============================================================

# bcrypt 限制 ≤ 72 字节；超出截断（与历史习惯一致，不在业务层做长度限制）
_BCRYPT_MAX_BYTES: Final[int] = 72


def hash_password(plain_password: str) -> str:
    """对明文密码做 bcrypt 哈希，返回可直接存库的字符串。"""
    if not plain_password:
        raise ValueError("password 不能为空")
    # bcrypt 4.x+ 严格限制 72 字节；超长截断
    raw = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """校验明文 vs 存储哈希。不抛异常；不匹配返回 False。

    异常（hash 格式非法）会被吞掉，记 False，调用方据此判断登录失败。
    """
    if not plain_password or not password_hash:
        return False
    try:
        raw = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# =============================================================
# 2. JWT 签发 / 校验
# =============================================================

# 区分 access / refresh 的 audience 字段
AUDIENCE_ACCESS: Final[str] = "ielts-buddy:access"
AUDIENCE_REFRESH: Final[str] = "ielts-buddy:refresh"
ISSUER: Final[str] = "ielts-buddy-web"


class InvalidTokenError(Exception):
    """JWT 校验失败（签名错、audience 错、格式错等）。"""


class TokenExpiredError(InvalidTokenError):
    """JWT 已过期。"""


def _now() -> datetime:
    """当前 UTC 时间（带 tzinfo，避免 jwt 库 PyJWT 2.10+ 警告）。"""
    return datetime.now(timezone.utc)


def _encode(
    *,
    subject: str,
    audience: str,
    ttl_seconds: int,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发 JWT。"""
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iss": ISSUER,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": secrets.token_urlsafe(8),  # 唯一标识，便于以后做黑名单
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        web_config.JWT_SECRET,
        algorithm=web_config.JWT_ALGORITHM,
    )


def create_access_token(
    user_id: int,
    email: str,
    *,
    ttl_seconds: int | None = None,
) -> str:
    """签发 access token（默认 TTL 1 小时）。"""
    return _encode(
        subject=str(user_id),
        audience=AUDIENCE_ACCESS,
        ttl_seconds=ttl_seconds or web_config.ACCESS_TOKEN_TTL_SECONDS,
        extra_claims={"email": email},
    )


def create_refresh_token(
    user_id: int,
    *,
    ttl_seconds: int | None = None,
) -> str:
    """签发 refresh token（默认 TTL 7 天）。"""
    return _encode(
        subject=str(user_id),
        audience=AUDIENCE_REFRESH,
        ttl_seconds=ttl_seconds or web_config.REFRESH_TOKEN_TTL_SECONDS,
    )


def decode_token(token: str, *, expected_audience: str) -> dict[str, Any]:
    """校验 token 并返回 payload。"""
    try:
        payload = jwt.decode(
            token,
            web_config.JWT_SECRET,
            algorithms=[web_config.JWT_ALGORITHM],
            audience=expected_audience,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
        return payload
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError("token 已过期") from e
    except jwt.InvalidTokenError as e:
        raise InvalidTokenError(f"token 无效: {e}") from e


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "InvalidTokenError",
    "TokenExpiredError",
    "AUDIENCE_ACCESS",
    "AUDIENCE_REFRESH",
    "ISSUER",
]
