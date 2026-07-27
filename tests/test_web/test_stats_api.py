"""Web 端 stats API + dashboard / stats 页面端到端测试。

覆盖：
- 无学习记录时返回全 0 / 空结构，前端不崩
- 多用户隔离：A 注册几条，B 看不到
- 页面 200 + 关键字段
- 受保护：未登录 302 / 401
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ielts_buddy.web.main import create_app


def _seed_learning_records(
    db_path: str, user_id: int, words_data: list[dict]
) -> None:
    """往 web_data.db 写 N 条学习记录（绕开 Service，方便测 stats 计算）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            word TEXT NOT NULL,
            word_data TEXT NOT NULL,
            memory_level INTEGER DEFAULT 0,
            next_review TEXT,
            learn_count INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0,
            first_learned TEXT,
            last_reviewed TEXT,
            is_starred INTEGER DEFAULT 0,
            is_difficult INTEGER DEFAULT 0,
            source TEXT DEFAULT 'builtin',
            UNIQUE (user_id, word)
        );
        """
    )
    for w in words_data:
        conn.execute(
            """INSERT OR REPLACE INTO learning_records
               (user_id, word, word_data, memory_level, next_review,
                learn_count, correct_count, wrong_count,
                first_learned, last_reviewed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, w["word"], w["word_data"], w["memory_level"],
                w.get("next_review"), w.get("learn_count", 1),
                w.get("correct_count", 0), w.get("wrong_count", 0),
                w.get("first_learned"), w.get("last_reviewed"),
            ),
        )
    conn.commit()
    conn.close()


# =============================================================
# 受保护
# =============================================================


def test_stats_api_unauthenticated_401(client_with_db: TestClient) -> None:
    r = client_with_db.get("/api/stats/summary")
    assert r.status_code == 401


