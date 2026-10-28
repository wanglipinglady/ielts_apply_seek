"""微信小程序专用路由（v3.9+ / 2026-08-24 新增）。

设计要点：
- 路由前缀统一为 ``/api/wx/``，与 Web 端 ``/api/auth/`` 物理隔离
- service 层完全复用 ``WebAuthService``（铁律 #1：service 是单一真相源）
- code → openid 转换在路由层做（不污染 service）
- service 层零改动，只新增 ``login_by_wechat_openid`` 方法

认证流程（小程序侧）：
1. ``wx.login()`` → 拿到临时 ``code``
2. POST /api/wx/login {code, nickname?, avatar_url?}
3. 服务端用 code 调微信 ``code2Session`` 换 openid（+ session_key）
4. 服务端查/建用户（按 openid）
5. 返回 access_token + refresh_token + user + is_new_user
6. 小程序存 token 到 storage，后续请求带 ``Authorization: Bearer <access_token>``
"""
from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ielts_buddy.web import config as web_config
from ielts_buddy.web.auth.deps import (
    get_current_user,
    get_web_auth_service,
    user_to_response,
)
from ielts_buddy.web.auth.schemas import (
    WxActivatePcAccountRequest,
    WxActivatePcAccountResponse,
    WxLoginRequest,
    WxLoginResponse,
    WxMergeToExistingRequest,
    WxMergeToExistingResponse,
    WxResetPasswordRequest,
    WxResetPasswordResponse,
)
from ielts_buddy.web.auth.service import AuthError, WebAuthService
from ielts_buddy.web.auth.repository import WebUser

logger = logging.getLogger(__name__)

# ---- 路由实例 ----

router = APIRouter(prefix="/api/wx", tags=["wechat-miniprogram"])


# =============================================================
# 工具：code → openid
# =============================================================


