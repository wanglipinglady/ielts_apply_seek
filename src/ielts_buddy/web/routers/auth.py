"""/api/auth/* 与 /login、/register 模板路由。

设计：
- JSON API（/api/auth/*）用于 SPA 客户端、curl、Postman；
- HTML 路由（/login、/register）用 Jinja2 模板渲染，给浏览器用户用。
- HTMX 友好的错误返回：JSON 失败仍带 ``HX-Reswap`` 让前端按需 swap。
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ielts_buddy.web import config as web_config
from ielts_buddy.web.auth.deps import (
    get_current_user,
    get_current_user_optional,
    get_refresh_token_from_cookie,
    get_web_auth_service,
    user_to_response,
)
from ielts_buddy.web.auth.repository import WebUser
from ielts_buddy.web.auth.schemas import (
    AuthErrorResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    TokenResponse,
)
from ielts_buddy.web.auth.security import (
    InvalidTokenError,
    TokenExpiredError,
    decode_token,
    AUDIENCE_REFRESH,
)
from ielts_buddy.web.auth.service import AuthError, WebAuthService


# ---- 路由实例 ----

router = APIRouter(tags=["auth"])
api_router = APIRouter(prefix="/api/auth", tags=["auth"])


# =============================================================
# 工具：refresh cookie 设置
# =============================================================


def _set_refresh_cookie(response: Response, token: str) -> None:
    """下发 HttpOnly refresh token cookie。"""
    response.set_cookie(
        key=web_config.REFRESH_COOKIE_NAME,
        value=token,
        max_age=web_config.REFRESH_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=web_config.COOKIE_SECURE,
        samesite=web_config.COOKIE_SAMESITE,
        path="/api/auth",  # 只在 auth 路由携带，最小化暴露面
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=web_config.REFRESH_COOKIE_NAME,
        path="/api/auth",
    )


def _set_access_cookie(response: Response, token: str) -> None:
    """下发 access token cookie（非 HttpOnly，JS 可读）。"""
    response.set_cookie(
        key=web_config.ACCESS_COOKIE_NAME,
        value=token,
        max_age=web_config.ACCESS_TOKEN_TTL_SECONDS,
        httponly=False,  # JS 需要读取，用于 localStorage 同步
        secure=web_config.COOKIE_SECURE,
        samesite=web_config.COOKIE_SAMESITE,
        path="/",  # 全站路由需要
    )


def _clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        key=web_config.ACCESS_COOKIE_NAME,
        path="/",
    )


def _auth_error_response(exc: AuthError) -> JSONResponse:
    """统一 AuthError → 4xx JSON 响应。"""
    code = exc.code
    if code == "EMAIL_TAKEN":
        status_code = status.HTTP_409_CONFLICT
    elif code == "WEAK_PASSWORD":
        status_code = status.HTTP_400_BAD_REQUEST
    elif code == "INVALID_EMAIL":
        status_code = status.HTTP_400_BAD_REQUEST
    elif code in ("INVALID_CREDENTIALS",):
        status_code = status.HTTP_401_UNAUTHORIZED
    elif code == "USER_NOT_FOUND":
        status_code = status.HTTP_401_UNAUTHORIZED
    elif code in ("TOKEN_INVALID", "TOKEN_EXPIRED"):
        status_code = status.HTTP_401_UNAUTHORIZED
    else:
        status_code = status.HTTP_400_BAD_REQUEST
    return JSONResponse(
        status_code=status_code,
        content=AuthErrorResponse(detail=exc.message, code=code).model_dump(),
    )


# =============================================================
# JSON API
# =============================================================


@api_router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": AuthErrorResponse}, 400: {"model": AuthErrorResponse}},
)
def api_register(
    response: Response,
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
    # 支持 JSON 和 form-encoded 两种格式
    email: Annotated[str, Form(description="邮箱")],
    password: Annotated[str, Form(description="密码")],
) -> TokenResponse | JSONResponse:
    # Form 字段不做 Pydantic 验证，需手动校验
    if len(password) < 8:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "密码至少 8 位"},
        )
    if "@" not in email or "." not in email:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "邮箱格式无效"},
        )
    try:
        result = svc.register(email, password)
    except AuthError as e:
        return _auth_error_response(e)

    _set_refresh_cookie(response, result.refresh_token)
    _set_access_cookie(response, result.access_token)
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user=user_to_response(result.user),
    )


@api_router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"model": AuthErrorResponse}},
)
def api_login(
    response: Response,
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
    # 支持 JSON 和 form-encoded 两种格式
    email: Annotated[str, Form(description="邮箱")],
    password: Annotated[str, Form(description="密码")],
) -> TokenResponse | JSONResponse:
    try:
        result = svc.login(email, password)
    except AuthError as e:
        return _auth_error_response(e)

    _set_refresh_cookie(response, result.refresh_token)
    _set_access_cookie(response, result.access_token)
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user=user_to_response(result.user),
    )


@api_router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={401: {"model": AuthErrorResponse}},
)
def api_refresh(
    request: Request,
    response: Response,
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
) -> Response:
    # 不走依赖注入，缺 / 错 / 过期都要在路由内清 cookie 后再返回 401
    # 关键：必须复用 ``response`` 形参，否则 set/delete_cookie 不会下发
    refresh_token: str | None = request.cookies.get(web_config.REFRESH_COOKIE_NAME)
    if not refresh_token:
        _clear_refresh_cookie(response)
        response.status_code = status.HTTP_401_UNAUTHORIZED
        response.body = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=AuthErrorResponse(
                detail="缺少 refresh token（请重新登录）",
                code="TOKEN_INVALID",
            ).model_dump(),
        ).body
        return response
    # 早期校验 refresh 合法性（signature/audience/expiry），失败清 cookie
    try:
        decode_token(refresh_token, expected_audience=AUDIENCE_REFRESH)
    except (InvalidTokenError, TokenExpiredError):
        _clear_refresh_cookie(response)
        response.status_code = status.HTTP_401_UNAUTHORIZED
        response.body = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=AuthErrorResponse(
                detail="refresh token 无效", code="TOKEN_INVALID",
            ).model_dump(),
        ).body
        return response

    try:
        result = svc.refresh(refresh_token)
    except AuthError as e:
        # refresh 失败时顺手清 cookie（避免脏 cookie 持续无效）
        _clear_refresh_cookie(response)
        err = _auth_error_response(e)
        response.status_code = err.status_code
        response.body = err.body
        return response

    _set_refresh_cookie(response, result.refresh_token)
    ok = TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user=user_to_response(result.user),
    )
    response.media_type = "application/json"
    response.body = ok.model_dump_json().encode("utf-8")
    response.status_code = status.HTTP_200_OK
    return response


@api_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def api_logout(response: Response) -> Response:
    """登出：清除 access 和 refresh cookie。

    注意：必须复用 ``response`` 形参，否则 set_cookie 不会下发到客户端。
    204 + cookie：FastAPI 会忽略 body，但 Set-Cookie 头仍会写入。
    """
    _clear_access_cookie(response)
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@api_router.get("/me")
def api_me(
    user: Annotated[WebUser, Depends(get_current_user)],
):
    """当前用户信息。"""
    return user_to_response(user).model_dump()


# =============================================================
# 改密 / 重置密码
# =============================================================

from fastapi import Header


@api_router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    responses={401: {"model": AuthErrorResponse}, 400: {"model": AuthErrorResponse}},
)
def api_change_password(
    body: ChangePasswordRequest,
    user: Annotated[WebUser, Depends(get_current_user)],
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
) -> ChangePasswordResponse | JSONResponse:
    """用户自助改密：登录态调用，需提供旧密码。

    请求体：
    ```json
    {"old_password": "OldPass123!", "new_password": "NewPass456!"}
    ```

    返回：
    - 200：{"ok": true}
    - 401：旧密码错 / 未登录
    - 400：新密码太弱 / email 不存在
    """
    try:
        svc.change_password(user.id, body.old_password, body.new_password)
    except AuthError as e:
        return _auth_error_response(e)
    return ChangePasswordResponse(ok=True)


def _verify_admin_token(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    """校验 admin 接口的预共享 token（环境变量 ``IELTS_BUDDY_ADMIN_RESET_TOKEN``）。

    未传 / 错值都 401。失败时**不区分**是"缺失"还是"错值"，避免泄露。
    """
    expected = web_config.ADMIN_RESET_TOKEN
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少或无效的 X-Admin-Token",
            headers={"WWW-Authenticate": "X-Admin-Token"},
        )


@api_router.post(
    "/admin/reset-password",
    response_model=ResetPasswordResponse,
    responses={
        401: {"model": AuthErrorResponse},
        404: {"model": AuthErrorResponse},
    },
)
def api_admin_reset_password(
    body: ResetPasswordRequest,
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
    # 守卫：必须在 HTTP 头带 X-Admin-Token
    _: Annotated[None, Depends(_verify_admin_token)],
) -> ResetPasswordResponse | JSONResponse:
    """管理员按 email 重置密码：返回一次性新明文密码。

    安全说明：
    - 必须设置环境变量 ``IELTS_BUDDY_ADMIN_RESET_TOKEN``（prod 必须设置）
    - 调用方需在 header 带 ``X-Admin-Token: <value>``
    - 响应中**一次性**返回新明文密码；服务端只存 bcrypt hash，不留明文
    - 客户端**必须**立即保存这个密码；丢失只能再次重置

    请求体：
    ```json
    {"email": "user@x.com"}
    ```

    返回：
    ```json
    {
      "email": "user@x.com",
      "new_password": "aB3xY7zQ9m",
      "user_id": 4
    }
    ```
    """
    try:
        user, new_plain = svc.reset_password(body.email)
    except AuthError as e:
        return _auth_error_response(e)
    return ResetPasswordResponse(
        email=user.email,
        new_password=new_plain,
        user_id=user.id,
    )


# =============================================================
# HTML 模板路由
# =============================================================


def _get_templates(request: Request) -> Jinja2Templates:
    """从 app.state 拿已构造的 templates 实例。"""
    return request.app.state.templates


@router.get("/login", response_class=HTMLResponse)
def page_login(request: Request) -> HTMLResponse:
    return _get_templates(request).TemplateResponse(
        request,
        "pages/login.html",
        {"title": "登录", "phase": 1, "current_user": None},
    )


@router.get("/register", response_class=HTMLResponse)
def page_register(request: Request) -> HTMLResponse:
    return _get_templates(request).TemplateResponse(
        request,
        "pages/register.html",
        {"title": "注册", "phase": 1, "current_user": None},
    )


@router.get("/change-password", response_class=HTMLResponse)
def page_change_password(request: Request) -> HTMLResponse:
    """修改密码页面（需登录态，由前端 JS 检查 localStorage token）。"""
    return _get_templates(request).TemplateResponse(
        request,
        "pages/change_password.html",
        {"title": "修改密码", "phase": 1, "current_user": None},
    )


# 注：``/dashboard`` 的真实实现在 ``pages.py``（阶段 2 加了摘要卡片），
# 这里不再保留占位版本，避免同名路由被后者覆盖导致实际请求走老版本。
