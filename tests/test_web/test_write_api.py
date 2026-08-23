"""``/write`` 写作辅助 Web 端到端测试（A 档）。

覆盖：
1. /write 未登录 → 302 → /login
2. /write 已登录 → 200 + HTML 含"写作辅助"
3. /api/write/topics 未登录 → 401
4. /api/write/topics?category=education → 200 + 仅返回 education 类
5. /api/write/templates → 200 + 含 introduction/body/conclusion/transition
6. /api/write/synonyms → 200 + 返回 synonyms 列表
7. /api/write/categories → 200 + 至少 7 个分类
8. /api/write/vocab?topic=education → 200 + 含模糊匹配命中
9. /api/write/template-types / topics/{id} 健壮性

注：本测试在 conftest 提供 ``client_with_db`` 之上,显式注入 write router。
主对话会在 main.py 里统一注册,所以这些测试只验证 router 行为本身。
"""
from __future__ import annotations

import os
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
def write_client(tmp_path) -> Iterator[TestClient]:
    """写路由专用 TestClient：自带 auth + write 两个 router。

    主对话会在 main.py 统一注册 write router；这里为了在不修改 main.py
    的前提下让测试可跑,在 fixture 里手工 include。
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
    from ielts_buddy.web.routers import write as write_routes

    app = FastAPI()
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates.env.globals["app_name"] = "IELTS Buddy"
    app.state.templates.env.globals["app_version"] = "0.1.0"
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # auth + write 路由都注册上（page_redirect 走 auth 的 token 校验）
    app.include_router(auth_routes.router)
    app.include_router(auth_routes.api_router)
    app.include_router(write_routes.router)
    app.include_router(write_routes.api_router)

    # 用独立内存 user repo,跟业务库隔离
    repo = create_sqlite_web_user_repository(":memory:")
    app.state.web_user_repo = repo

    with TestClient(app) as c:
        yield c

    repo.close()


def _register(
    client: TestClient,
    email: str = "writer@example.com",
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


# =============================================================
# 1. 页面路由
# =============================================================


def test_write_page_unauthenticated_redirects_to_login(write_client: TestClient) -> None:
    """未登录访问 /write → 302 → /login。"""
    r = write_client.get("/write", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/login"


def test_write_page_authenticated_returns_html(write_client: TestClient) -> None:
    """登录后访问 /write → 200 + HTML 含"写作辅助"。"""
    user = _register(write_client, email="write-page@example.com")
    r = write_client.get("/write", headers=user["headers"])
    assert r.status_code == 200
    assert "写作辅助" in r.text
    # 4 个 tab 都在
    assert 'data-tab="topics"' in r.text
    assert 'data-tab="templates"' in r.text
    assert 'data-tab="synonyms"' in r.text
    assert 'data-tab="vocab"' in r.text


# =============================================================
# 2. /api/write/categories
# =============================================================


def test_api_categories_unauthenticated_returns_401(write_client: TestClient) -> None:
    """未登录访问 /api/write/categories → 401。"""
    r = write_client.get("/api/write/categories")
    assert r.status_code == 401


def test_api_categories_returns_at_least_7(write_client: TestClient) -> None:
    """登录后访问 → 200 + 至少 7 个分类（education/environment/...）。"""
    user = _register(write_client, email="write-cats@example.com")
    r = write_client.get("/api/write/categories", headers=user["headers"])
    assert r.status_code == 200
    cats = r.json()
    assert isinstance(cats, list)
    assert len(cats) >= 7
    # 内置数据里应当包含这几个分类
    assert "education" in cats
    assert "environment" in cats


# =============================================================
# 3. /api/write/topics
# =============================================================


def test_api_topics_unauthenticated_returns_401(write_client: TestClient) -> None:
    r = write_client.get("/api/write/topics")
    assert r.status_code == 401


def test_api_topics_default_returns_all_categories(write_client: TestClient) -> None:
    """无 category 参数 → 返回全部话题。"""
    user = _register(write_client, email="write-topics-all@example.com")
    r = write_client.get("/api/write/topics", headers=user["headers"])
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) > 0
    # 每条都应有完整字段
    sample = rows[0]
    assert set(sample.keys()) == {
        "topic", "question", "category", "keywords", "band7_vocab",
    }


def test_api_topics_filter_by_education(write_client: TestClient) -> None:
    """?category=education → 仅返回 education 类话题。"""
    user = _register(write_client, email="write-edu@example.com")
    r = write_client.get(
        "/api/write/topics?category=education",
        headers=user["headers"],
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0
    for row in rows:
        assert row["category"].lower() == "education"

    # 对比不带筛选
    r_all = write_client.get(
        "/api/write/topics", headers=user["headers"]
    )
    rows_all = r_all.json()
    assert len(rows_all) > len(rows)  # education 是子集


def test_api_topics_case_insensitive_filter(write_client: TestClient) -> None:
    """?category=EDUCATION 大小写不敏感。"""
    user = _register(write_client, email="write-case@example.com")
    r1 = write_client.get(
        "/api/write/topics?category=education",
        headers=user["headers"],
    )
    r2 = write_client.get(
        "/api/write/topics?category=EDUCATION",
        headers=user["headers"],
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_api_topics_nonexistent_category_returns_empty(write_client: TestClient) -> None:
    """不存在的分类 → 200 + 空列表。"""
    user = _register(write_client, email="write-none@example.com")
    r = write_client.get(
        "/api/write/topics?category=zzz_not_a_category",
        headers=user["headers"],
    )
    assert r.status_code == 200
    assert r.json() == []


# =============================================================
# 4. /api/write/topics/{topic_id}
# =============================================================


def test_api_topic_detail_unauthenticated_returns_401(write_client: TestClient) -> None:
    r = write_client.get("/api/write/topics/1")
    assert r.status_code == 401


def test_api_topic_detail_first_topic(write_client: TestClient) -> None:
    """topic_id=1 → 返回第一个话题。"""
    user = _register(write_client, email="write-det1@example.com")
    r = write_client.get(
        "/api/write/topics/1", headers=user["headers"]
    )
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert "topic" in body and "question" in body


def test_api_topic_detail_out_of_range_returns_null(write_client: TestClient) -> None:
    """越界 topic_id → 200 + null（service 设计）。"""
    user = _register(write_client, email="write-oob@example.com")
    r = write_client.get(
        "/api/write/topics/999999", headers=user["headers"]
    )
    assert r.status_code == 200
    assert r.json() is None


def test_api_topic_detail_zero_id_rejected(write_client: TestClient) -> None:
    """topic_id=0 应被 Path(ge=1) 拒绝 → 422。"""
    user = _register(write_client, email="write-zero@example.com")
    r = write_client.get(
        "/api/write/topics/0", headers=user["headers"]
    )
    assert r.status_code == 422


# =============================================================
# 5. /api/write/templates
# =============================================================


def test_api_templates_unauthenticated_returns_401(write_client: TestClient) -> None:
    r = write_client.get("/api/write/templates")
    assert r.status_code == 401


def test_api_templates_default_contains_all_four_types(write_client: TestClient) -> None:
    """无 type 参数 → 包含 introduction/body/conclusion/transition 四类。"""
    user = _register(write_client, email="write-tpl@example.com")
    r = write_client.get("/api/write/templates", headers=user["headers"])
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0
    types_seen = {row["type"] for row in rows}
    assert "introduction" in types_seen
    assert "body" in types_seen
    assert "conclusion" in types_seen
    assert "transition" in types_seen
    # 字段完整
    sample = rows[0]
    assert set(sample.keys()) == {"type", "template", "translation", "example"}


def test_api_templates_filter_by_introduction(write_client: TestClient) -> None:
    """?type=introduction → 仅返回 introduction 类。"""
    user = _register(write_client, email="write-intro@example.com")
    r = write_client.get(
        "/api/write/templates?type=introduction",
        headers=user["headers"],
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0
    for row in rows:
        assert row["type"] == "introduction"


# =============================================================
# 6. /api/write/template-types
# =============================================================


def test_api_template_types_unauthenticated_returns_401(write_client: TestClient) -> None:
    r = write_client.get("/api/write/template-types")
    assert r.status_code == 401


def test_api_template_types_shape(write_client: TestClient) -> None:
    """返回 4 种模板类型。"""
    user = _register(write_client, email="write-ttypes@example.com")
    r = write_client.get(
        "/api/write/template-types", headers=user["headers"]
    )
    assert r.status_code == 200
    types = r.json()
    assert set(types) >= {"introduction", "body", "conclusion", "transition"}


# =============================================================
# 7. /api/write/synonyms
# =============================================================


def test_api_synonyms_unauthenticated_returns_401(write_client: TestClient) -> None:
    r = write_client.get("/api/write/synonyms")
    assert r.status_code == 401


def test_api_synonyms_default_returns_list(write_client: TestClient) -> None:
    """无 word 参数 → 返回完整 synonyms 列表。"""
    user = _register(write_client, email="write-syns@example.com")
    r = write_client.get("/api/write/synonyms", headers=user["headers"])
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) > 0
    # 字段完整
    sample = rows[0]
    assert set(sample.keys()) == {"common", "synonyms", "context"}
    # synonyms 是列表且非空
    assert isinstance(sample["synonyms"], list)
    assert len(sample["synonyms"]) > 0


def test_api_synonyms_filter_by_word(write_client: TestClient) -> None:
    """?word=important → 命中 'important' 这一条。"""
    user = _register(write_client, email="write-synword@example.com")
    r = write_client.get(
        "/api/write/synonyms?word=important",
        headers=user["headers"],
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    commons = [row["common"] for row in rows]
    assert "important" in commons


# =============================================================
# 8. /api/write/vocab
# =============================================================


def test_api_vocab_unauthenticated_returns_401(write_client: TestClient) -> None:
    r = write_client.get("/api/write/vocab?topic=education")
    assert r.status_code == 401


def test_api_vocab_fuzzy_match_education(write_client: TestClient) -> None:
    """?topic=education 模糊匹配 → 命中教育类话题。"""
    user = _register(write_client, email="write-vocab@example.com")
    r = write_client.get(
        "/api/write/vocab?topic=education",
        headers=user["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    # 关键词 / 高分词都应是非空列表
    assert isinstance(body["keywords"], list) and len(body["keywords"]) > 0
    assert isinstance(body["band7_vocab"], list) and len(body["band7_vocab"]) > 0
    # 响应字段完整
    assert set(body.keys()) == {
        "topic", "question", "category", "keywords", "band7_vocab",
    }


def test_api_vocab_fuzzy_match_chinese_keyword(write_client: TestClient) -> None:
    """?topic=教育 模糊匹配中文关键词也能命中。"""
    user = _register(write_client, email="write-vocab-cn@example.com")
    r = write_client.get(
        "/api/write/vocab?topic=%E6%95%99%E8%82%B2",  # URL-encoded "教育"
        headers=user["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    # 至少有部分中文话题能命中
    assert body is not None


def test_api_vocab_no_match_returns_null(write_client: TestClient) -> None:
    """找不到匹配 → 200 + null。"""
    user = _register(write_client, email="write-vocab-null@example.com")
    r = write_client.get(
        "/api/write/vocab?topic=zzz_no_such_topic_xyz",
        headers=user["headers"],
    )
    assert r.status_code == 200
    assert r.json() is None


def test_api_vocab_missing_topic_param_422(write_client: TestClient) -> None:
    """?topic 缺失 → 422（Pydantic 校验）。"""
    user = _register(write_client, email="write-vocab-422@example.com")
    r = write_client.get(
        "/api/write/vocab", headers=user["headers"]
    )
    assert r.status_code == 422


# =============================================================
# 9. 数据来源是只读 JSON（不写 DB；不需要 user_id 隔离测试）
# =============================================================


def test_write_endpoints_are_readonly_no_side_effects(write_client: TestClient) -> None:
    """所有 API 都是只读 GET；连发两次结果应一致。

    说明 WritingService 是纯只读、零 LLM、零副作用,无 user 隔离可言。
    """
    user = _register(write_client, email="write-readonly@example.com")

    # 连发两次,结果完全一致
    r1 = write_client.get("/api/write/categories", headers=user["headers"])
    r2 = write_client.get("/api/write/categories", headers=user["headers"])
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()

    t1 = write_client.get("/api/write/topics", headers=user["headers"])
    t2 = write_client.get("/api/write/topics", headers=user["headers"])
    assert t1.json() == t2.json()