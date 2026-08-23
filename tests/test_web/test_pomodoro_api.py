"""``/api/pomodoro/*`` 番茄钟端到端测试（v3.6 新增）。

覆盖：
1. /pomodoro 未登录 → 302 → /login
2. /api/pomodoro/start 未登录 → 401
3. /api/pomodoro/start 成功路径：落库并返回 session_id
4. /api/pomodoro/{id}/complete 写入实际时长 + interrupted + note
5. /api/pomodoro/{id}/complete 找不到 session → 404
6. /api/pomodoro/history 按 user 隔离
7. /api/pomodoro/today 今日累计
8. planned_sec 边界（<60 / >7200 / 合法值）
9. activity 白名单（非法回落 "other"）
10. duration_sec 边界（<0 / 合法值）
"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


# =============================================================
# Helpers
# =============================================================


def _register(
    client: TestClient,
    email: str = "pomodoro@example.com",
    password: str = "password123",
) -> dict[str, Any]:
    r = client.post(
        "/api/auth/register",
        data={"email": email, "password": password},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "user_id": body["user"]["id"],
        "access_token": body["access_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }


def _start_session(
    client: TestClient,
    headers: dict,
    planned_sec: int = 1500,
    activity: str = "vocab",
    note: str = "",
) -> dict:
    """启动一个专注会话,返回响应 JSON。"""
    r = client.post(
        "/api/pomodoro/start",
        headers=headers,
        data={
            "planned_sec": str(planned_sec),
            "activity": activity,
            "note": note,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


# =============================================================
# 1. 页面路由
# =============================================================


def test_pomodoro_page_unauthenticated_redirects_to_login(client_with_db: TestClient) -> None:
    """未登录访问 /pomodoro → 302 → /login。"""
    r = client_with_db.get("/pomodoro", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/login"


def test_pomodoro_page_authenticated_returns_html(client_with_db: TestClient) -> None:
    """登录后访问 /pomodoro → 200 + HTML。"""
    user = _register(client_with_db, email="pomo-html@example.com")
    r = client_with_db.get("/pomodoro", headers=user["headers"])
    assert r.status_code == 200
    assert "番茄钟" in r.text


# =============================================================
# 2. /api/pomodoro/start
# =============================================================


def test_start_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录 POST /api/pomodoro/start → 401。"""
    r = client_with_db.post(
        "/api/pomodoro/start",
        data={"planned_sec": "1500", "activity": "vocab"},
    )
    assert r.status_code == 401


def test_start_returns_session_id_and_planned_sec(client_with_db: TestClient) -> None:
    """start 响应包含 session_id / planned_sec / started_at。"""
    user = _register(client_with_db, email="pomo-start@example.com")
    data = _start_session(client_with_db, user["headers"], planned_sec=1500)
    assert isinstance(data["session_id"], int)
    assert data["session_id"] > 0
    assert data["planned_sec"] == 1500
    assert data["started_at"] != ""


def test_start_persists_to_db(client_with_db: TestClient) -> None:
    """start 后,本地 SQLite 应有一行 duration_sec=0,interrupted=0。"""
    user = _register(client_with_db, email="pomo-persist@example.com")
    data = _start_session(
        client_with_db, user["headers"],
        planned_sec=1500, activity="writing", note="开始 Task 2",
    )
    sid = data["session_id"]
    h = client_with_db.get("/api/pomodoro/history", headers=user["headers"])
    rows = h.json()
    assert len(rows) == 1
    assert rows[0]["id"] == sid
    assert rows[0]["activity"] == "writing"
    assert rows[0]["planned_sec"] == 1500
    assert rows[0]["duration_sec"] == 0
    assert rows[0]["interrupted"] is False
    assert rows[0]["note"] == "开始 Task 2"


def test_start_invalid_activity_falls_back_to_other(client_with_db: TestClient) -> None:
    """非法 activity 回落 'other'。"""
    user = _register(client_with_db, email="pomo-act@example.com")
    data = _start_session(
        client_with_db, user["headers"],
        planned_sec=900, activity="hacking",
    )
    h = client_with_db.get("/api/pomodoro/history", headers=user["headers"])
    assert h.json()[0]["activity"] == "other"


def test_start_planned_sec_min_boundary(client_with_db: TestClient) -> None:
    """planned_sec=60 (最小值) 应允许。"""
    user = _register(client_with_db, email="pomo-min@example.com")
    data = _start_session(client_with_db, user["headers"], planned_sec=60)
    assert data["planned_sec"] == 60


