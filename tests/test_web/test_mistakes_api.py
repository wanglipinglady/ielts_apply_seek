"""``/mistakes`` 错词本路由端到端测试（v3.6 新增）。

覆盖:
 1. /mistakes 未登录 → 302 → /login
 2. /mistakes 已登录 → 200 + HTML 含「错词本」
 3. /api/mistakes/words 错词列表,按 wrong_count DESC
 4. /api/mistakes/words?min_wrong=3 过滤
 5. /api/mistakes/words 未登录 → 401
 6. /api/mistakes/stats 聚合统计
 7. POST /api/mistakes/{word}/mark-correct → wrong_count 清 0
 8. POST /api/mistakes/{word}/add → 加 personal_vocab.mistakes 分类
 9. POST mark-correct 不存在的词 → 404
10. 数据隔离:用户 B 看不到用户 A 的错词
"""
from __future__ import annotations

import json as _json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient


WEB_DIR = Path(__file__).resolve().parents[2] / "src" / "ielts_buddy" / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture
def mistakes_client(tmp_path) -> Iterator[TestClient]:
    """错词本专用 TestClient:自带 auth + mistakes router。
    """
    os.environ.setdefault("IELTS_BUDDY_ENV", "dev")
    os.environ.setdefault("IELTS_BUDDY_JWT_SECRET", "test-secret-" + "x" * 32)
    os.environ.setdefault("IELTS_BUDDY_WEB_DB_MODE", "sqlite")
    os.environ["IELTS_BUDDY_WEB_SQLITE_PATH"] = str(tmp_path / "web_data.db")

    import importlib
    from ielts_buddy.web import config as web_config
    importlib.reload(web_config)

    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository
    from ielts_buddy.web.routers import auth as auth_routes
    from ielts_buddy.web.routers import mistakes as mistakes_routes

    app = FastAPI()
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates.env.globals["app_name"] = "IELTS Buddy"
    app.state.templates.env.globals["app_version"] = "0.1.0"
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(auth_routes.router)
    app.include_router(auth_routes.api_router)
    app.include_router(mistakes_routes.router)
    app.include_router(mistakes_routes.api_router)

    repo = create_sqlite_web_user_repository(":memory:")
    app.state.web_user_repo = repo

    sqlite_path = Path(str(tmp_path / "web_data.db"))
    from ielts_buddy.repositories.fallback_repo import create_fallback_container
    app.state.container = create_fallback_container(
        sqlite_db_path=sqlite_path,
        mysql_url="",
        prefer_mode="sqlite",
    )

    with TestClient(app) as c:
        yield c

    repo.close()
    try:
        app.state.container.close()
    except Exception:
        pass


@pytest.fixture
def client(mistakes_client: TestClient) -> TestClient:
    """通用 fixture 别名。"""
    return mistakes_client


# =============================================================
# Helpers
# =============================================================


def _register(client: TestClient, email: str, password: str = "password123") -> dict[str, Any]:
    r = client.post(
        "/api/auth/register",
        data={"email": email, "password": password},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "email": email,
        "password": password,
        "user_id": body["user"]["id"],
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
    }


def _auth(user: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['access_token']}"}


def _seed_mistakes(app: FastAPI, user_id: int, words: list[dict]) -> None:
    """直接写 learning_records 表,模拟错词数据。"""
    container = app.state.container
    from ielts_buddy.core.models import Word
    for w in words:
        # 错 N 次
        word_obj = Word(**w)
        for _ in range(w.get("_wrong_count", 1)):
            container.learning.upsert_record(user_id, word_obj, correct=False)


# =============================================================
# Tests
# =============================================================


