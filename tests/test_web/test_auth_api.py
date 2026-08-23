"""/api/auth/* 端到端测试。"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from ielts_buddy.web.auth.security import (
    create_access_token,
    create_refresh_token,
)


# =============================================================
# 注册
# =============================================================


def test_register_success(client: TestClient) -> None:
    r = client.post(
        "/api/auth/register",
        data={"email": "alice@example.com", "password": "password123"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["id"] >= 1
    # refresh cookie 应当下发
    assert "ib_refresh" in r.cookies
    # access / refresh token 都能解码
    from ielts_buddy.web.auth.security import (
        AUDIENCE_ACCESS,
        AUDIENCE_REFRESH,
        decode_token,
    )
    decode_token(body["access_token"], expected_audience=AUDIENCE_ACCESS)
    decode_token(body["refresh_token"], expected_audience=AUDIENCE_REFRESH)


def test_register_duplicate_email_returns_409(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        data={"email": "dup@example.com", "password": "password123"},
    )
    r = client.post(
        "/api/auth/register",
        data={"email": "dup@example.com", "password": "different123"},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "EMAIL_TAKEN"


def test_register_weak_password_returns_422(client: TestClient) -> None:
    """密码 < 8 位由 pydantic 校验层拦在 422。"""
    r = client.post(
        "/api/auth/register",
        data={"email": "weak@example.com", "password": "short"},
    )
    assert r.status_code == 422


def test_register_invalid_email_returns_422(client: TestClient) -> None:
    """pydantic 校验失败由 FastAPI 抛 422。"""
    r = client.post(
        "/api/auth/register",
        data={"email": "not-an-email", "password": "password123"},
    )
    assert r.status_code == 422


# =============================================================
# 登录
# =============================================================


def test_login_success(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        data={"email": "login@example.com", "password": "password123"},
    )
    r = client.post(
        "/api/auth/login",
        data={"email": "login@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "login@example.com"
    assert "ib_refresh" in r.cookies


def test_login_wrong_password_returns_401(client: TestClient) -> None:
    client.post(
        "/api/auth/register",
        data={"email": "wp@example.com", "password": "password123"},
    )
    r = client.post(
        "/api/auth/login",
        data={"email": "wp@example.com", "password": "wrongpass"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "INVALID_CREDENTIALS"


def test_login_nonexistent_email_returns_401(client: TestClient) -> None:
    r = client.post(
        "/api/auth/login",
        data={"email": "ghost@example.com", "password": "password123"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "INVALID_CREDENTIALS"


# =============================================================
# 刷新
# =============================================================


def test_refresh_success(client: TestClient) -> None:
    reg = client.post(
        "/api/auth/register",
        data={"email": "ref@example.com", "password": "password123"},
    )
    assert reg.status_code == 201
    client.cookies.set("ib_refresh", reg.cookies["ib_refresh"])
    r = client.post("/api/auth/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] != reg.json()["access_token"]


def test_refresh_no_cookie_returns_401(client: TestClient) -> None:
    r = client.post("/api/auth/refresh")
    assert r.status_code == 401


def _collect_set_cookies(response) -> str:
    """合并所有 Set-Cookie 头（starlette/httpx 在 delete_cookie 时会单独下发）。"""
    raw = response.headers.get_list("set-cookie")
    return "\n".join(raw).lower()


def test_refresh_invalid_token_clears_cookie(client: TestClient) -> None:
    """refresh 失败时 cookie 应被清掉。"""
    client.cookies.set("ib_refresh", "not-a-token")
    r = client.post("/api/auth/refresh")
    assert r.status_code == 401
    # starlette 通过删除 cookie 下发 Set-Cookie: ib_refresh=; Max-Age=0
    set_cookie = _collect_set_cookies(r)
    assert "ib_refresh" in set_cookie
    assert (
        "max-age=0" in set_cookie
        or 'ib_refresh=""' in set_cookie
        or "ib_refresh=;" in set_cookie
    )


# =============================================================
# 登出
# =============================================================


def test_logout_clears_cookie(client: TestClient) -> None:
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    set_cookie = _collect_set_cookies(r)
    assert "ib_refresh" in set_cookie
    assert (
        "max-age=0" in set_cookie
        or 'ib_refresh=""' in set_cookie
        or "ib_refresh=;" in set_cookie
    )


# =============================================================
# me
# =============================================================


def test_me_with_valid_token(client: TestClient) -> None:
    reg = client.post(
        "/api/auth/register",
        data={"email": "me@example.com", "password": "password123"},
    )
    access = reg.json()["access_token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "me@example.com"
    assert body["id"] >= 1


def test_me_without_token_returns_401(client: TestClient) -> None:
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_with_invalid_token_returns_401(client: TestClient) -> None:
    r = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )
    assert r.status_code == 401


def test_me_with_refresh_token_rejected(client: TestClient) -> None:
    """拿 refresh token 当 access 用 → audience 不匹配 → 401。"""
    reg = client.post(
        "/api/auth/register",
        data={"email": "rt@example.com", "password": "password123"},
    )
    refresh = reg.json()["refresh_token"]
    r = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert r.status_code == 401


def test_me_with_expired_token_returns_401(client: TestClient) -> None:
    """用 TTL=1 的 token，sleep 后过期 → 401。"""
    # 直接生成一个马上过期的 access token
    from ielts_buddy.web.auth.security import AUDIENCE_ACCESS, decode_token
    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository

    # 注册一个用户
    reg = client.post(
        "/api/auth/register",
        data={"email": "exp@example.com", "password": "password123"},
    )
    user_id = reg.json()["user"]["id"]
    # 签发 1s TTL 的 access token
    token = create_access_token(user_id, "exp@example.com", ttl_seconds=1)
    time.sleep(1.5)
    r = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


# =============================================================
# 模板页
# =============================================================


def test_login_page_renders(client: TestClient) -> None:
    r = client.get("/login")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "登录" in r.text


def test_register_page_renders(client: TestClient) -> None:
    r = client.get("/register")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "注册" in r.text


def test_dashboard_redirects_when_unauthenticated(client: TestClient) -> None:
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_dashboard_renders_for_authenticated_user(
    client: TestClient, registered_user: dict
) -> None:
    headers = {"Authorization": f"Bearer {registered_user['access_token']}"}
    r = client.get("/dashboard", headers=headers)
    assert r.status_code == 200
    assert registered_user["email"] in r.text


# =============================================================
# 端到端：注册 → 自动登录 → me 拿当前用户
# =============================================================


def test_end_to_end_flow(client: TestClient) -> None:
    # 1) 注册
    reg = client.post(
        "/api/auth/register",
        data={"email": "e2e@example.com", "password": "password123"},
    )
    assert reg.status_code == 201
    access = reg.json()["access_token"]

    # 2) 用 access token 拿 me
    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "e2e@example.com"

    # 3) 用 refresh 换新 access
    client.cookies.set("ib_refresh", reg.cookies["ib_refresh"])
    new = client.post("/api/auth/refresh")
    assert new.status_code == 200
    new_access = new.json()["access_token"]

    # 4) 旧 access 仍能短期使用（除非过期）
    me2 = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert me2.status_code == 200

    # 5) 登出（清 cookie）
    out = client.post("/api/auth/logout")
    assert out.status_code == 204


# =============================================================
# 修改密码（form-encoded 路径，HTMX 默认提交格式）
# =============================================================


def test_change_password_form_path_requires_login(client: TestClient) -> None:
    """未登录 → 401（不能因为缺少 form 字段就走通到路由）。"""
    r = client.post(
        "/api/auth/change-password",
        data={"old_password": "x", "new_password": "longenough"},
        # 显式清 Authorization 头，避免 TestClient cookie 自动复用
        headers={"Authorization": ""},
    )
    assert r.status_code == 401, r.text
    assert "缺少 Authorization" in r.text


def test_change_password_form_path_wrong_old_password(client: TestClient) -> None:
    """登录态 + 旧密码错 → 401 INVALID_CREDENTIALS。"""
    reg = client.post(
        "/api/auth/register",
        data={"email": "cpwrong@example.com", "password": "oldpass123"},
    )
    assert reg.status_code == 201
    access = reg.json()["access_token"]

    r = client.post(
        "/api/auth/change-password",
        data={"old_password": "WRONG", "new_password": "newpass456"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 401, r.text
    assert "INVALID_CREDENTIALS" in r.text


def test_change_password_form_path_success(client: TestClient) -> None:
    """登录态 + 旧密码对 → 200 {ok: true}，新密码可登录。"""
    reg = client.post(
        "/api/auth/register",
        data={"email": "cpsuccess@example.com", "password": "oldpass123"},
    )
    assert reg.status_code == 201
    access = reg.json()["access_token"]

    r = client.post(
        "/api/auth/change-password",
        data={"old_password": "oldpass123", "new_password": "newpass456"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    # 新密码能登录；旧密码不能
    new_login = client.post(
        "/api/auth/login",
        data={"email": "cpsuccess@example.com", "password": "newpass456"},
    )
    assert new_login.status_code == 200

    # 旧密码登录应该 401
    old_login = client.post(
        "/api/auth/login",
        data={"email": "cpsuccess@example.com", "password": "oldpass123"},
    )
    assert old_login.status_code == 401


def test_change_password_form_path_weak_new_password_returns_422(client: TestClient) -> None:
    """form-encoded：new_password < 8 → 422（Pydantic Field min_length 校验）。"""
    reg = client.post(
        "/api/auth/register",
        data={"email": "cpweak@example.com", "password": "oldpass123"},
    )
    assert reg.status_code == 201
    access = reg.json()["access_token"]

    r = client.post(
        "/api/auth/change-password",
        data={"old_password": "oldpass123", "new_password": "short"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 422, r.text


def test_change_password_page_renders(client: TestClient) -> None:
    """/change-password HTML 页面能渲染，包含必填元素。"""
    r = client.get("/change-password")
    assert r.status_code == 200
    for needle in ("修改密码", "old_password", "new_password",
                   "confirm_password", "pwd-toggle",
                   "/api/auth/change-password"):
        assert needle in r.text, f"missing {needle!r}"


# =============================================================
# 忘记密码（重置为默认密码 12345678）
# =============================================================


def test_forgot_password_page_renders(client: TestClient) -> None:
    """/forgot-password HTML 页面能渲染，包含默认密码提示。"""
    r = client.get("/forgot-password")
    assert r.status_code == 200
    for needle in ("忘记密码", "12345678", "name=\"email\"",
                   "/api/auth/forgot-password"):
        assert needle in r.text, f"missing {needle!r}"


def test_forgot_password_unknown_email_returns_401(client: TestClient) -> None:
    """邮箱不存在 → 401 INVALID_CREDENTIALS（避免邮箱枚举）。"""
    r = client.post(
        "/api/auth/forgot-password",
        data={"email": "nobody@example.com"},
    )
    assert r.status_code == 401, r.text
    assert "INVALID_CREDENTIALS" in r.text


def test_forgot_password_invalid_email_format_returns_400(client: TestClient) -> None:
    """邮箱格式无效 → 400 INVALID_EMAIL。"""
    r = client.post(
        "/api/auth/forgot-password",
        data={"email": "not-an-email"},
    )
    assert r.status_code == 400, r.text
    assert "INVALID_EMAIL" in r.text


def test_forgot_password_missing_email_returns_422(client: TestClient) -> None:
    """email 字段缺失 → 422（Pydantic / Form 必填校验）。"""
    r = client.post("/api/auth/forgot-password", data={})
    assert r.status_code == 422


def test_forgot_password_resets_to_default_and_returns_plaintext(
    client: TestClient,
) -> None:
    """重置成功：返回明文 12345678，旧密码失效，新密码可登录。"""
    # 1. 注册用户
    reg = client.post(
        "/api/auth/register",
        data={"email": "forgot@example.com", "password": "originalpw1"},
    )
    assert reg.status_code == 201
    user_id = reg.json()["user"]["id"]

    # 2. 重置为默认密码
    r = client.post(
        "/api/auth/forgot-password",
        data={"email": "forgot@example.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "forgot@example.com"
    assert body["user_id"] == user_id
    assert body["new_password"] == "12345678"

    # 3. 旧密码登录失败
    old_login = client.post(
        "/api/auth/login",
        data={"email": "forgot@example.com", "password": "originalpw1"},
    )
    assert old_login.status_code == 401

    # 4. 默认密码登录成功
    new_login = client.post(
        "/api/auth/login",
        data={"email": "forgot@example.com", "password": "12345678"},
    )
    assert new_login.status_code == 200
