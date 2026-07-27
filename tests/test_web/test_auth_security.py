"""密码哈希 + JWT 单测。"""
from __future__ import annotations

import time

import jwt
import pytest

from ielts_buddy.web import config as web_config
from ielts_buddy.web.auth.security import (
    AUDIENCE_ACCESS,
    AUDIENCE_REFRESH,
    ISSUER,
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


# =============================================================
# 密码
# =============================================================


def test_hash_password_not_equal_to_plain() -> None:
    """哈希结果 ≠ 明文。"""
    h = hash_password("hello")
    assert h != "hello"
    assert h.startswith("$2")  # bcrypt 前缀


def test_hash_password_random_salt() -> None:
    """同密码两次哈希结果不同（bcrypt salt 随机）。"""
    h1 = hash_password("hello")
    h2 = hash_password("hello")
    assert h1 != h2


def test_verify_password_correct() -> None:
    h = hash_password("hello")
    assert verify_password("hello", h) is True


def test_verify_password_wrong() -> None:
    h = hash_password("hello")
    assert verify_password("world", h) is False


def test_verify_password_empty() -> None:
    """空密码 / 空哈希都返回 False（不抛异常）。"""
    h = hash_password("hello")
    assert verify_password("", h) is False
    assert verify_password("hello", "") is False


def test_hash_password_empty_raises() -> None:
    """空密码抛 ValueError。"""
    with pytest.raises(ValueError):
        hash_password("")


def test_hash_password_truncates_long_input() -> None:
    """> 72 字节的密码截断后仍能验证。"""
    long_pw = "x" * 100
    h = hash_password(long_pw)
    # 同 100 字符密码应能验证通过
    assert verify_password(long_pw, h) is True
    # 截断 72 字节的不同后缀也通过
    assert verify_password("x" * 72, h) is True


# =============================================================
# JWT
# =============================================================


def test_access_token_decodes() -> None:
    token = create_access_token(42, "alice@example.com")
    payload = decode_token(token, expected_audience=AUDIENCE_ACCESS)
    assert payload["sub"] == "42"
    assert payload["email"] == "alice@example.com"
    assert payload["aud"] == AUDIENCE_ACCESS
    assert payload["iss"] == ISSUER
    assert "exp" in payload
    assert "iat" in payload
    assert "jti" in payload


def test_refresh_token_decodes() -> None:
    token = create_refresh_token(42)
    payload = decode_token(token, expected_audience=AUDIENCE_REFRESH)
    assert payload["sub"] == "42"
    assert payload["aud"] == AUDIENCE_REFRESH
    # refresh token 不带 email
    assert "email" not in payload


def test_access_token_wrong_audience() -> None:
    """access token 错用 audience=refresh 解码会失败。"""
    token = create_access_token(42, "alice@example.com")
    with pytest.raises(InvalidTokenError):
        decode_token(token, expected_audience=AUDIENCE_REFRESH)


def test_refresh_token_wrong_audience() -> None:
    """refresh token 错用 audience=access 解码会失败。"""
    token = create_refresh_token(42)
    with pytest.raises(InvalidTokenError):
        decode_token(token, expected_audience=AUDIENCE_ACCESS)


def test_token_tampered_signature() -> None:
    """篡改 token（最后 4 位）应解码失败。"""
    token = create_access_token(42, "alice@example.com")
    tampered = token[:-4] + ("x" if token[-1] != "x" else "y") * 4
    with pytest.raises(InvalidTokenError):
        decode_token(tampered, expected_audience=AUDIENCE_ACCESS)


def test_token_wrong_secret() -> None:
    """用错误 secret 签的 token 校验失败。"""
    bad = jwt.encode(
        {"sub": "1", "aud": AUDIENCE_ACCESS, "iss": ISSUER,
         "iat": int(time.time()), "exp": int(time.time()) + 60},
        "wrong-secret",
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        decode_token(bad, expected_audience=AUDIENCE_ACCESS)


def test_token_expired() -> None:
    """TTL=1 秒的 token 等过期后解码抛 TokenExpiredError。"""
    token = create_access_token(42, "alice@example.com", ttl_seconds=1)
    time.sleep(1.5)
    with pytest.raises(TokenExpiredError):
        decode_token(token, expected_audience=AUDIENCE_ACCESS)


def test_token_missing_required_claim() -> None:
    """缺 exp 的 token 校验失败。"""
    bad = jwt.encode(
        {"sub": "1", "aud": AUDIENCE_ACCESS, "iss": ISSUER, "iat": int(time.time())},
        web_config.JWT_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        decode_token(bad, expected_audience=AUDIENCE_ACCESS)