def test_unauth_page_redirects_to_login(client: TestClient) -> None:
    """未登录访问 /mistakes → 302"""
    r = client.get("/mistakes", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["location"]


def test_authenticated_page_renders(client: TestClient) -> None:
    """已登录访问 /mistakes → 200,HTML 含「错词本」。"""
    user = _register(client, "alice@example.com")
    r = client.get("/mistakes", headers=_auth(user))
    assert r.status_code == 200
    assert "错词本" in r.text


def test_words_unauth_returns_401(client: TestClient) -> None:
    """未登录 → 401。"""
    r = client.get("/api/mistakes/words")
    assert r.status_code == 401


def test_words_empty_returns_zero(client: TestClient) -> None:
    """空数据 → total=0, words=[]。"""
    user = _register(client, "bob@example.com")
    r = client.get("/api/mistakes/words", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["words"] == []


def test_words_sorted_by_wrong_count_desc(client: TestClient) -> None:
    """错词按 wrong_count DESC 排序。"""
    user = _register(client, "carol@example.com")
    _seed_mistakes(
        client.app,  # type: ignore[attr-defined]
        user["user_id"],
        [
            {"word": "apple", "meaning": "苹果", "phonetic": "ˈæp.əl",
             "band": 5, "topic": "food", "_wrong_count": 1},
            {"word": "benefit", "meaning": "利益", "phonetic": "ˈbenɪfɪt",
             "band": 6, "topic": "society", "_wrong_count": 4},
            {"word": "abandon", "meaning": "放弃", "phonetic": "əˈbændən",
             "band": 7, "topic": "academic", "_wrong_count": 2},
        ],
    )
    r = client.get("/api/mistakes/words", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert [w["word"] for w in body["words"]] == ["benefit", "abandon", "apple"]
    # 字段完整
    first = body["words"][0]
    assert first["meaning"] == "利益"
    assert first["phonetic"] == "ˈbenɪfɪt"
    assert first["wrong_count"] == 4
    assert "error_rate" in first
    assert "last_reviewed" in first


def test_words_min_wrong_filter(client: TestClient) -> None:
    """min_wrong=3 过滤后只剩 1 个。"""
    user = _register(client, "david@example.com")
    _seed_mistakes(
        client.app,  # type: ignore[attr-defined]
        user["user_id"],
        [
            {"word": "apple", "meaning": "苹果", "band": 5, "_wrong_count": 1},
            {"word": "benefit", "meaning": "利益", "band": 6, "_wrong_count": 3},
        ],
    )
    r = client.get("/api/mistakes/words?min_wrong=3", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["words"][0]["word"] == "benefit"


def test_stats_aggregate(client: TestClient) -> None:
    """聚合统计正确。"""
    user = _register(client, "eve@example.com")
    _seed_mistakes(
        client.app,  # type: ignore[attr-defined]
        user["user_id"],
        [
            {"word": "apple", "meaning": "苹果", "band": 5, "_wrong_count": 1},
            {"word": "benefit", "meaning": "利益", "band": 6, "_wrong_count": 4},
            {"word": "abandon", "meaning": "放弃", "band": 7, "_wrong_count": 2},
        ],
    )
    r = client.get("/api/mistakes/stats", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["distinct_words"] == 3
    # 1+4+2 = 7
    assert body["total_wrong_count"] == 7
    assert body["last_7d_wrong"] == 3
    # top_offenders: benefit=4, abandon=2, apple=1
    assert body["top_offenders"][0]["word"] == "benefit"
    assert body["top_offenders"][0]["wrong_count"] == 4


def test_mark_correct_clears_wrong_count(client: TestClient) -> None:
    """标记某词已掌握 → wrong_count 清 0,该词不再出现在列表中。"""
    user = _register(client, "frank@example.com")
    _seed_mistakes(
        client.app,  # type: ignore[attr-defined]
        user["user_id"],
        [
            {"word": "apple", "meaning": "苹果", "band": 5, "_wrong_count": 1},
            {"word": "benefit", "meaning": "利益", "band": 6, "_wrong_count": 2},
        ],
    )
    # 标记 apple 已掌握
    r = client.post("/api/mistakes/apple/mark-correct", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["word"] == "apple"

    # 重新拉列表 apple 应消失
    r = client.get("/api/mistakes/words", headers=_auth(user))
    body = r.json()
    assert body["total"] == 1
    assert body["words"][0]["word"] == "benefit"


def test_mark_correct_unknown_word_returns_404(client: TestClient) -> None:
    """标记不存在的词 → 404。"""
    user = _register(client, "grace@example.com")
    r = client.post("/api/mistakes/zzznothing/mark-correct", headers=_auth(user))
    assert r.status_code == 404


def test_add_to_mistakes_category(client: TestClient) -> None:
    """手动加入 personal_vocab.mistakes 分类 → 200。"""
    user = _register(client, "henry@example.com")
    _seed_mistakes(
        client.app,  # type: ignore[attr-defined]
        user["user_id"],
        [{"word": "benefit", "meaning": "利益", "band": 6, "_wrong_count": 1}],
    )
    r = client.post("/api/mistakes/benefit/add", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["word"] == "benefit"


def test_user_isolation(client: TestClient) -> None:
    """用户 B 看不到用户 A 的错词。"""
    # 用户 A 注入错词
    user_a = _register(client, "alice_isolation@example.com")
    _seed_mistakes(
        client.app,  # type: ignore[attr-defined]
        user_a["user_id"],
        [{"word": "apple", "meaning": "苹果", "band": 5, "_wrong_count": 3}],
    )

    # 用户 B 不应看到 A 的数据
    user_b = _register(client, "bob_isolation@example.com")
    r = client.get("/api/mistakes/words", headers=_auth(user_b))
    body = r.json()
    assert body["total"] == 0


def test_min_wrong_validation(client: TestClient) -> None:
    """min_wrong=0 超出 ge=1 边界 → 422。"""
    user = _register(client, "iris@example.com")
    r = client.get("/api/mistakes/words?min_wrong=0", headers=_auth(user))
    assert r.status_code == 422
