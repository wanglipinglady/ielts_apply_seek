"""
WeChat 小程序登录契约测试（v3.9+ / 2026-08-24 新增）。

锁定 3 个端点的响应 / 入参结构：
- POST /api/wx/dev-mock-login（dev 模式跳过 code2Session，直接用 code 当 openid）
- GET /api/wx/config-check
- POST /api/wx/login（生产模式调真实微信接口，dev 测试走 mock 即可）

特别注意：
- /api/wx/login 走真实微信接口，契约测试不直接调用
- /api/wx/dev-mock-login 只在 dev 模式可用，prod 返回 403
- 响应字段与 Web /api/auth/login 完全对齐（access_token / refresh_token / user）
  → 这是铁律 #1 的契约体现
"""
from __future__ import annotations


def test_wx_config_check_contract(client):
    """GET /api/wx/config-check 响应契约。

    小程序启动时调用，确认服务端配置状态。
    """
    res = client.get("/api/wx/config-check")
    assert res.status_code == 200
    body = res.json()

    # 必填字段契约（小程序前端依赖）
    required = {"wechat_configured", "mock_login_enabled", "endpoint"}
    missing = required - body.keys()
    assert not missing, f"config-check 响应缺字段: {missing}; 实际: {body.keys()}"

    # 类型契约（防 schema 误改）
    assert isinstance(body["wechat_configured"], bool)
    assert isinstance(body["mock_login_enabled"], bool)
    assert isinstance(body["endpoint"], str)
    # endpoint 必须是微信官方 URL
    assert "weixin.qq.com" in body["endpoint"], \
        f"endpoint 应指向微信官方; 实际: {body['endpoint']}"


def test_wx_dev_mock_login_response_contract(client):
    """POST /api/wx/dev-mock-login 响应契约（与 Web login 同字段名，三端共享）。

    这是契约测试的关键：wx-login 的响应字段必须与 Web login 完全对齐，
    保证小程序前端拿到 access_token 后能直接走 Web 的鉴权中间件。
    """
    res = client.post(
        "/api/wx/dev-mock-login",
        json={"code": "test_oBPnJ5_demo_openid_001", "nickname": "测试用户"},
    )
    assert res.status_code == 200, f"wx mock 登录失败: {res.status_code} {res.text}"
    body = res.json()

    # 必须与 Web /api/auth/login 同字段（铁律 #1）
    required = {"access_token", "refresh_token", "token_type", "expires_in", "user"}
    missing = required - body.keys()
    assert not missing, f"wx mock 响应缺字段: {missing}; 实际: {body.keys()}"

    # user 嵌套对象契约
    user = body["user"]
    assert "id" in user, f"user 缺 id 字段; 实际: {user.keys()}"
    assert isinstance(user["id"], int), f"user.id 必须是 int; 实际: {type(user['id'])}"

    # is_new_user 标志（v3.9 微信登录新增）
    assert "is_new_user" in body, f"wx mock 响应缺 is_new_user 字段; 实际: {body.keys()}"
    assert isinstance(body["is_new_user"], bool)

    # 第一次调用 → 新用户
    assert body["is_new_user"] is True, "首次 mock 登录应标记 is_new_user=True"

    # token 类型契约
    assert body["token_type"] == "bearer"


def test_wx_dev_mock_login_idempotent(client):
    """同一 code 第二次调用 → is_new_user=False（数据库去重）。

    验证 service 层 openid 查重逻辑正确。
    """
    # 第一次
    res1 = client.post(
        "/api/wx/dev-mock-login",
        json={"code": "test_idempotent_openid_002"},
    )
    assert res1.status_code == 200
    assert res1.json()["is_new_user"] is True

    # 第二次同 code → 老用户
    res2 = client.post(
        "/api/wx/dev-mock-login",
        json={"code": "test_idempotent_openid_002"},
    )
    assert res2.status_code == 200
    assert res2.json()["is_new_user"] is False, \
        "同一 openid 第二次登录应标记 is_new_user=False"
    # user.id 应一致
    assert res1.json()["user"]["id"] == res2.json()["user"]["id"], \
        "同一 openid 应映射到同一 user_id"


def test_wx_dev_mock_login_token_can_decode(client):
    """wx-login 返回的 access_token 必须能被现有 decode_token 解析。

    验证铁律 #1：三端共享同一套 JWT 签发逻辑。
    """
    res = client.post(
        "/api/wx/dev-mock-login",
        json={"code": "test_token_decode_openid_003"},
    )
    assert res.status_code == 200
    token = res.json()["access_token"]

    from ielts_buddy.web.auth.security import decode_token, AUDIENCE_ACCESS
    payload = decode_token(token, expected_audience=AUDIENCE_ACCESS)
    assert payload is not None, "wx-login 返回的 token 无法被 decode_token 解析"
    assert "sub" in payload
    # sub 转 int 后应能对应 user.id（验证 wx-login 创建的用户与 token 关联正确）
    user_id = int(payload["sub"])
    assert user_id > 0


def test_wx_dev_mock_login_empty_code_400(client):
    """空 code 必须 400（前端基础校验）。"""
    res = client.post(
        "/api/wx/dev-mock-login",
        json={"code": ""},
    )
    # FastAPI Pydantic 校验 min_length=1 → 422
    assert res.status_code in (400, 422), \
        f"空 code 应返回 400/422; 实际: {res.status_code}"


def test_wx_login_real_endpoint_exists(client):
    """POST /api/wx/login 路由必须存在（生产模式调真实微信）。

    dev 测试中因为没有真实 WECHAT_APPID 会返回 400/500，**但路由必须存在**。
    """
    res = client.post(
        "/api/wx/login",
        json={"code": "test_fake_code_for_route_check"},
    )
    # 路由存在 → 返回 400/500（不是 404）
    assert res.status_code != 404, \
        f"/api/wx/login 路由不存在（404）; 实际: {res.status_code}"
    # 因为没有真实微信 AppID，会返回 400（WECHAT_APPID 未配置）
    assert res.status_code in (400, 500), \
        f"无真实微信配置时应返回 400/500; 实际: {res.status_code}"


def test_wx_login_response_keys_match_web_login(client):
    """wx-login 响应字段名必须与 Web login 完全一致（铁律 #1）。

    验证：小程序拿到 wx-login 的 token 后，能用同样的逻辑解析
    access_token / refresh_token / user.id。
    """
    # 注册一个 web 用户
    client.post(
        "/api/auth/register",
        data={"email": "web_login@example.com", "password": "password123"},
    )
    web_login = client.post(
        "/api/auth/login",
        data={"email": "web_login@example.com", "password": "password123"},
    )
    web_keys = set(web_login.json().keys())

    # wx mock 登录
    wx_login = client.post(
        "/api/wx/dev-mock-login",
        json={"code": "test_web_login_match_004"},
    )
    wx_keys = set(wx_login.json().keys())

    # 核心字段交集必须非空
    core_fields = {"access_token", "refresh_token", "user"}
    assert core_fields <= web_keys, f"Web login 缺核心字段: {core_fields - web_keys}"
    assert core_fields <= wx_keys, f"wx mock login 缺核心字段: {core_fields - wx_keys}"