def test_stats_page_unauthenticated_redirects(client_with_db: TestClient) -> None:
    r = client_with_db.get("/stats", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


# =============================================================
# 空数据
# =============================================================


def test_summary_with_no_data(client_with_db: TestClient) -> None:
    reg = client_with_db.post(
        "/api/auth/register",
        data={"email": "newbie@example.com", "password": "password123"},
    )
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    r = client_with_db.get("/api/stats/summary", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["today_new_words"] == 0
    assert body["total_words"] == 0
    assert body["accuracy"] == 0.0
    assert body["due_count"] == 0
    assert body["current_streak"] == 0


def test_overview_empty_returns_7_level_rows(client_with_db: TestClient) -> None:
    reg = client_with_db.post(
        "/api/auth/register",
        data={"email": "ov@example.com", "password": "password123"},
    )
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    r = client_with_db.get("/api/stats/overview", headers=h)
    body = r.json()
    # 7 个等级（艾宾浩斯 0-6）全 0
    assert len(body["level_distribution"]) == 7
    assert all(item["count"] == 0 for item in body["level_distribution"])
    # 7 天趋势
    assert len(body["trend"]) == 7
    # band 进度：词库为空时不返回（web 版退化）


# =============================================================
# 有数据
# =============================================================


def test_summary_with_real_data(
    client_with_db: TestClient, web_db_path: str
) -> None:
    reg = client_with_db.post(
        "/api/auth/register",
        data={"email": "data@example.com", "password": "password123"},
    )
    user_id = reg.json()["user"]["id"]

    today = date.today().isoformat()
    _seed_learning_records(
        web_db_path,
        user_id,
        [
            {
                "word": "abandon",
                "word_data": '{"word":"abandon","band":7}',
                "memory_level": 6,
                "next_review": "2099-12-31",
                "learn_count": 5,
                "correct_count": 5,
                "wrong_count": 0,
                "first_learned": f"{today}T08:00:00",
                "last_reviewed": f"{today}T10:00:00",
            },
            {
                "word": "boost",
                "word_data": '{"word":"boost","band":6}',
                "memory_level": 3,
                "next_review": today,  # 今天到期
                "learn_count": 3,
                "correct_count": 2,
                "wrong_count": 1,
                "first_learned": f"{today}T09:00:00",
                "last_reviewed": f"{today}T11:00:00",
            },
            {
                "word": "cabbage",
                "word_data": '{"word":"cabbage","band":5}',
                "memory_level": 5,  # 也算 mastered
                "next_review": "2099-12-31",
                "learn_count": 4,
                "correct_count": 4,
                "wrong_count": 0,
                "first_learned": "2026-01-01T08:00:00",
                "last_reviewed": "2026-01-02T10:00:00",
            },
        ],
    )
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    r = client_with_db.get("/api/stats/summary", headers=h)
    body = r.json()
    assert body["total_words"] == 3
    assert body["total_reviews"] == 12
    assert body["total_correct"] == 11
    assert body["total_wrong"] == 1
    assert 0.9 < body["accuracy"] < 0.92  # 11/12 = 0.9167
    assert body["mastered"] == 2  # level >= 5
    assert body["due_count"] == 1  # boost
    # 今日统计：abandon 和 boost 都是今天新学/复习
    assert body["today_new_words"] >= 2


def test_overview_band_progress_with_data(
    client_with_db: TestClient, web_db_path: str
) -> None:
    reg = client_with_db.post(
        "/api/auth/register",
        data={"email": "band@example.com", "password": "password123"},
    )
    user_id = reg.json()["user"]["id"]
    today = date.today().isoformat()
    _seed_learning_records(
        web_db_path,
        user_id,
        [
            {
                "word": "x",
                "word_data": '{"word":"x","band":7}',
                "memory_level": 5,
                "next_review": "2099-12-31",
                "first_learned": f"{today}T08:00:00",
                "last_reviewed": f"{today}T08:00:00",
            },
            {
                "word": "y",
                "word_data": '{"word":"y","band":6}',
                "memory_level": 4,
                "next_review": "2099-12-31",
                "first_learned": f"{today}T08:00:00",
                "last_reviewed": f"{today}T08:00:00",
            },
        ],
    )
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    r = client_with_db.get("/api/stats/overview", headers=h)
    body = r.json()
    # level_distribution: 2 条记录，1 个在 L5，1 个在 L4
    dist = {item["level"]: item["count"] for item in body["level_distribution"]}
    assert dist.get(5) == 1
    assert dist.get(4) == 1
    # band_progress: band 7 + band 6 各 1
    bands = {item["band"]: item for item in body["band_progress"]}
    assert 7 in bands
    assert 6 in bands


# =============================================================
# 多用户隔离
# =============================================================


def test_user_isolation(
    client_with_db: TestClient, web_db_path: str
) -> None:
    """A 注册并写入数据；B 注册后看不到 A 的数据。"""
    reg_a = client_with_db.post(
        "/api/auth/register",
        data={"email": "alice@x.com", "password": "password123"},
    )
    user_a = reg_a.json()["user"]["id"]
    today = date.today().isoformat()
    _seed_learning_records(
        web_db_path,
        user_a,
        [
            {
                "word": "a1",
                "word_data": '{"word":"a1","band":7}',
                "memory_level": 5,
                "next_review": "2099-12-31",
                "first_learned": f"{today}T08:00:00",
                "last_reviewed": f"{today}T08:00:00",
            }
        ],
    )

    # 重新发请求（之前 lifespan 已开，注入数据需新 client）
    reg_b = client_with_db.post(
        "/api/auth/register",
        data={"email": "bob@x.com", "password": "password123"},
    )
    h_b = {"Authorization": f"Bearer {reg_b.json()['access_token']}"}
    r = client_with_db.get("/api/stats/summary", headers=h_b)
    body = r.json()
    # B 没数据
    assert body["total_words"] == 0
    assert body["mastered"] == 0

    # A 看到自己的
    h_a = {"Authorization": f"Bearer {reg_a.json()['access_token']}"}
    r2 = client_with_db.get("/api/stats/summary", headers=h_a)
    assert r2.json()["total_words"] == 1


# =============================================================
# 页面
# =============================================================


def test_dashboard_page_with_data(
    client_with_db: TestClient, web_db_path: str
) -> None:
    reg = client_with_db.post(
        "/api/auth/register",
        data={"email": "page@x.com", "password": "password123"},
    )
    user_id = reg.json()["user"]["id"]
    today = date.today().isoformat()
    _seed_learning_records(
        web_db_path,
        user_id,
        [
            {
                "word": "z",
                "word_data": '{"word":"z","band":7}',
                "memory_level": 5,
                "next_review": "2099-12-31",
                "first_learned": f"{today}T08:00:00",
                "last_reviewed": f"{today}T08:00:00",
            }
        ],
    )
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    r = client_with_db.get("/dashboard", headers=h)
    assert r.status_code == 200
    assert "page@x.com" in r.text
    # 摘要卡片的"已掌握"应有 1
    assert "已掌握" in r.text
    assert ">1<" in r.text or "1</span>" in r.text


def test_stats_page_renders(
    client_with_db: TestClient, web_db_path: str
) -> None:
    reg = client_with_db.post(
        "/api/auth/register",
        data={"email": "sp@x.com", "password": "password123"},
    )
    user_id = reg.json()["user"]["id"]
    today = date.today().isoformat()
    _seed_learning_records(
        web_db_path,
        user_id,
        [
            {
                "word": "k",
                "word_data": '{"word":"k","band":7}',
                "memory_level": 3,
                "next_review": today,
                "first_learned": f"{today}T08:00:00",
                "last_reviewed": f"{today}T08:00:00",
            }
        ],
    )
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    r = client_with_db.get("/stats", headers=h)
    assert r.status_code == 200
    # 关键段落标题都渲染
    for header in ["摘要", "记忆等级分布", "各 Band 掌握进度", "最近 7 天"]:
        assert header in r.text
    # 7 行 level 表（L0-L6）
    assert r.text.count("L0") + r.text.count("L1") + r.text.count("L2") + \
           r.text.count("L3") + r.text.count("L4") + r.text.count("L5") + \
           r.text.count("L6") >= 7
