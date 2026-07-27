"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """注册请求体。"""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    """登录请求体。"""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """刷新 access token 的请求体。

    注：阶段 1 约定 refresh token 走 HttpOnly Cookie，body 留空兼容未来扩展。
    """


class UserResponse(BaseModel):
    """当前用户响应。"""

    id: int
    email: str
    created_at: str | None = None
    last_login_at: str | None = None


class TokenResponse(BaseModel):
    """登录/刷新返回的 token 响应。

    access_token 始终在 body 里，refresh_token 既可能在 body（API 客户端），
    也可能只在 Set-Cookie（Web 前端）。为简化，前端统一从 body 拿 access_token；
    Set-Cookie 同步下发 refresh_token。
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access_token 剩余秒数
    user: UserResponse


class AuthErrorResponse(BaseModel):
    """认证错误响应。"""

    detail: str
    code: str  # INVALID_CREDENTIALS / EMAIL_TAKEN / TOKEN_INVALID / ...


__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "UserResponse",
    "TokenResponse",
    "AuthErrorResponse",
]