def test_start_planned_sec_below_min_rejected(client_with_db: TestClient) -> None:
    """planned_sec=30 (<60) 应 422。"""
    user = _register(client_with_db, email="pomo-bmin@example.com")
    r = client_with_db.post(
        "/api/pomodoro/start",
        headers=user["headers"],
        data={"planned_sec": "30", "activity": "vocab"},
    )
    assert r.status_code == 422


def test_start_planned_sec_above_max_rejected(client_with_db: TestClient) -> None:
    """planned_sec=7201 (>7200) 应 422。"""
    user = _register(client_with_db, email="pomo-bmax@example.com")
    r = client_with_db.post(
        "/api/pomodoro/start",
        headers=user["headers"],
        data={"planned_sec": "7201", "activity": "vocab"},
    )
    assert r.status_code == 422


# =============================================================
# 3. /api/pomodoro/{id}/complete
# =============================================================


def test_complete_writes_duration_and_note(client_with_db: TestClient) -> None:
    """complete 写入实际时长 + note,本地应能读到。"""
    user = _register(client_with_db, email="pomo-complete@example.com")
    data = _start_session(client_with_db, user["headers"], planned_sec=1500)
    sid = data["session_id"]

    r = client_with_db.post(
        f"/api/pomodoro/{sid}/complete",
        headers=user["headers"],
        data={"duration_sec": "1500", "interrupted": "false", "note": "完成"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["session_id"] == sid
    assert body["duration_sec"] == 1500

    # history 应能读回
    h = client_with_db.get("/api/pomodoro/history", headers=user["headers"])
    rows = h.json()
    assert len(rows) == 1
    assert rows[0]["duration_sec"] == 1500
    assert rows[0]["interrupted"] is False
    assert rows[0]["note"] == "完成"


def test_complete_interrupted_true_marks_session(client_with_db: TestClient) -> None:
    """interrupted=true → 中途放弃标记。"""
    user = _register(client_with_db, email="pomo-intr@example.com")
    data = _start_session(client_with_db, user["headers"], planned_sec=1500)
    sid = data["session_id"]

    r = client_with_db.post(
        f"/api/pomodoro/{sid}/complete",
        headers=user["headers"],
        data={"duration_sec": "300", "interrupted": "true", "note": "被打断"},
    )
    assert r.status_code == 200

    h = client_with_db.get("/api/pomodoro/history", headers=user["headers"])
    assert h.json()[0]["interrupted"] is True
    assert h.json()[0]["duration_sec"] == 300


def test_complete_unknown_session_returns_404(client_with_db: TestClient) -> None:
    """complete 一个不存在的 session_id → 404。"""
    user = _register(client_with_db, email="pomo-404@example.com")
    r = client_with_db.post(
        "/api/pomodoro/999999/complete",
        headers=user["headers"],
        data={"duration_sec": "100", "interrupted": "false", "note": ""},
    )
    assert r.status_code == 404


def test_complete_other_users_session_returns_404(client_with_db: TestClient) -> None:
    """跨用户 complete → 404（防越权）。"""
    user_a = _register(client_with_db, email="pomo-a@example.com")
    user_b = _register(client_with_db, email="pomo-b@example.com")

    # A 启 session
    data = _start_session(client_with_db, user_a["headers"])
    sid = data["session_id"]

    # B 尝试 complete A 的 session
    r = client_with_db.post(
        f"/api/pomodoro/{sid}/complete",
        headers=user_b["headers"],
        data={"duration_sec": "100", "interrupted": "false", "note": ""},
    )
    assert r.status_code == 404

    # 确认 A 的 session 没被 B 改写
    h = client_with_db.get("/api/pomodoro/history", headers=user_a["headers"])
    rows = h.json()
    assert rows[0]["duration_sec"] == 0     # 仍为 0


def test_complete_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录 complete → 401。"""
    r = client_with_db.post(
        "/api/pomodoro/1/complete",
        data={"duration_sec": "100", "interrupted": "false", "note": ""},
    )
    assert r.status_code == 401


def test_complete_negative_duration_rejected(client_with_db: TestClient) -> None:
    """duration_sec=-1 → 422。"""
    user = _register(client_with_db, email="pomo-neg@example.com")
    data = _start_session(client_with_db, user["headers"])
    sid = data["session_id"]

    r = client_with_db.post(
        f"/api/pomodoro/{sid}/complete",
        headers=user["headers"],
        data={"duration_sec": "-1", "interrupted": "false", "note": ""},
    )
    assert r.status_code == 422


# =============================================================
# 4. /api/pomodoro/history
# =============================================================


def test_history_user_isolation(client_with_db: TestClient) -> None:
    """两个用户互不可见。"""
    user_a = _register(client_with_db, email="pomo-iso-a@example.com")
    user_b = _register(client_with_db, email="pomo-iso-b@example.com")

    _start_session(client_with_db, user_a["headers"], activity="vocab")
    _start_session(client_with_db, user_a["headers"], activity="writing")
    _start_session(client_with_db, user_b["headers"], activity="exam")

    ha = client_with_db.get("/api/pomodoro/history", headers=user_a["headers"]).json()
    hb = client_with_db.get("/api/pomodoro/history", headers=user_b["headers"]).json()
    assert len(ha) == 2
    assert len(hb) == 1
    assert hb[0]["activity"] == "exam"


def test_history_respects_limit(client_with_db: TestClient) -> None:
    """limit 参数生效。"""
    user = _register(client_with_db, email="pomo-lim@example.com")
    for _ in range(5):
        _start_session(client_with_db, user["headers"])

    r = client_with_db.get(
        "/api/pomodoro/history?limit=3", headers=user["headers"]
    )
    assert len(r.json()) == 3


def test_history_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录访问 history → 401。"""
    r = client_with_db.get("/api/pomodoro/history")
    assert r.status_code == 401


# =============================================================
# 5. /api/pomodoro/today
# =============================================================


def test_today_empty_returns_zero(client_with_db: TestClient) -> None:
    """没数据时 today 返回 0。"""
    user = _register(client_with_db, email="pomo-today0@example.com")
    r = client_with_db.get("/api/pomodoro/today", headers=user["headers"])
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["total_sec"] == 0
    assert data["completed"] == 0
    assert data["abandoned"] == 0


def test_today_counts_completed_and_abandoned(client_with_db: TestClient) -> None:
    """完成 1 个、放弃 1 个 → today 正确分桶。"""
    user = _register(client_with_db, email="pomo-today@example.com")

    # 完成 1 个（duration 接近 planned）
    d1 = _start_session(client_with_db, user["headers"], planned_sec=1500)
    client_with_db.post(
        f"/api/pomodoro/{d1['session_id']}/complete",
        headers=user["headers"],
        data={"duration_sec": "1450", "interrupted": "false", "note": ""},
    )

    # 放弃 1 个
    d2 = _start_session(client_with_db, user["headers"], planned_sec=1500)
    client_with_db.post(
        f"/api/pomodoro/{d2['session_id']}/complete",
        headers=user["headers"],
        data={"duration_sec": "200", "interrupted": "true", "note": ""},
    )

    r = client_with_db.get("/api/pomodoro/today", headers=user["headers"])
    data = r.json()
    assert data["total"] == 2
    assert data["completed"] == 1
    assert data["abandoned"] == 1
    assert data["total_sec"] == 1450 + 200


def test_today_user_isolation(client_with_db: TestClient) -> None:
    """today 按 user 隔离。"""
    user_a = _register(client_with_db, email="pomo-toda@example.com")
    user_b = _register(client_with_db, email="pomo-todb@example.com")

    _start_session(client_with_db, user_a["headers"])
    _start_session(client_with_db, user_b["headers"])
    _start_session(client_with_db, user_b["headers"])

    ra = client_with_db.get("/api/pomodoro/today", headers=user_a["headers"]).json()
    rb = client_with_db.get("/api/pomodoro/today", headers=user_b["headers"]).json()
    assert ra["total"] == 1
    assert rb["total"] == 2


def test_today_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录 today → 401。"""
    r = client_with_db.get("/api/pomodoro/today")
    assert r.status_code == 401


# =============================================================
# 6. 端到端流程
# =============================================================


def test_e2e_start_then_complete_then_history_visible(client_with_db: TestClient) -> None:
    """完整流程：start → complete → history 可见 + today 计数。"""
    user = _register(client_with_db, email="pomo-e2e@example.com")

    # start
    data = _start_session(
        client_with_db, user["headers"],
        planned_sec=1500, activity="vocab", note="背 50 个词",
    )
    sid = data["session_id"]

    # complete
    r = client_with_db.post(
        f"/api/pomodoro/{sid}/complete",
        headers=user["headers"],
        data={"duration_sec": "1500", "interrupted": "false", "note": "背完"},
    )
    assert r.status_code == 200

    # history 校验
    h = client_with_db.get("/api/pomodoro/history", headers=user["headers"]).json()
    assert len(h) == 1
    assert h[0]["activity"] == "vocab"
    assert h[0]["duration_sec"] == 1500
    assert h[0]["note"] == "背完"

    # today 校验
    t = client_with_db.get("/api/pomodoro/today", headers=user["headers"]).json()
    assert t["total"] == 1
    assert t["completed"] == 1