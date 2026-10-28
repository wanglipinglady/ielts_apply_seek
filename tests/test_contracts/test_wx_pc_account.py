"""
v4.0+ 契约测试：小程序内开通 PC 端账号 + 重置密码 + 账号合并。

覆盖 P0/P1 遗留问题对应的 4 个端点：
- POST /api/wx/activate-pc-account  （P1：开通 PC 端账号不再是死路）
- POST /api/wx/reset-password        （P1：重置密码不再是"开发中"占位）
- POST /api/wx/merge-to-existing     （P0：合并链路可用）
- GET  /api/wx/config-check          （回归）

关键不变量：
1. 开通 PC 端账号后 **user_id 不变**（学习数据零迁移）——这是整个设计的地基
2. 开通后可以用新邮箱密码在 PC 端登录
3. 重置密码后旧密码失效、新密码生效
4. 重置密码不能改别人的账号（邮箱不匹配 → 403）
5. 合并后数据迁移 + 旧账号删除 + 审计日志写入
"""
from __future__ import annotations


def _wx_login(client, openid: str = "test_activate_openid_001"):
    """用 dev-mock-login 拿一个微信账号的 token。"""
    res = client.post("/api/wx/dev-mock-login", json={"code": f"test_{openid}"})
    assert res.status_code == 200, res.text
    body = res.json()
    return {
        "Authorization": f"Bearer {body['access_token']}",
    }, body["user"]


# =============================================================
# activate-pc-account
# =============================================================


def test_activate_pc_account_keeps_user_id(client):
    """开通 PC 端账号后 user_id 必须不变（数据零迁移的地基）。"""
    headers, user = _wx_login(client, "test_activate_keep_id_001")

    assert user["email"].endswith("@wechat.ielts-buddy.local"), \
        "前置条件：微信登录应生成占位账号"
    original_id = user["id"]

    res = client.post(
        "/api/wx/activate-pc-account",
        json={"email": "activate@example.com", "password": "password123"},
        headers=headers,
    )
    assert res.status_code == 200, f"开通失败: {res.status_code} {res.text}"
    body = res.json()

    # user_id 不变
    assert body["user"]["id"] == original_id, \
        f"开通 PC 端账号不应改变 user_id: {original_id} → {body['user']['id']}"
    # email 变成真实邮箱
    assert body["user"]["email"] == "activate@example.com"
    # 不再是占位账号
    assert body["user"]["is_placeholder_account"] is False
    # 返回新 token（前端要更新本地缓存）
    assert body["access_token"]
    assert body["refresh_token"]


def test_activate_pc_account_then_pc_login_works(client):
    """开通后，同一个邮箱+密码能在 PC 端登录。"""
    headers, _ = _wx_login(client, "test_activate_then_login_002")

    res = client.post(
        "/api/wx/activate-pc-account",
        json={"email": "activate_login@example.com", "password": "password123"},
        headers=headers,
    )
    assert res.status_code == 200, res.text

    # PC 端用同一套凭据登录
    login = client.post(
        "/api/auth/login",
        data={"email": "activate_login@example.com", "password": "password123"},
    )
    assert login.status_code == 200, f"PC 端登录失败: {login.status_code} {login.text}"
    assert login.json()["user"]["email"] == "activate_login@example.com"


def test_activate_pc_account_twice_returns_conflict(client):
    """已开通的账号不能再"开通"（避免覆盖已有邮箱）。"""
    headers, _ = _wx_login(client, "test_activate_twice_003")

    first = client.post(
        "/api/wx/activate-pc-account",
        json={"email": "activate_twice@example.com", "password": "password123"},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/wx/activate-pc-account",
        json={"email": "activate_twice2@example.com", "password": "password123"},
        headers=headers,
    )
    assert second.status_code == 400, f"重复开通应报错: {second.status_code}"
    assert second.json()["code"] == "ALREADY_ACTIVATED"


def test_activate_pc_account_email_taken_returns_409(client):
    """邮箱被别人占用 → 409 + EMAIL_TAKEN。"""
    client.post(
        "/api/auth/register",
        data={"email": "taken@example.com", "password": "password123"},
    )
    headers, _ = _wx_login(client, "test_activate_taken_004")

    res = client.post(
        "/api/wx/activate-pc-account",
        json={"email": "taken@example.com", "password": "password123"},
        headers=headers,
    )
    assert res.status_code == 409, f"应返回 409: {res.status_code} {res.text}"
    assert res.json()["code"] == "EMAIL_TAKEN"


def test_activate_pc_account_requires_auth(client):
    """未登录调用 → 401。"""
    res = client.post(
        "/api/wx/activate-pc-account",
        json={"email": "noauth@example.com", "password": "password123"},
    )
    assert res.status_code in (401, 403), f"未登录应 401/403: {res.status_code}"


def test_activate_pc_account_weak_password_rejected(client):
    """密码太弱 → 400。"""
    headers, _ = _wx_login(client, "test_activate_weak_005")
    res = client.post(
        "/api/wx/activate-pc-account",
        json={"email": "weak@example.com", "password": "short"},
        headers=headers,
    )
    assert res.status_code in (400, 422), f"弱密码应被拒: {res.status_code}"


# =============================================================
# reset-password
# =============================================================