class WxCodeError(Exception):
    """微信 code2Session 调用失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code  # 微信返回的 errcode
        self.message = message


async def _exchange_code_for_openid(code: str) -> tuple[str, str | None]:
    """调微信 ``code2Session`` 换 openid + session_key。

    Returns:
        (openid, session_key or None)

    Raises:
        WxCodeError: 微信返回非 0 错误码 / 网络异常 / 配置缺失
    """
    if not web_config.WECHAT_APPID or not web_config.WECHAT_SECRET:
        # 配置缺失 → 抛错（路由层会 fallback 到 mock 或 5xx）
        raise WxCodeError(
            "CONFIG_MISSING",
            "服务端未配置 WECHAT_APPID / WECHAT_SECRET",
        )

    params = {
        "appid": web_config.WECHAT_APPID,
        "secret": web_config.WECHAT_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(web_config.WECHAT_CODE2SESSION_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.warning("wechat code2session 网络错误: %s", e)
        raise WxCodeError("NETWORK_ERROR", f"调用微信接口失败: {e}") from e
    except (ValueError, KeyError) as e:
        logger.warning("wechat code2session 响应解析失败: %s", e)
        raise WxCodeError("INVALID_RESPONSE", "微信接口返回无法解析") from e

    # 微信返回 {"openid": ..., "session_key": ..., "unionid": ..., "errcode": 0, "errmsg": ""}
    errcode = data.get("errcode", 0)
    if errcode != 0:
        errmsg = data.get("errmsg", "未知错误")
        logger.warning("wechat code2session 业务错误: errcode=%s errmsg=%s", errcode, errmsg)
        raise WxCodeError(str(errcode), errmsg)

    openid = data.get("openid")
    if not openid:
        raise WxCodeError("OPENID_MISSING", "微信接口未返回 openid")

    return openid, data.get("session_key")


# =============================================================
# JSON API
# =============================================================


@router.post(
    "/login",
    response_model=WxLoginResponse,
    responses={
        400: {"description": "请求参数无效 / 微信接口错误"},
        500: {"description": "服务端未配置 WECHAT_APPID"},
    },
)
async def api_wx_login(
    request: Request,
    body: WxLoginRequest,
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
) -> WxLoginResponse | JSONResponse:
    """微信小程序一键登录。

    请求：
    ```json
    {"code": "wx.login() 返回的 code", "nickname": "可选", "avatar_url": "可选"}
    ```

    成功（200）：
    ```json
    {
      "access_token": "...",
      "refresh_token": "...",
      "token_type": "bearer",
      "expires_in": 3600,
      "user": {"id": 42, "email": "wx+xxxxxx@wechat.ielts-buddy.local", ...},
      "is_new_user": true
    }
    ```

    失败：
    - 400：微信返回 40001 (invalid code) / 40029 (invalid code) / 等
    - 500：服务端未配置 WECHAT_APPID（仅 prod 环境）
    """
    # 1. code → openid
    try:
        openid, _session_key = await _exchange_code_for_openid(body.code)
    except WxCodeError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": e.message, "code": e.code},
        )

    # 2. service 层：openid → 查/建用户 → 返回 token
    try:
        result = svc.login_by_wechat_openid(openid, nickname=body.nickname)
    except AuthError as e:
        # service 层错误统一映射成 400
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": e.message, "code": e.code},
        )

    # 3. 返回 token + user + is_new_user
    user_resp = user_to_response(result.user)
    return WxLoginResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user=user_resp,
        is_new_user=result.is_new_user,
        # v4.0+：复用 user_to_response 的计算结果，避免两处逻辑分叉
        is_placeholder_account=user_resp.is_placeholder_account,
    )


# =============================================================
# v4.0+：占位账号合并到老账号
# =============================================================


@router.post(
    "/merge-to-existing",
    response_model=WxMergeToExistingResponse,
    responses={
        400: {"description": "请求参数无效"},
        401: {"description": "未登录或登录已失效"},
        404: {"description": "目标邮箱未注册"},
        409: {"description": "目标账号已绑定其他微信 / 不能合并到占位账号"},
        500: {"description": "合并过程失败（已回滚）"},
    },
)
async def api_wx_merge_to_existing(
    request: Request,
    body: WxMergeToExistingRequest,
    current_user: Annotated[WebUser, Depends(get_current_user)],
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
) -> WxMergeToExistingResponse | JSONResponse:
    """v4.0+：把当前微信占位账号合并到指定邮箱的老账号。

    **前置条件**：
    - 调用方必须已通过 ``/api/wx/login`` 登录（依赖 ``get_current_user`` 强制校验 token）
    - 当前用户**必须是占位账号**（email 以 ``@wechat.ielts-buddy.local`` 结尾）

    **请求**：
    ```json
    {"email": "zhang@163.com", "password": "aaa123456"}
    ```

    **业务行为**：
    1. 校验老账号存在 + 密码对
    2. 校验老账号没绑过其他微信
    3. 事务里：迁移占位账号所有业务数据到老账号 + 转移 openid + 删除占位账号 + 写审计日志
    4. 返回基于老账号身份的新 token（小程序端需更新本地 user.id）

    **成功（200）**：
    ```json
    {
      "access_token": "...",
      "refresh_token": "...",
      "token_type": "bearer",
      "expires_in": 3600,
      "user": {"id": 42, "email": "zhang@163.com", "is_placeholder_account": false, ...},
      "merged_from_user_id": 156,
      "merged_vocab_count": 23
    }
    ```

    **失败**：
    - 400 INVALID_REQUEST：当前用户不是微信账号
    - 401 UNAUTHORIZED：未登录
    - 404 USER_NOT_FOUND：邮箱未注册
    - 400 INVALID_CREDENTIALS：密码错
    - 400 INVALID_TARGET：目标是占位账号
    - 409 ALREADY_BOUND：目标账号已绑定其他微信
    - 400 CANNOT_MERGE_SELF：合并目标是当前账号
    - 500 MERGE_FAILED：合并过程出错（已自动回滚）
    """
    # 1. 前置校验：当前用户必须是微信账号
    if not current_user.wechat_openid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "当前账号不是微信账号，无法触发合并", "code": "INVALID_REQUEST"},
        )

    # 2. 调 service 执行合并
    try:
        login_result, merged_from_user_id, merged_vocab_count = svc.merge_wechat_to_existing(
            wechat_openid=current_user.wechat_openid,
            target_email=body.email,
            target_password=body.password,
        )
    except AuthError as e:
        # service 层错误统一映射
        # USER_NOT_FOUND 用 404，其他用 400
        if e.code == "USER_NOT_FOUND":
            status_code = status.HTTP_404_NOT_FOUND
        elif e.code == "ALREADY_BOUND":
            status_code = status.HTTP_409_CONFLICT
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        return JSONResponse(
            status_code=status_code,
            content={"detail": e.message, "code": e.code},
        )
    except Exception as e:
        # 兜底：service 抛 MERGE_FAILED 等
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": f"合并失败: {str(e)[:200]}",
                "code": "MERGE_FAILED",
            },
        )

    # 3. 返回新 token（基于老账号身份）
    return WxMergeToExistingResponse(
        access_token=login_result.access_token,
        refresh_token=login_result.refresh_token,
        expires_in=login_result.expires_in,
        user=user_to_response(login_result.user),
        merged_from_user_id=merged_from_user_id,
        merged_vocab_count=merged_vocab_count,
    )


# =============================================================
# v4.0+：小程序内开通 PC 端账号
# =============================================================


@router.post(
    "/activate-pc-account",
    response_model=WxActivatePcAccountResponse,
    responses={
        400: {"description": "参数无效 / 账号状态不对"},
        401: {"description": "未登录或登录已失效"},
        409: {"description": "邮箱已被注册"},
    },
)
async def api_wx_activate_pc_account(
    request: Request,
    body: WxActivatePcAccountRequest,
    current_user: Annotated[WebUser, Depends(get_current_user)],
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
) -> WxActivatePcAccountResponse | JSONResponse:
    """v4.0+：在小程序里直接开通 PC 端账号（不再让用户去网页注册）。

    **前置条件**：已登录（token 有效），且当前账号是微信占位账号。

    **业务行为**：
    1. 校验邮箱格式 + 密码强度
    2. 校验邮箱未被注册
    3. **原地**把占位账号的 email 改成真实邮箱、写入密码 hash
       （保留 user_id → 小程序里的学习数据零迁移）
    4. 返回基于新身份签发的 token（小程序端需更新本地 user 缓存）

    **成功（200）**：
    ```json
    {
      "access_token": "...",
      "refresh_token": "...",
      "token_type": "bearer",
      "expires_in": 3600,
      "user": {"id": 42, "email": "zhang@163.com", "is_placeholder_account": false}
    }
    ```

    **失败**：
    - 400 INVALID_EMAIL / WEAK_PASSWORD / ALREADY_ACTIVATED
    - 409 EMAIL_TAKEN：邮箱已被注册
    """
    try:
        result = svc.activate_pc_account(
            user_id=int(current_user.id),
            email=body.email,
            password=body.password,
        )
    except AuthError as e:
        if e.code == "EMAIL_TAKEN":
            status_code = status.HTTP_409_CONFLICT
        elif e.code == "USER_NOT_FOUND":
            status_code = status.HTTP_404_NOT_FOUND
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        return JSONResponse(
            status_code=status_code,
            content={"detail": e.message, "code": e.code},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"开通失败: {str(e)[:200]}", "code": "ACTIVATE_FAILED"},
        )

    return WxActivatePcAccountResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user=user_to_response(result.user),
    )


# =============================================================
# v4.0+：已登录用户重置 PC 端密码
# =============================================================


@router.post(
    "/reset-password",
    response_model=WxResetPasswordResponse,
    responses={
        400: {"description": "参数无效"},
        401: {"description": "未登录或登录已失效"},
        403: {"description": "邮箱与当前账号不一致"},
    },
)
async def api_wx_reset_password(
    request: Request,
    body: WxResetPasswordRequest,
    current_user: Annotated[WebUser, Depends(get_current_user)],
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
) -> WxResetPasswordResponse | JSONResponse:
    """v4.0+：已登录用户重置自己账号的 PC 端密码。

    **为什么需要这个**：账号一旦在 PC 端登录过，邮箱就被锁定不能改
    （``pc_logged_in_at`` 有值）。但用户可能忘了密码 → 只能"重置密码"。

    **安全约束**：
    - 必须持有效 access token（登录态 = 微信身份证明）
    - body 里的 email 必须等于当前账号的 email（防越权重置他人密码）

    **成功（200）**：
    ```json
    {"ok": true, "email": "zhang@163.com"}
    ```

    **失败**：
    - 400 WEAK_PASSWORD：新密码太弱
    - 403 EMAIL_MISMATCH：邮箱与当前账号不一致
    """
    try:
        user = svc.reset_password_for_session(
            user_id=int(current_user.id),
            email=body.email,
            new_password=body.new_password,
        )
    except AuthError as e:
        if e.code == "EMAIL_MISMATCH":
            status_code = status.HTTP_403_FORBIDDEN
        elif e.code == "USER_NOT_FOUND":
            status_code = status.HTTP_404_NOT_FOUND
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        return JSONResponse(
            status_code=status_code,
            content={"detail": e.message, "code": e.code},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"重置失败: {str(e)[:200]}", "code": "RESET_FAILED"},
        )

    return WxResetPasswordResponse(ok=True, email=user.email)


@router.post(
    "/dev-mock-login",
    response_model=WxLoginResponse,
    responses={403: {"description": "生产环境禁用此端点"}},
)
async def api_wx_dev_mock_login(
    request: Request,
    body: WxLoginRequest,
    svc: Annotated[WebAuthService, Depends(get_web_auth_service)],
) -> WxLoginResponse | JSONResponse:
    """仅供 dev / 真机调试：跳过 code2Session 直接用 code 当作 openid。

    生产环境（``IELTS_BUDDY_ENV=prod``）会返回 403。
    触发条件：``web_config.WECHAT_DEV_ALLOW_MOCK == False``

    用途：
    - 真机调试时无需真实小程序也能联调
    - pytest 测试时跳过微信 API
    - 每次用不同的 code 模拟新用户 / 老用户

    注意：传 ``code = "test_<openid>"`` 即可模拟任意 openid。
    """
    if not web_config.WECHAT_DEV_ALLOW_MOCK:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "prod 环境禁用 mock 登录", "code": "MOCK_DISABLED"},
        )

    # 把 code 直接当 openid 用（约定："test_<openid>" 格式）
    mock_openid = body.code.strip()
    if mock_openid.startswith("test_"):
        mock_openid = mock_openid[len("test_"):]
    if not mock_openid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "code 不能为空", "code": "INVALID_OPENID"},
        )

    try:
        result = svc.login_by_wechat_openid(mock_openid, nickname=body.nickname)
    except AuthError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": e.message, "code": e.code},
        )

    is_new_user = result.is_new_user
    return WxLoginResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user=user_to_response(result.user),
        is_new_user=is_new_user,
    )


@router.get("/config-check")
async def api_wx_config_check() -> dict:
    """配置自检（小程序启动时可调用，便于排查配置问题）。

    返回：
    - wechat_configured: bool — WECHAT_APPID + WECHAT_SECRET 都已配置
    - mock_login_enabled: bool — dev 环境允许 mock 登录
    - endpoint: str — code2Session URL（前端调试用）
    """
    return {
        "wechat_configured": bool(
            web_config.WECHAT_APPID and web_config.WECHAT_SECRET
        ),
        "mock_login_enabled": web_config.WECHAT_DEV_ALLOW_MOCK,
        "endpoint": web_config.WECHAT_CODE2SESSION_URL,
        "appid_preview": (
            web_config.WECHAT_APPID[:8] + "***"
            if web_config.WECHAT_APPID
            else ""
        ),
    }


__all__ = ["router"]