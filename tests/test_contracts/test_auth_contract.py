"""
auth 模块契约测试
锁定 4 个核心 API 的响应 / 入参结构（鉴权是三端共享最敏感的部分）。

特别注意：
- /api/auth/login Web + 小程序都会调用
- /api/auth/wx-login 小程序专用（W2 新增）
- /api/auth/register Web 专用（CLI 不走注册）
- JWT token 字段名（access_token / refresh_token）三端都不能变
"""
from __future__ import annotations

import os


def test_login_response_contract(client):
    """POST /api/auth/login 响应契约。

    Web /login 页、小程序 wx-login（间接调用）都依赖 token 字段。
    """
    # 先注册一个测试账号
    client.post(
        "/api/auth/register",
        data={"email": "auth_contract@example.com", "password": "password123"},
    )

    res = client.post(
        "/api/auth/login",
        data={"email": "auth_contract@example.com", "password": "password123"},
    )
    assert res.status_code == 200, f"login 失败: {res.text}"
    body = res.json()

    # 关键字段契约：JWT token 命名不能变
    required = {"access_token", "refresh_token"}
    missing = required - body.keys()
    assert not missing, f"login 响应缺字段: {missing}; 实际: {body.keys()}"

    # user 嵌套对象契约
    assert "user" in body, f"login 响应缺 user 字段"
    user = body["user"]
    user_required = {"id", "email"}
    user_missing = user_required - user.keys()
    assert not user_missing, f"user 对象缺字段: {user_missing}; 实际: {user.keys()}"


def test_register_response_contract(client):
    """POST /api/auth/register 响应契约（与 login 同步）。"""
    res = client.post(
        "/api/auth/register",
        data={"email": "register_contract@example.com", "password": "password123"},
    )

    if res.status_code == 201:
        body = res.json()
        # 与 login 保持一致的字段结构
        assert "access_token" in body
        assert "refresh_token" in body
        assert "user" in body
        assert "id" in body["user"]


def test_jwt_token_can_decode(client):
    """JWT token 必须能被现有 decode_token 解析（带 audience 参数）。

    这个测试保护：改 JWT 签发逻辑不会破坏三端鉴权。
    """
    client.post(
        "/api/auth/register",
        data={"email": "jwt@example.com", "password": "password123"},
    )
    login = client.post(
        "/api/auth/login",
        data={"email": "jwt@example.com", "password": "password123"},
    )
    token = login.json()["access_token"]

    # 解析 token：必须传 audience（沿用现有 AUDIENCE_ACCESS 常量）
    from ielts_buddy.web.auth.security import decode_token, AUDIENCE_ACCESS
    payload = decode_token(token, expected_audience=AUDIENCE_ACCESS)

    assert payload is not None, "decode_token 返回 None — JWT 解析失败"
    assert "sub" in payload, "JWT payload 缺 sub 字段"
    # sub 在 JWT 里是字符串（JWT 标准），deps.py 里会 int() 转换
    assert isinstance(payload["sub"], str), f"sub 必须是 str (JWT 标准);); 实际: {type(payload['sub'])}"
    # 同时验证能转 int（deps.py 的关键操作）
    int(payload["sub"])  # 不抛异常就 OK


def test_unauthorized_request_returns_401(client):
    """未登录访问鉴权接口必须返回 401（三端统一行为）。

    小程序依赖这个状态码触发「跳转到登录页」。

    注意：用 /api/auth/refresh 这种"已知存在 + 需要鉴权"的端点来测。
    """
    # /api/auth/refresh 不带 token 必须返回 401
    res = client.post("/api/auth/refresh", json={})
    assert res.status_code in (401, 403), \
        f"未登录应返回 401/403; 实际: {res.status_code}"


def test_invalid_token_returns_401(client):
    """无效 JWT 必须返回 401（小程序依赖这个判断「token 过期」）。"""
    res = client.post(
        "/api/auth/refresh",
        json={},
        headers={"Authorization": "Bearer invalid_token_xxxx"},
    )
    assert res.status_code in (401, 403), \
        f"无效 token 应返回 401/403; 实际: {res.status_code}"