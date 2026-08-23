"""``/calendar`` 学习日历热力图 API 测试（v3.6 新增）。

覆盖：
1. /calendar 未登录 → 302 → /login
2. /calendar 已登录 → 200 + HTML
3. /api/calendar/data 未登录 → 401
4. /api/calendar/data 默认 3 月、响应字段完整
5. /api/calendar/data months 参数边界（1 / 12 合法；0 / 13 非法）
6. /api/calendar/data user 隔离（A 看不到 B 的数据）
7. /api/calendar/data 有数据时 streak / today 正确
8. /api/calendar/today 未登录 → 401
9. /api/calendar/today 字段完整性
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient


# =============================================================
# Helpers
# =============================================================


def _register(
    client: TestClient,
    email: str = "calendar@example.com",
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


def _seed_focus(client_with_db: TestClient, user_id: int,
                days_offset: int, duration_sec: int) -> None:
    """直接往 SQLite 写一条 focus_sessions（绕过 API 速度更快）。"""
    today = date.today()
    started = (today - timedelta(days=days_offset)).isoformat()
    conn: sqlite3.Connection = client_with_db.app.state.container.offline._conn
    conn.execute(
        """INSERT INTO focus_sessions
               (user_id, activity, planned_sec, duration_sec,
                interrupted, started_at, ended_at, created_at)
           VALUES (?, 'vocab', ?, ?, 0, ?, ?, ?)""",
        (user_id, max(duration_sec, 60), duration_sec,
         started, started, started),
    )
    conn.commit()


# =============================================================
# 1. /calendar 页面路由
# =============================================================


def test_calendar_page_unauthenticated_redirects_to_login(client_with_db: TestClient) -> None:
    r = client_with_db.get("/calendar", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/login"


def test_calendar_page_authenticated_returns_html(client_with_db: TestClient) -> None:
    user = _register(client_with_db, email="cal-page@example.com")
    r = client_with_db.get("/calendar", headers=user["headers"])
    assert r.status_code == 200
    assert "学习日历" in r.text


# =============================================================
# 2. /api/calendar/data
# =============================================================


def test_api_data_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    r = client_with_db.get("/api/calendar/data")
    assert r.status_code == 401


def test_api_data_default_3_months_shape(client_with_db: TestClient) -> None:
    """默认 months=3 → start_date 与 end_date 差 90 天,days 数=91。"""
    user = _register(client_with_db, email="cal-default@example.com")
    r = client_with_db.get("/api/calendar/data", headers=user["headers"])
    assert r.status_code == 200, r.text
    body = r.json()

    # 响应字段完整性
    assert set(body.keys()) == {
        "months", "start_date", "end_date", "days",
        "today_minutes", "today_level", "streak_current", "streak_max",
    }
    assert body["months"] == 3
    assert body["start_date"] < body["end_date"]
    # days 数 = months * 30 + 1（含起止两天）
    assert len(body["days"]) == 91

    # 每个 day 的字段
    d0 = body["days"][0]
    assert set(d0.keys()) == {"date", "minutes", "level"}

    # 空数据：所有 minutes=0, level=0, streak=0
    assert body["today_minutes"] == 0
    assert body["today_level"] == 0
    assert body["streak_current"] == 0
    assert body["streak_max"] == 0


def test_api_data_months_param_1_and_12(client_with_db: TestClient) -> None:
    """months=1 和 months=12 都合法。"""
    user = _register(client_with_db, email="cal-months@example.com")
    for m in (1, 12):
        r = client_with_db.get(
            f"/api/calendar/data?months={m}",
            headers=user["headers"],
        )
        assert r.status_code == 200
        body = r.json()
        assert body["months"] == m
        assert len(body["days"]) == m * 30 + 1


def test_api_data_months_param_invalid_422(client_with_db: TestClient) -> None:
    """months=0 或 months=13 → 422（Pydantic Query 校验）。"""
    user = _register(client_with_db, email="cal-invalid@example.com")
    for bad in (0, 13, -1):
        r = client_with_db.get(
            f"/api/calendar/data?months={bad}",
            headers=user["headers"],
        )
        assert r.status_code == 422, f"months={bad} 应被拒"


def test_api_data_user_isolation(client_with_db: TestClient) -> None:
    """A 看不到 B 的 focus_sessions。"""
    alice = _register(client_with_db, email="alice-iso@example.com")
    bob = _register(client_with_db, email="bob-iso@example.com")
    _seed_focus(client_with_db, user_id=int(bob["user_id"]),
                days_offset=0, duration_sec=25 * 60)

    r = client_with_db.get("/api/calendar/data", headers=alice["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["today_minutes"] == 0
    assert body["streak_current"] == 0


def test_api_data_with_focus_reflects_in_response(client_with_db: TestClient) -> None:
    """今天 1 次 25 min 番茄 → today_minutes=25, level=2。"""
    user = _register(client_with_db, email="cal-focus@example.com")
    _seed_focus(client_with_db, user_id=int(user["user_id"]),
                days_offset=0, duration_sec=25 * 60)

    r = client_with_db.get("/api/calendar/data", headers=user["headers"])
    body = r.json()
    assert body["today_minutes"] == 25
    assert body["today_level"] == 2
    assert body["streak_current"] == 1


def test_api_data_streak_three_consecutive_days(client_with_db: TestClient) -> None:
    """连续 3 天 → streak_current=3。"""
    user = _register(client_with_db, email="cal-streak@example.com")
    uid = int(user["user_id"])
    for off in range(3):
        _seed_focus(client_with_db, user_id=uid,
                    days_offset=off, duration_sec=25 * 60)

    r = client_with_db.get("/api/calendar/data", headers=user["headers"])
    body = r.json()
    assert body["streak_current"] == 3
    assert body["streak_max"] == 3


# =============================================================
# 3. /api/calendar/today
# =============================================================


def test_api_today_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    r = client_with_db.get("/api/calendar/today")
    assert r.status_code == 401


def test_api_today_shape(client_with_db: TestClient) -> None:
    """today 端点返回 {date, minutes, level}。"""
    user = _register(client_with_db, email="cal-today@example.com")
    r = client_with_db.get("/api/calendar/today", headers=user["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"date", "minutes", "level"}
    assert body["date"] == date.today().isoformat()
    assert body["minutes"] == 0
    assert body["level"] == 0


def test_api_today_after_one_focus(client_with_db: TestClient) -> None:
    user = _register(client_with_db, email="cal-today-focus@example.com")
    uid = int(user["user_id"])
    _seed_focus(client_with_db, user_id=uid,
                days_offset=0, duration_sec=25 * 60)

    r = client_with_db.get("/api/calendar/today", headers=user["headers"])
    body = r.json()
    assert body["minutes"] == 25
    assert body["level"] == 2