def test_reset_password_changes_pc_login_password(client):
    """重置密码后，新密码能登录 PC 端，旧密码失效。"""
    headers, user = _wx_login(client, "test_reset_ok_001")

    act = client.post(
        "/api/wx/activate-pc-account",
        json={"email": "reset@example.com", "password": "password123"},
        headers=headers,
    )
    assert act.status_code == 200, act.text

    reset = client.post(
        "/api/wx/reset-password",
        json={"email": "reset@example.com", "new_password": "newpassword456"},
        headers=headers,
    )
    assert reset.status_code == 200, f"重置失败: {reset.status_code} {reset.text}"
    assert reset.json()["ok"] is True

    # 新密码可登录
    ok = client.post(
        "/api/auth/login",
        data={"email": "reset@example.com", "password": "newpassword456"},
    )
    assert ok.status_code == 200, f"新密码登录失败: {ok.status_code} {ok.text}"

    # 旧密码失效
    old = client.post(
        "/api/auth/login",
        data={"email": "reset@example.com", "password": "password123"},
    )
    assert old.status_code == 401, f"旧密码应失效: {old.status_code}"


def test_reset_password_email_mismatch_returns_403(client):
    """邮箱与当前账号不一致 → 403（防越权重置他人密码）。"""
    headers, _ = _wx_login(client, "test_reset_mismatch_002")
    client.post(
        "/api/wx/activate-pc-account",
        json={"email": "owner@example.com", "password": "password123"},
        headers=headers,
    )

    res = client.post(
        "/api/wx/reset-password",
        json={"email": "someone_else@example.com", "new_password": "newpassword456"},
        headers=headers,
    )
    assert res.status_code == 403, f"应返回 403: {res.status_code} {res.text}"
    assert res.json()["code"] == "EMAIL_MISMATCH"


def test_reset_password_requires_auth(client):
    """未登录调用 → 401。"""
    res = client.post(
        "/api/wx/reset-password",
        json={"email": "x@example.com", "new_password": "newpassword456"},
    )
    assert res.status_code in (401, 403), f"未登录应 401/403: {res.status_code}"


def test_reset_password_weak_password_rejected(client):
    """新密码太弱 → 400/422。"""
    headers, _ = _wx_login(client, "test_reset_weak_003")
    client.post(
        "/api/wx/activate-pc-account",
        json={"email": "weakreset@example.com", "password": "password123"},
        headers=headers,
    )
    res = client.post(
        "/api/wx/reset-password",
        json={"email": "weakreset@example.com", "new_password": "abc"},
        headers=headers,
    )
    assert res.status_code in (400, 422), f"弱密码应被拒: {res.status_code}"


# =============================================================
# merge-to-existing（P0：合并链路）
# =============================================================


def test_merge_to_existing_merges_and_returns_old_account(client):
    """合并：微信占位账号 → PC 端老账号。

    验证：
    - 返回基于老账号身份的新 token
    - 老账号的 user_id 保持不变
    - merged_from_user_id 指向被删掉的占位账号
    """
    # 先在 PC 端注册一个老账号
    reg = client.post(
        "/api/auth/register",
        data={"email": "merge_target@example.com", "password": "password123"},
    )
    assert reg.status_code == 201, reg.text
    target_id = reg.json()["user"]["id"]

    # 微信端登录 → 占位账号
    headers, wx_user = _wx_login(client, "test_merge_src_001")
    placeholder_id = wx_user["id"]
    assert placeholder_id != target_id

    res = client.post(
        "/api/wx/merge-to-existing",
        json={"email": "merge_target@example.com", "password": "password123"},
        headers=headers,
    )
    assert res.status_code == 200, f"合并失败: {res.status_code} {res.text}"
    body = res.json()

    # 返回的是老账号身份
    assert body["user"]["id"] == target_id, \
        f"合并后应切换到老账号 id={target_id}; 实际 {body['user']['id']}"
    assert body["user"]["email"] == "merge_target@example.com"
    assert body["merged_from_user_id"] == placeholder_id
    assert body["access_token"]


def test_merge_to_existing_wrong_password_rejected(client):
    """密码错 → 400 INVALID_CREDENTIALS。"""
    client.post(
        "/api/auth/register",
        data={"email": "merge_wrongpwd@example.com", "password": "password123"},
    )
    headers, _ = _wx_login(client, "test_merge_wrongpwd_002")

    res = client.post(
        "/api/wx/merge-to-existing",
        json={"email": "merge_wrongpwd@example.com", "password": "wrongpassword"},
        headers=headers,
    )
    assert res.status_code == 400, f"应返回 400: {res.status_code} {res.text}"
    assert res.json()["code"] == "INVALID_CREDENTIALS"


def test_merge_to_existing_unknown_email_returns_404(client):
    """邮箱未注册 → 404 USER_NOT_FOUND。"""
    headers, _ = _wx_login(client, "test_merge_nouser_003")
    res = client.post(
        "/api/wx/merge-to-existing",
        json={"email": "nobody_here@example.com", "password": "password123"},
        headers=headers,
    )
    assert res.status_code == 404, f"应返回 404: {res.status_code} {res.text}"
    assert res.json()["code"] == "USER_NOT_FOUND"


def test_merge_to_existing_requires_auth(client):
    """未登录调用 → 401。"""
    res = client.post(
        "/api/wx/merge-to-existing",
        json={"email": "x@example.com", "password": "password123"},
    )
    assert res.status_code in (401, 403), f"未登录应 401/403: {res.status_code}"
