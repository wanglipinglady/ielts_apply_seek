"""PrepResource API 端到端测试（v3.8 P3.1 Sprint 3 新增）。

覆盖:
1. /resources 页面:未登录跳登录;登录返回 HTML
2. /api/resources/list:无过滤返回全部
3. /api/resources/list:skill 过滤
4. /api/resources/list:level 过滤
5. /api/resources/list:is_featured 过滤
6. /api/resources/list:sort_by 参数
7. /api/resources/list:limit/offset 分页
8. /api/resources/{id}:存在返回完整资源
9. /api/resources/{id}:不存在返回 404
10. /api/resources/featured:4 个 skill 各 1 条
11. /api/resources/recommendation:有 featured 返回 featured
12. /api/resources/by-up:按作者查
13. /api/resources/ups:所有 UP 主 + 资源数
"""
from __future__ import annotations

import os
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fresh_db(tmp_path) -> Iterator[tuple]:
    """给每个测试一个全新 SQLite 文件 + 关闭 listening/reading 启动期种子 + 注册用户。"""
    db_path = str(tmp_path / "web.db")
    os.environ["IELTS_BUDDY_ENV"] = "dev"
    os.environ["IELTS_BUDDY_JWT_SECRET"] = "test-secret-" + "x" * 32
    os.environ["IELTS_BUDDY_WEB_DB_MODE"] = "sqlite"
    os.environ["IELTS_BUDDY_WEB_SQLITE_PATH"] = db_path
    # 关闭 listening/reading 启动期种子,避免在 SQLite 上与测试 seed 抢锁
    os.environ["IELTS_BUDDY_LISTENING_AUTO_SEED"] = "0"
    import importlib
    from ielts_buddy.web import config as web_config
    importlib.reload(web_config)

    from ielts_buddy.web.main import create_app
    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository

    app = create_app()
    repo = create_sqlite_web_user_repository(db_path)
    app.state.web_user_repo = repo

    with TestClient(app) as c:
        # 清空 lifespan 启动期种子的 ~29 条资源
        app.state.container.prep_resource._conn.execute(
            "DELETE FROM prep_resources"
        )
        app.state.container.prep_resource._conn.commit()
        # 在 fresh_db 中注册用户(不能用 conftest.registered_user,
        # 因为那是 :memory: 注册的 token,跨 db 无效)
        r = c.post(
            "/api/auth/register",
            data={"email": "alice@example.com", "password": "password123"},
        )
        assert r.status_code == 201
        body = r.json()
        token = body["access_token"]
        # 清空 cookies,防止前一次测试的 set-cookie 带到下一次
        c.cookies.clear()
        yield c, app, token


