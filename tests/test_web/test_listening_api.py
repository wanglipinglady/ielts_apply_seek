"""``/listen`` 听力路由端到端测试（B 档 Web 化）。

覆盖：
 1. /listen 未登录 → 302 → /login
 2. /listen 已登录 → 200 + HTML 含「听力」
 3. /api/listening/resources 未登录 → 401
 4. /api/listening/resources?type=podcast → 200 + 仅 podcast
 5. /api/listening/resources?difficulty=beginner → 200 + 仅 beginner
 6. /api/listening/detail?idx=1 → 200 + 含 url/description
 7. /api/listening/dictation?count=5 → 200 + 5 个题,每题含 word/phonetic/definition
 8. /api/listening/record POST → 200 + 正确题数 / 错误题数
 9. /api/listening/record user 隔离（A 提交不污染 B）
10. /api/listening/dictation 参数校验（count=0 / count=100 422）

注：本测试在 conftest 提供 ``client_with_db`` 之上,显式注入 listening router。
主对话会在 main.py 里统一注册,所以这些测试只验证 router 行为本身。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient


# =============================================================
# Fixtures
# =============================================================


WEB_DIR = Path(__file__).resolve().parents[2] / "src" / "ielts_buddy" / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


@pytest.fixture
def listening_client(tmp_path) -> Iterator[TestClient]:
    """听力路由专用 TestClient：自带 auth + listening 两个 router。

    主对话会在 main.py 统一注册 listening router；这里为了在不修改
    main.py 的前提下让测试可跑,在 fixture 里手工 include。
    """
    os.environ.setdefault("IELTS_BUDDY_ENV", "dev")
    os.environ.setdefault("IELTS_BUDDY_JWT_SECRET", "test-secret-" + "x" * 32)
    os.environ.setdefault("IELTS_BUDDY_WEB_DB_MODE", "sqlite")
    os.environ["IELTS_BUDDY_WEB_SQLITE_PATH"] = str(tmp_path / "web_data.db")

    # 重载 config,确保拿到刚设的 sqlite path
    import importlib
    from ielts_buddy.web import config as web_config
    importlib.reload(web_config)

    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository
    from ielts_buddy.web.routers import auth as auth_routes
    from ielts_buddy.web.routers import listening as listening_routes

    app = FastAPI()
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates.env.globals["app_name"] = "IELTS Buddy"
    app.state.templates.env.globals["app_version"] = "0.1.0"
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # auth + listening 路由都注册上
    app.include_router(auth_routes.router)
    app.include_router(auth_routes.api_router)
    app.include_router(listening_routes.router)
    app.include_router(listening_routes.api_router)

    # 用独立内存 user repo,跟业务库隔离
    repo = create_sqlite_web_user_repository(":memory:")
    app.state.web_user_repo = repo

    # 业务容器走 fallback（SQLite 默认 backend）,包含 learning_records 表
    from ielts_buddy.repositories.fallback_repo import create_fallback_container
    sqlite_path = Path(str(tmp_path / "web_data.db"))
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


# 提供 ``client_with_db`` 别名兼容任务规范中的引用
@pytest.fixture
def client_with_db(listening_client: TestClient) -> TestClient:
    """任务规范里使用的 fixture 名,转发到 ``listening_client``。"""
    return listening_client


# =============================================================
# Helpers
# =============================================================


def _register(
    client: TestClient,
    email: str,
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


def _get_dictation(
    client: TestClient, headers: dict, count: int = 5
) -> list[dict[str, Any]]:
    """调用 dictation 接口返回题目列表（含 word/phonetic/definition）。"""
    r = client.get(
        f"/api/listening/dictation?count={count}", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["questions"]


# =============================================================
# 1. /listen 页面
# =============================================================


def test_listen_page_unauthenticated_redirects_to_login(
    client_with_db: TestClient,
) -> None:
    """未登录访问 /listen → 302 → /login。"""
    r = client_with_db.get("/listen", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/login"


def test_listen_page_authenticated_returns_html(
    client_with_db: TestClient,
) -> None:
    """登录后访问 /listen → 200 + HTML 含「听力」。"""
    user = _register(client_with_db, email="listen-page@example.com")
    r = client_with_db.get("/listen", headers=user["headers"])
    assert r.status_code == 200
    assert "听力" in r.text


# =============================================================
# 2. /api/listening/resources
# =============================================================


def test_resources_unauthenticated_returns_401(
    client_with_db: TestClient,
) -> None:
    """未登录访问 /api/listening/resources → 401。"""
    r = client_with_db.get("/api/listening/resources")
    assert r.status_code == 401


def test_resources_filter_by_type_podcast(client_with_db: TestClient) -> None:
    """type=podcast → 仅 podcast。"""
    user = _register(client_with_db, email="listen-res-type@example.com")
    r = client_with_db.get(
        "/api/listening/resources?type=podcast",
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) > 0, "listening_resources.json 至少应有 1 个 podcast"
    assert all(it["type"] == "podcast" for it in rows)
    # 每个 item 必备字段
    for it in rows:
        assert {"idx", "type", "difficulty", "title", "url",
                "description", "topics", "free"} <= set(it.keys())
        assert isinstance(it["idx"], int) and it["idx"] > 0


def test_resources_filter_by_type_no_match(client_with_db: TestClient) -> None:
    """type 不存在 → 列表为空。"""
    user = _register(client_with_db, email="listen-res-empty@example.com")
    r = client_with_db.get(
        "/api/listening/resources?type=doesnotexist",
        headers=user["headers"],
    )
    assert r.status_code == 200
    assert r.json() == []


def test_resources_filter_by_difficulty_beginner(
    client_with_db: TestClient,
) -> None:
    """difficulty=beginner → 仅 beginner。"""
    user = _register(
        client_with_db, email="listen-res-diff@example.com"
    )
    r = client_with_db.get(
        "/api/listening/resources?difficulty=beginner",
        headers=user["headers"],
    )
    assert r.status_code == 200
    rows = r.json()
    assert all(it["difficulty"] == "beginner" for it in rows)


def test_resources_no_filter_returns_all(client_with_db: TestClient) -> None:
    """不传 filter → 全部资源。"""
    user = _register(client_with_db, email="listen-res-all@example.com")
    r = client_with_db.get(
        "/api/listening/resources", headers=user["headers"]
    )
    assert r.status_code == 200
    rows = r.json()
    # JSON 里有多条；非空 + 不同 type 共存
    assert len(rows) > 1
    types = {it["type"] for it in rows}
    assert len(types) >= 2


# =============================================================
# 3. /api/listening/detail
# =============================================================


def test_detail_unauthenticated_returns_401(
    client_with_db: TestClient,
) -> None:
    """未登录访问 /api/listening/detail → 401。"""
    r = client_with_db.get("/api/listening/detail?idx=1")
    assert r.status_code == 401


def test_detail_idx_1_returns_resource(client_with_db: TestClient) -> None:
    """idx=1 → 200 + 含 url/description。"""
    user = _register(client_with_db, email="listen-detail@example.com")
    r = client_with_db.get(
        "/api/listening/detail?idx=1", headers=user["headers"]
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["idx"] == 1
    assert body["url"], "详情必须含 url"
    assert body["description"], "详情必须含 description"
    assert body["title"]
    assert body["type"]
    assert body["difficulty"]


def test_detail_idx_out_of_range_returns_404(
    client_with_db: TestClient,
) -> None:
    """idx 越界 → 404。"""
    user = _register(client_with_db, email="listen-404@example.com")
    r = client_with_db.get(
        "/api/listening/detail?idx=99999", headers=user["headers"]
    )
    assert r.status_code == 404


def test_detail_idx_zero_returns_404_or_422(
    client_with_db: TestClient,
) -> None:
    """idx=0 (Pydantic ge=1 拒绝) → 422。"""
    user = _register(client_with_db, email="listen-zero@example.com")
    r = client_with_db.get(
        "/api/listening/detail?idx=0", headers=user["headers"]
    )
    # 422 (Pydantic Query validation) or 404 都合理
    assert r.status_code in (404, 422)


# =============================================================
# 4. /api/listening/dictation
# =============================================================


def test_dictation_unauthenticated_returns_401(
    client_with_db: TestClient,
) -> None:
    """未登录 access → 401。"""
    r = client_with_db.get("/api/listening/dictation?count=5")
    assert r.status_code == 401


def test_dictation_returns_5_questions(client_with_db: TestClient) -> None:
    """count=5 → 5 个题,每题含 word/phonetic/definition。"""
    user = _register(client_with_db, email="listen-d5@example.com")
    qs = _get_dictation(client_with_db, user["headers"], count=5)
    assert len(qs) == 5
    for q in qs:
        assert "word" in q
        assert "phonetic" in q
        assert "definition" in q
        assert q["word"]
        # phonetic / definition 可以为空字符串但 key 必须存在


def test_dictation_count_too_small_returns_422(
    client_with_db: TestClient,
) -> None:
    """count=0 → 422。"""
    user = _register(client_with_db, email="listen-d0@example.com")
    r = client_with_db.get(
        "/api/listening/dictation?count=0", headers=user["headers"]
    )
    assert r.status_code == 422


def test_dictation_count_too_large_returns_422(
    client_with_db: TestClient,
) -> None:
    """count=100 → 422 (le=50)。"""
    user = _register(client_with_db, email="listen-d100@example.com")
    r = client_with_db.get(
        "/api/listening/dictation?count=100", headers=user["headers"]
    )
    assert r.status_code == 422


# =============================================================
# 5. /api/listening/record
# =============================================================


def test_record_unauthenticated_returns_401(
    client_with_db: TestClient,
) -> None:
    """未登录 record → 401。"""
    r = client_with_db.post(
        "/api/listening/record",
        json={"answers": [{"word": "hello", "answer": "hello"}]},
    )
    assert r.status_code == 401


def test_record_writes_correct_and_wrong_counts(
    client_with_db: TestClient,
) -> None:
    """提交 3 个答案(2 对 1 错) → 正确 2 / 错误 1。"""
    user = _register(client_with_db, email="listen-rec@example.com")
    qs = _get_dictation(client_with_db, user["headers"], count=3)
    assert len(qs) == 3

    answers = [
        {"word": qs[0]["word"], "answer": qs[0]["word"]},   # 对
        {"word": qs[1]["word"], "answer": qs[1]["word"]},   # 对
        {"word": qs[2]["word"], "answer": "wrong_answer"},   # 错
    ]
    r = client_with_db.post(
        "/api/listening/record",
        headers=user["headers"],
        json={"answers": answers},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["correct"] == 2
    assert body["wrong"] == 1
    assert set(body["correct_words"]) == {qs[0]["word"], qs[1]["word"]}
    assert body["wrong_words"] == [qs[2]["word"]]


def test_record_persists_to_learning_records(
    client_with_db: TestClient,
) -> None:
    """record 落库 → 可在 SQLite learning_records 表读到。"""
    user = _register(client_with_db, email="listen-persist@example.com")
    qs = _get_dictation(client_with_db, user["headers"], count=2)

    answers = [
        {"word": qs[0]["word"], "answer": qs[0]["word"]},
        {"word": qs[1]["word"], "answer": qs[1]["word"]},
    ]
    client_with_db.post(
        "/api/listening/record",
        headers=user["headers"],
        json={"answers": answers},
    )

    # 直接读 SQLite（容器 offline backend）
    container = client_with_db.app.state.container
    conn: sqlite3.Connection = container.offline._conn
    rows = conn.execute(
        "SELECT user_id, word, learn_count, correct_count, "
        "wrong_count, source FROM learning_records WHERE user_id = ?",
        (int(user["user_id"]),),
    ).fetchall()
    assert len(rows) == 2
    words_in_db = {row["word"] for row in rows}
    assert words_in_db == {qs[0]["word"], qs[1]["word"]}
    # source 都是 "builtin"
    assert all(row["source"] == "builtin" for row in rows)
    # 正确题 learn_count = 1, correct_count = 1, wrong_count = 0
    for row in rows:
        assert row["learn_count"] == 1
        assert row["correct_count"] == 1
        assert row["wrong_count"] == 0


def test_record_user_isolation(client_with_db: TestClient) -> None:
    """A 提交不污染 B;A / B 的 learning_records 互不可见。"""
    alice = _register(client_with_db, email="listen-iso-alice@example.com")
    bob = _register(client_with_db, email="listen-iso-bob@example.com")

    qs = _get_dictation(client_with_db, alice["headers"], count=2)

    # Alice 提交(两个都对)
    r = client_with_db.post(
        "/api/listening/record",
        headers=alice["headers"],
        json={
            "answers": [
                {"word": qs[0]["word"], "answer": qs[0]["word"]},
                {"word": qs[1]["word"], "answer": qs[1]["word"]},
            ],
        },
    )
    assert r.status_code == 200

    # Bob 不提交 → 应没有任何记录
    container = client_with_db.app.state.container
    conn: sqlite3.Connection = container.offline._conn

    bob_rows = conn.execute(
        "SELECT word FROM learning_records WHERE user_id = ?",
        (int(bob["user_id"]),),
    ).fetchall()
    assert len(bob_rows) == 0, "Bob 不应有任何 learning_records"

    alice_rows = conn.execute(
        "SELECT word FROM learning_records WHERE user_id = ?",
        (int(alice["user_id"]),),
    ).fetchall()
    assert len(alice_rows) == 2
    alice_words = {r["word"] for r in alice_rows}
    assert alice_words == {qs[0]["word"], qs[1]["word"]}


def test_record_empty_answers_returns_zero(
    client_with_db: TestClient,
) -> None:
    """空 answers → 200 + total=0/0/0。"""
    user = _register(client_with_db, email="listen-empty@example.com")
    r = client_with_db.post(
        "/api/listening/record",
        headers=user["headers"],
        json={"answers": []},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["correct"] == 0
    assert body["wrong"] == 0


def test_record_all_wrong(client_with_db: TestClient) -> None:
    """全错 → correct=0, wrong=total。"""
    user = _register(client_with_db, email="listen-wrong@example.com")
    qs = _get_dictation(client_with_db, user["headers"], count=3)
    answers = [{"word": q["word"], "answer": ""} for q in qs]
    r = client_with_db.post(
        "/api/listening/record",
        headers=user["headers"],
        json={"answers": answers},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["correct"] == 0
    assert body["wrong"] == 3
