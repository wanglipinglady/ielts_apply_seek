"""FastAPI 依赖：当前用户、auth service 实例、refresh cookie 解析。

设计：
1. ``get_web_auth_service()``：从 app.state 取仓库（由 ``create_app`` 注入），
   构造 ``WebAuthService``。每个请求重新构造 service（service 是无状态壳），
   仓库本身在 app 启动时打开、关闭时释放。
2. ``get_current_user()``：强制要求 access token。缺 / 错 / 过期一律 401。
3. ``get_current_user_optional()``：可选登录态；解析失败返回 None，用于首页
   这类公开页面判"已登录显示用户名，未登录显示登录入口"。
4. ``get_refresh_token_from_cookie()``：从 HttpOnly Cookie 拿 refresh token，
   refresh 路由专用。
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ielts_buddy.web import config as web_config
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.auth.schemas import UserResponse
from ielts_buddy.web.auth.security import (
    AUDIENCE_ACCESS,
    InvalidTokenError,
    TokenExpiredError,
    decode_token,
)
from ielts_buddy.web.auth.service import WebAuthService


# Bearer token 自动处理（auto_error=False 让 401 走我们自己的文案）
_bearer_scheme = HTTPBearer(auto_error=False)


def _get_access_token_from_request(
    credentials: Optional[HTTPAuthorizationCredentials],
    request: Request,
) -> Optional[str]:
    """从 Authorization 头或 access cookie 获取 access token。"""
    # 优先从 Authorization 头获取
    if credentials and credentials.credentials:
        return credentials.credentials
    # 降级：从 access cookie 获取（用于浏览器页面导航场景）
    access_cookie = request.cookies.get(web_config.ACCESS_COOKIE_NAME)
    if access_cookie:
        return access_cookie
    return None


def get_web_auth_service(request: Request) -> WebAuthService:
    """从 app.state 取仓储，构造 service。

    ``create_app`` 必须先把 repo 挂到 ``app.state.web_user_repo``。
    """
    repo = getattr(request.app.state, "web_user_repo", None)
    if repo is None:
        raise RuntimeError(
            "app.state.web_user_repo 未初始化；检查 create_app()"
        )
    return WebAuthService(
        repo,
        access_ttl_seconds=web_config.ACCESS_TOKEN_TTL_SECONDS,
        refresh_ttl_seconds=web_config.REFRESH_TOKEN_TTL_SECONDS,
    )


def _unauthorized(detail: str = "未登录或登录已失效") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(_bearer_scheme)
    ] = None,
    request: Request = None,
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)] = None,
) -> WebUser:
    """强制登录依赖。缺 token / token 无效 / 用户不存在都 401。"""
    token = _get_access_token_from_request(credentials, request)
    if not token:
        raise _unauthorized("缺少 Authorization 头或 access cookie")
    try:
        payload = decode_token(token, expected_audience=AUDIENCE_ACCESS)
    except TokenExpiredError as e:
        raise _unauthorized("token 已过期") from e
    except InvalidTokenError as e:
        raise _unauthorized(f"token 无效: {e}") from e

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as e:
        raise _unauthorized("token 缺少 sub 字段") from e

    user = svc.get_by_id(user_id)
    if user is None:
        raise _unauthorized("用户不存在")
    return user


def get_current_user_optional(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(_bearer_scheme)
    ] = None,
    request: Request = None,
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)] = None,
) -> Optional[WebUser]:
    """可选登录态：解析失败返回 None，调用方按需展示。"""
    token = _get_access_token_from_request(credentials, request)
    if not token:
        return None
    try:
        payload = decode_token(token, expected_audience=AUDIENCE_ACCESS)
        user_id = int(payload["sub"])
    except (InvalidTokenError, TokenExpiredError, KeyError, TypeError, ValueError):
        return None
    return svc.get_by_id(user_id)


def get_refresh_token_from_cookie(
    request: Request,
    ib_refresh: Annotated[
        Optional[str], Cookie(alias=web_config.REFRESH_COOKIE_NAME)
    ] = None,
) -> str:
    """从 HttpOnly Cookie 拿 refresh token；缺失或空 → 401。"""
    if not ib_refresh:
        raise _unauthorized("缺少 refresh token（请重新登录）")
    return ib_refresh


def user_to_response(user: WebUser) -> UserResponse:
    """把 domain WebUser 转 API 响应模型。"""
    # v4+：判断是否为占位账号（@wechat.ielts-buddy.local 是微信占位邮箱）
    is_placeholder = bool(user.email and user.email.endswith("@wechat.ielts-buddy.local"))

    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        wechat_openid=user.wechat_openid,
        is_placeholder_account=is_placeholder,
        pc_logged_in_at=user.pc_logged_in_at,  # type: ignore[arg-type]
    )


__all__ = [
    "get_web_auth_service",
    "get_current_user",
    "get_current_user_optional",
    "get_refresh_token_from_cookie",
    "user_to_response",
]