def _seed_resources(container) -> int:
    """手动塞几条不同 skill/level 的资源。返回 seed 数量。"""
    repo = container.prep_resource
    repo.seed_resource(
        title="Simon 口语 Part 1 套路",
        bv_id="BV1sim01",
        url="https://www.bilibili.com/video/BV1sim01",
        author_name="Simon",
        author_uid=90001,
        uploader_name="Simon 雅思",
        uploader_uid=90001,
        skill="speaking",
        video_type="methodology",
        level="5-6",
        method_summary="Simon 老师讲解口语 Part 1 答题套路和常见话题词汇。",
        source_status="verified_repost",
        publish_date="2023-06-01",
        duration_sec=900,
        outdated_risk="low",
        format_compatible="computer",
        computer_delivery_only=True,
        is_featured=True,
        recommend_score=9.5,
        sort_order=1,
        related_action_url="/speaking/practice",
        related_action_label="开始口语对练",
    )
    repo.seed_resource(
        title="王陆语料库精听",
        bv_id="BV1wanglu01",
        url="https://www.bilibili.com/video/BV1wanglu01",
        author_name="王陆",
        author_uid=90002,
        uploader_name="雅思王陆",
        uploader_uid=90002,
        skill="listening",
        video_type="methodology",
        level="5-6",
        method_summary="王陆语料库的点听、复数、缩写技巧。",
        source_status="verified_repost",
        publish_date="2024-01-15",
        duration_sec=1800,
        outdated_risk="low",
        format_compatible="computer",
        computer_delivery_only=True,
        is_featured=True,
        recommend_score=9.0,
        sort_order=2,
        related_action_url="/listening/practice",
        related_action_label="开始听力训练",
    )
    repo.seed_resource(
        title="刘洪波阅读真经 9-15-3 方法",
        bv_id="BV1lhb01",
        url="https://www.bilibili.com/video/BV1lhb01",
        author_name="刘洪波",
        author_uid=90003,
        uploader_name="刘洪波",
        uploader_uid=90003,
        skill="reading",
        video_type="methodology",
        level="6-7",
        method_summary="刘洪波 9-15-3 阅读法:9 分钟定位、15 分钟细读、3 分钟检查。",
        source_status="official",
        publish_date="2024-03-10",
        duration_sec=1200,
        outdated_risk="low",
        format_compatible="computer",
        computer_delivery_only=True,
        is_featured=True,
        recommend_score=9.8,
        sort_order=3,
        related_action_url="/reading/practice",
        related_action_label="开始阅读训练",
    )
    repo.seed_resource(
        title="非 featured 的写作资料",
        bv_id="BV1nfd01",
        url="https://www.bilibili.com/video/BV1nfd01",
        author_name="顾家北",
        author_uid=90004,
        uploader_name="顾家北",
        uploader_uid=90004,
        skill="writing",
        video_type="tutorial",
        level="6-7",
        method_summary="顾家北手把手教你写图表作文。",
        source_status="verified_repost",
        publish_date="2023-08-20",
        duration_sec=2400,
        outdated_risk="medium",
        format_compatible="paper",
        computer_delivery_only=False,
        is_featured=False,
        recommend_score=7.0,
        sort_order=100,
        related_action_url=None,
        related_action_label=None,
    )
    return 4


# =============================================================
# 页面
# =============================================================


