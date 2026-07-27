"""Web 端业务服务：注册 / 登录 / 刷新 / me / 登出。

注意：service 层不感知 FastAPI，方便单测。
"""
from __future__ import annotations

from dataclasses import dataclass

from ielts_buddy.web.auth.repository import (
    WebUser,
    WebUserRepository,
    WebUserEmailConflictError,
    WebUserNotFoundError,
)
from ielts_buddy.web.auth.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)


# =============================================================
# 异常 / 错误码
# =============================================================


class AuthError(Exception):
    """认证业务异常：包含 code + 人类可读 message。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# =============================================================
# 登录结果
# =============================================================


@dataclass
class LoginResult:
    user: WebUser
    access_token: str
    refresh_token: str
    expires_in: int  # access token 剩余秒数


# =============================================================
# Service
# =============================================================


class WebAuthService:
    """Web 端认证业务编排。

    接受 ``WebUserRepository`` 注入。Repository 是 Protocol，便于换 MySQL 实现。
    """

    def __init__(
        self,
        repo: WebUserRepository,
        *,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
    ) -> None:
        self._repo = repo
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    # ---- 注册 ----

    def register(self, email: str, password: str) -> LoginResult:
        """注册并自动登录（成功直接返回 token 集合，避免前端再来一次登录）。"""
        email_norm = email.strip().lower()
        if not email_norm:
            raise AuthError("INVALID_EMAIL", "邮箱不能为空")
        if len(password) < 8:
            raise AuthError("WEAK_PASSWORD", "密码至少 8 位")

        pw_hash = hash_password(password)
        try:
            user = self._repo.create(email_norm, pw_hash)
        except WebUserEmailConflictError as e:
            raise AuthError("EMAIL_TAKEN", str(e)) from e

        # 注册即登录：更新 last_login_at
        self._repo.update_last_login(user.id)

        return self._build_login_result(user)

    # ---- 登录 ----

    def login(self, email: str, password: str) -> LoginResult:
        """校验邮箱+密码，返回 token 集合。

        邮箱不存在 / 密码错误都返回同一个 ``INVALID_CREDENTIALS``，避免
        邮箱枚举攻击。
        """
        user = self._repo.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise AuthError("INVALID_CREDENTIALS", "邮箱或密码错误")

        self._repo.update_last_login(user.id)
        return self._build_login_result(user)

    # ---- 刷新 ----

    def refresh(self, refresh_token: str) -> LoginResult:
        """用 refresh token 换新 access + refresh。

        实现：解析 refresh token（已在路由层校验过合法性），用 sub 查 user，
        重新签发两把 token。
        """
        # 注意：调用方已经在路由层 decode_token 校验过 audience/expiry；
        # service 层只取 sub 查 user。
        from ielts_buddy.web.auth.security import (
            decode_token,
            AUDIENCE_REFRESH,
            InvalidTokenError,
        )

        try:
            payload = decode_token(refresh_token, expected_audience=AUDIENCE_REFRESH)
        except InvalidTokenError as e:
            raise AuthError("TOKEN_INVALID", str(e)) from e

        try:
            user_id = int(payload["sub"])
        except (KeyError, TypeError, ValueError) as e:
            raise AuthError("TOKEN_INVALID", "refresh token 缺少 sub") from e

        user = self._repo.get_by_id(user_id)
        if user is None:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

        return self._build_login_result(user)

    # ---- me ----

    def get_by_id(self, user_id: int) -> WebUser | None:
        """便捷：取当前用户。"""
        return self._repo.get_by_id(user_id)

    # ---- 内部 ----

    def _build_login_result(self, user: WebUser) -> LoginResult:
        access = create_access_token(
            user.id, user.email, ttl_seconds=self._access_ttl
        )
        refresh = create_refresh_token(user.id, ttl_seconds=self._refresh_ttl)
        return LoginResult(
            user=user,
            access_token=access,
            refresh_token=refresh,
            expires_in=self._access_ttl,
        )


__all__ = [
    "WebAuthService",
    "AuthError",
    "LoginResult",
]
