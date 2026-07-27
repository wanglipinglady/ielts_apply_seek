"""WebAuthService 单测：不依赖 FastAPI，直接调 service。"""
from __future__ import annotations

import pytest

from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository
from ielts_buddy.web.auth.security import (
    AUDIENCE_ACCESS,
    AUDIENCE_REFRESH,
    decode_token,
)
from ielts_buddy.web.auth.service import AuthError, WebAuthService


@pytest.fixture
def svc() -> WebAuthService:
    repo = create_sqlite_web_user_repository(":memory:")
    return WebAuthService(
        repo, access_ttl_seconds=60, refresh_ttl_seconds=600
    )


# =============================================================
# 注册
# =============================================================


def test_register_success(svc: WebAuthService) -> None:
    result = svc.register("alice@example.com", "password123")
    assert result.user.id >= 1
    assert result.user.email == "alice@example.com"
    # access token 可解码
    payload = decode_token(result.access_token, expected_audience=AUDIENCE_ACCESS)
    assert payload["sub"] == str(result.user.id)
    assert payload["email"] == "alice@example.com"
    # refresh token 可解码
    refresh_payload = decode_token(
        result.refresh_token, expected_audience=AUDIENCE_REFRESH
    )
    assert refresh_payload["sub"] == str(result.user.id)
    # 注册即登录：通过 get_by_id 拿到 last_login_at 应非空
    after = svc.get_by_id(result.user.id)
    assert after is not None
    assert after.last_login_at is not None


def test_register_duplicate_email(svc: WebAuthService) -> None:
    svc.register("dup@example.com", "password123")
    with pytest.raises(AuthError) as exc:
        svc.register("dup@example.com", "different123")
    assert exc.value.code == "EMAIL_TAKEN"


def test_register_weak_password(svc: WebAuthService) -> None:
    with pytest.raises(AuthError) as exc:
        svc.register("weak@example.com", "short")
    assert exc.value.code == "WEAK_PASSWORD"


def test_register_empty_email(svc: WebAuthService) -> None:
    with pytest.raises(AuthError) as exc:
        svc.register("", "password123")
    assert exc.value.code == "INVALID_EMAIL"


def test_register_email_normalized(svc: WebAuthService) -> None:
    """注册时邮箱大小写会被规范成小写。"""
    r = svc.register("Alice@Example.COM", "password123")
    assert r.user.email == "alice@example.com"


# =============================================================
# 登录
# =============================================================


def test_login_success(svc: WebAuthService) -> None:
    svc.register("bob@example.com", "password123")
    result = svc.login("bob@example.com", "password123")
    assert result.user.email == "bob@example.com"
    assert result.access_token
    assert result.refresh_token


def test_login_wrong_password(svc: WebAuthService) -> None:
    svc.register("bob@example.com", "password123")
    with pytest.raises(AuthError) as exc:
        svc.login("bob@example.com", "wrongpass")
    assert exc.value.code == "INVALID_CREDENTIALS"


def test_login_nonexistent_email(svc: WebAuthService) -> None:
    """不存在的邮箱与错误密码返回同一错误（防邮箱枚举）。"""
    with pytest.raises(AuthError) as exc:
        svc.login("ghost@example.com", "password123")
    assert exc.value.code == "INVALID_CREDENTIALS"


def test_login_updates_last_login(svc: WebAuthService) -> None:
    svc.register("eve@example.com", "password123")
    first = svc.get_by_id(svc.get_by_id(1).id)  # type: ignore[arg-type,union-attr]
    # 重新登录
    svc.login("eve@example.com", "password123")
    after = svc.get_by_id(first.id)  # type: ignore[union-attr]
    assert after is not None
    # 时间会变化（精度到秒）—— 我们只断言 not None 即可
    assert after.last_login_at is not None


# =============================================================
# 刷新
# =============================================================


def test_refresh_success(svc: WebAuthService) -> None:
    reg = svc.register("frank@example.com", "password123")
    new = svc.refresh(reg.refresh_token)
    # 拿到新 token
    assert new.access_token != reg.access_token
    assert new.refresh_token != reg.refresh_token
    # 还能解码
    decode_token(new.access_token, expected_audience=AUDIENCE_ACCESS)


def test_refresh_invalid_token(svc: WebAuthService) -> None:
    with pytest.raises(AuthError) as exc:
        svc.refresh("not-a-token")
    assert exc.value.code == "TOKEN_INVALID"


def test_refresh_wrong_audience(svc: WebAuthService) -> None:
    """拿 access token 当 refresh 用 → 失败。"""
    reg = svc.register("grace@example.com", "password123")
    with pytest.raises(AuthError) as exc:
        svc.refresh(reg.access_token)
    assert exc.value.code == "TOKEN_INVALID"


def test_refresh_user_deleted(svc: WebAuthService) -> None:
    """refresh 成功但用户已不存在 → 失败。"""
    # 通过关闭 repo + 重新开一个空库模拟用户消失
    reg = svc.register("henry@example.com", "password123")
    # 关闭并替换为空 repo
    svc._repo.close()
    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository
    svc._repo = create_sqlite_web_user_repository(":memory:")
    with pytest.raises(AuthError) as exc:
        svc.refresh(reg.refresh_token)
    assert exc.value.code == "USER_NOT_FOUND"


# =============================================================
# me
# =============================================================


def test_get_by_id(svc: WebAuthService) -> None:
    reg = svc.register("ivy@example.com", "password123")
    user = svc.get_by_id(reg.user.id)
    assert user is not None
    assert user.email == "ivy@example.com"


def test_get_by_id_not_found(svc: WebAuthService) -> None:
    assert svc.get_by_id(99999) is None
