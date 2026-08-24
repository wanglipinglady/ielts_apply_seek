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


class ChangePasswordRequest(BaseModel):
    """用户自助改密请求体。"""
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordResponse(BaseModel):
    """用户自助改密响应（仅返回 ok，不返回新密码明文）。"""
    ok: bool = True


class ResetPasswordRequest(BaseModel):
    """管理员重置密码请求体（按 email 重置）。"""
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    """用户自助「忘记密码」请求体（无需登录态）。

    注意：当前实现是简化版——用户提交邮箱，系统直接把该账号密码
    重置为默认密码 ``12345678``，并把明文一次性返回给调用方。
    这是**不安全**的设计（任何知道邮箱的人都能重置），仅用于
    本地 dev / 单用户场景。生产应走「邮件验证码」流程。
    """

    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """用户自助重置响应（一次性返回默认明文密码）。"""

    email: str
    new_password: str  # 固定默认值 "12345678"
    user_id: int


class ResetPasswordResponse(BaseModel):
    """管理员重置密码响应：**一次性返回新明文密码**，调用方需立即保存。

    安全注意：
    - 这是**只此一次**的机会显示明文密码
    - 响应到达客户端后，服务器端**不保留**明文密码（只存 bcrypt hash）
    - 丢失 = 需再次重置
    """
    email: str
    new_password: str  # 8-12 位随机生成的明文密码
    user_id: int


class WxLoginRequest(BaseModel):
    """微信小程序登录请求（v3.9+ / 2026-08-24 新增）。

    字段：
    - code: 微信 wx.login() 返回的临时凭证，**5 分钟有效**
    - nickname: 可选，用户昵称（用于初始化 display_name）
    - avatar_url: 可选，用户头像 URL
    """

    code: str = Field(min_length=1, max_length=512)
    nickname: str | None = Field(default=None, max_length=64)
    avatar_url: str | None = Field(default=None, max_length=512)


class WxLoginResponse(BaseModel):
    """微信小程序登录响应。

    与 TokenResponse 同 schema（统一字段名，三端共享），
    但额外带 ``is_new_user`` 标记小程序首登 vs 老用户。
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
    is_new_user: bool  # 小程序前端决定要不要弹"欢迎"提示


__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "UserResponse",
    "TokenResponse",
    "AuthErrorResponse",
    "ChangePasswordRequest",
    "ChangePasswordResponse",
    "ResetPasswordRequest",
    "ResetPasswordResponse",
    "ForgotPasswordRequest",
    "ForgotPasswordResponse",
    "WxLoginRequest",
    "WxLoginResponse",
]