class TestResourcesPage:
    def test_page_unauthenticated_redirects_to_login(self, fresh_db) -> None:
        client, _, _ = fresh_db
        r = client.get("/resources", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers.get("location", "")

    def test_page_authenticated_returns_html(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/resources",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert "备考资源广场" in r.text


# =============================================================
# /api/resources/list
# =============================================================


class TestResourcesList:
    def test_list_all_no_filter(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/list",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 4
        assert len(data["items"]) == 4

    def test_list_filter_by_skill(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/list?skill=reading",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["skill"] == "reading"
        assert data["items"][0]["author_name"] == "刘洪波"

    def test_list_filter_by_level(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/list?level=5-6",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2

    def test_list_filter_by_is_featured(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/list?is_featured=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        for item in data["items"]:
            assert item["is_featured"] is True

    def test_list_sort_by_recommend_score(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/list?sort_by=recommend_score",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = r.json()
        scores = [item["recommend_score"] for item in data["items"]]
        assert scores == sorted(scores, reverse=True)

    def test_list_sort_by_publish_date_returns_iso_string(self, fresh_db) -> None:
        """新增:发布排序应使用 MySQL/SQLite 通用语法,返回 publish_date 为 ISO 字符串。
        修复前 MySQL 报 'NULLS LAST' 语法错;修复后 publish_date 字段为 date 对象时
        _row_to_item 需归一化为 'YYYY-MM-DD' 字符串,否则 Pydantic 校验失败 500。"""
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/list?sort_by=publish_date",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # 排序: 2024-03-10 > 2024-01-15 > 2023-08-20 > 2023-06-01
        titles = [it["title"] for it in data["items"]]
        assert titles.index("刘洪波阅读真经 9-15-3 方法") < titles.index("王陆语料库精听")
        assert titles.index("王陆语料库精听") < titles.index("非 featured 的写作资料")
        assert titles.index("非 featured 的写作资料") < titles.index("Simon 口语 Part 1 套路")
        # publish_date 字段必须为 ISO 字符串(不是 datetime.date 对象)
        for item in data["items"]:
            assert isinstance(item["publish_date"], str)
            # 形如 2024-03-10
            assert len(item["publish_date"]) == 10
            assert item["publish_date"][4] == "-"

    def test_featured_returns_iso_string(self, fresh_db) -> None:
        """新增:featured 路径上的 publish_date 也需归一化,避免 500。"""
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/featured",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        for skill_key in ("listening", "reading", "speaking", "writing"):
            item = data.get(skill_key)
            if item is not None:
                assert isinstance(item["publish_date"], str)

    def test_list_pagination(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/list?limit=2&offset=0",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = r.json()
        assert data["total"] == 4
        assert len(data["items"]) == 2

        r2 = client.get(
            "/api/resources/list?limit=2&offset=2",
            headers={"Authorization": f"Bearer {token}"},
        )
        data2 = r2.json()
        assert len(data2["items"]) == 2
        ids1 = {item["id"] for item in data["items"]}
        ids2 = {item["id"] for item in data2["items"]}
        assert ids1.isdisjoint(ids2)


# =============================================================
# /api/resources/{id}
# =============================================================


class TestResourceDetail:
    def test_get_existing_resource(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/list",
            headers={"Authorization": f"Bearer {token}"},
        )
        first_id = r.json()["items"][0]["id"]
        r2 = client.get(
            f"/api/resources/{first_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["id"] == first_id
        assert data["title"]

    def test_get_missing_resource_returns_404(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.get(
            "/api/resources/99999",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404


# =============================================================
# /api/resources/featured
# =============================================================


class TestFeatured:
    def test_featured_returns_one_per_skill(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/featured",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["speaking"] is not None
        assert data["listening"] is not None
        assert data["reading"] is not None
        assert data["writing"] is None  # 顾家北那条 is_featured=False
        assert data["reading"]["recommend_score"] == 9.8


# =============================================================
# /api/resources/recommendation
# =============================================================


class TestRecommendation:
    def test_returns_featured_when_available(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/recommendation?skill=reading",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data is not None
        assert data["skill"] == "reading"

    def test_falls_back_to_top_score(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/recommendation?skill=writing",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data is not None
        assert data["skill"] == "writing"

    def test_returns_null_when_no_resources(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.get(
            "/api/resources/recommendation?skill=speaking",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json() is None


# =============================================================
# /api/resources/by-up
# =============================================================


class TestByUp:
    def test_by_up_returns_only_that_author(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        # 再加一条 Simon 的资源
        app.state.container.prep_resource.seed_resource(
            title="Simon 口语 Part 2 故事法",
            bv_id="BV1sim02",
            url="https://www.bilibili.com/video/BV1sim02",
            author_name="Simon",
            author_uid=90001,
            uploader_name="Simon 雅思",
            uploader_uid=90001,
            skill="speaking",
            video_type="methodology",
            level="5-6",
            method_summary="Simon Part 2 故事法。",
            source_status="verified_repost",
            publish_date="2023-07-01",
            duration_sec=900,
            outdated_risk="low",
            format_compatible="computer",
            computer_delivery_only=True,
            is_featured=False,
            recommend_score=8.5,
            sort_order=10,
        )
        r = client.get(
            "/api/resources/by-up?author_name=Simon",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        for item in data:
            assert item["author_name"] == "Simon"

    def test_by_up_empty(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.get(
            "/api/resources/by-up?author_name=NoSuchUP",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json() == []


# =============================================================
# /api/resources/ups
# =============================================================


class TestListUps:
    def test_ups_returns_unique_authors_with_counts(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_resources(app.state.container)
        r = client.get(
            "/api/resources/ups",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 4
        for item in data:
            assert item["count"] >= 1
            assert item["author_name"]
