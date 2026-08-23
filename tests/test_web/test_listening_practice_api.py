"""``/listen/practice`` 真·听力题库路由端到端测试（v3.7 P2 Sprint 2 新增）。

覆盖:
 1. /listen/practice 未登录 → 302 → /login
 2. /listen/practice 已登录 → 200 + HTML 含「真·听力题库」
 3. /api/listening/practice/sections 未登录 → 401
 4. /api/listening/practice/sections 已登录 → 200 + sections 数组
 5. /api/listening/practice/section/{n} → 200 + sets 数组
 6. /api/listening/practice/start → 200 + 返回 questions
 7. /api/listening/practice/start 非法 section → 422
 8. /api/listening/practice/start 不存在的 set → 404
 9. /api/listening/practice/random → 200 + 抽中一套
10. /api/listening/practice/question/{qid} → 200
11. /api/listening/practice/submit → 200 + is_correct
12. /api/listening/practice/submit 空答案 → 422
13. /api/listening/practice/submit 不存在 qid → 404
14. /api/listening/practice/history → 200
15. /api/listening/practice/stats → 200
16. /api/listening/practice/audio/{qid} 无音频 → 404
17. IDOR / 数据隔离:用户 B 看不到用户 A 的 stats
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient


WEB_DIR = Path(__file__).resolve().parents[2] / "src" / "ielts_buddy" / "web"
TEMPLATES_DIR = WEB_DIR / "templates"


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture
def lp_client(tmp_path) -> Iterator[TestClient]:
    """真·听力题库专用 TestClient:已种子一些题目。"""
    os.environ["IELTS_BUDDY_ENV"] = "dev"
    os.environ["IELTS_BUDDY_JWT_SECRET"] = "test-secret-" + "x" * 32
    os.environ["IELTS_BUDDY_WEB_DB_MODE"] = "sqlite"
    os.environ["IELTS_BUDDY_WEB_SQLITE_PATH"] = str(tmp_path / "web_data.db")

    # 强制重新加载 config 模块（清除缓存）
    import importlib
    from ielts_buddy.web import config as web_config
    importlib.reload(web_config)

    from ielts_buddy.repositories.fallback_repo import create_fallback_container
    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository
    from ielts_buddy.web.routers import auth as auth_routes
    from ielts_buddy.web.routers import listening_practice as lp_routes

    # 构造容器并预种子 Section 1 + 2
    container = create_fallback_container(
        sqlite_db_path=tmp_path / "web_data.db",
        mysql_url="",
        prefer_mode="sqlite",
    )
    repo = container.listening_practice
    for sec in (1, 2):
        for set_idx in (1, 2):
            for qid in range(1, 5):
                repo.seed_question(
                    section=sec, set_id=set_idx, qid=qid,
                    scenario=f"Sec{sec} Set{set_idx} Q{qid}",
                    question_type="multiple_choice",
                    stem=f"Question {qid}: pick one?",
                    options=["First", "Second", "Third", "Fourth"],
                    answer="A",
                    explanation="First is correct.",
                    transcript=f"Transcript for section {sec} question {qid}.",
                )

    app = FastAPI()
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.container = container
    # 复用 auth 路由
    app.include_router(auth_routes.router)
    app.include_router(auth_routes.api_router)
    # 业务路由
    app.include_router(lp_routes.router)
    app.include_router(lp_routes.api_router)
    # 注入 web_user_repo
    from pathlib import Path as _P
    app.state.web_user_repo = create_sqlite_web_user_repository(
        str(tmp_path / "web_data.db")
    )

    with TestClient(app) as c:
        yield c

    try:
        app.state.web_user_repo.close()
    except Exception:
        pass
    try:
        container.close()
    except Exception:
        pass


def _register(client: TestClient, email: str) -> dict:
    r = client.post(
        "/api/auth/register",
        data={"email": email, "password": "password123"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _auth_headers(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['access_token']}"}


# =============================================================
# 1-2. 页面路由
# =============================================================


class TestPageRoutes:
    def test_listen_practice_unauthenticated_redirects(self, lp_client):
        r = lp_client.get("/listen/practice", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    def test_listen_practice_authenticated_returns_html(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.get(
            "/listen/practice", headers=_auth_headers(body)
        )
        assert r.status_code == 200
        assert "真·听力题库" in r.text or "Listening Practice" in r.text


# =============================================================
# 3-4. /sections
# =============================================================


class TestSections:
    def test_sections_unauthenticated_returns_401(self, lp_client):
        r = lp_client.get("/api/listening/practice/sections")
        assert r.status_code == 401

    def test_sections_authenticated_returns_list(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.get(
            "/api/listening/practice/sections",
            headers=_auth_headers(body),
        )
        assert r.status_code == 200
        data = r.json()
        assert "sections" in data
        # 至少 Section 1 和 2 有数据
        nums = [s["section"] for s in data["sections"]]
        assert 1 in nums
        assert 2 in nums


# =============================================================
# 5. /section/{n}
# =============================================================


class TestSectionSets:
    def test_section_sets_returns_list(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.get(
            "/api/listening/practice/section/1",
            headers=_auth_headers(body),
        )
        assert r.status_code == 200
        rows = r.json()
        # 2 套
        assert len(rows) >= 2
        # 每条都有 set_id + scenario
        for row in rows:
            assert "set_id" in row
            assert "scenario" in row

    def test_section_sets_invalid_section(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.get(
            "/api/listening/practice/section/5",
            headers=_auth_headers(body),
        )
        assert r.status_code == 422


# =============================================================
# 6-8. /start
# =============================================================


class TestStart:
    def test_start_returns_questions(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 1},
            headers=_auth_headers(body),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["section"] == 1
        assert data["set_id"] == 1
        # 4 道选择题
        assert len(data["questions"]) == 4
        # 题目不含 answer/explanation(防泄漏)
        for q in data["questions"]:
            assert "answer" not in q
            assert "explanation" not in q
            assert "transcript" not in q
            assert q["options"] is not None
            assert len(q["options"]) == 4

    def test_start_invalid_section(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 5, "set_id": 1},
            headers=_auth_headers(body),
        )
        assert r.status_code == 422

    def test_start_missing_set(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 999},
            headers=_auth_headers(body),
        )
        assert r.status_code == 404


# =============================================================
# 9. /random
# =============================================================


class TestRandom:
    def test_random_returns_set(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.post(
            "/api/listening/practice/random",
            json={},
            headers=_auth_headers(body),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["section"] in (1, 2)
        assert data["set_id"] >= 1
        assert len(data["questions"]) >= 1

    def test_random_with_section_filter(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.post(
            "/api/listening/practice/random",
            json={"section": 2},
            headers=_auth_headers(body),
        )
        assert r.status_code == 200
        assert r.json()["section"] == 2


# =============================================================
# 10. /question/{qid}
# =============================================================


class TestQuestionDetail:
    def test_question_detail(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        # 用 start 拿到第一题的 id
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 1},
            headers=_auth_headers(body),
        )
        qid = r.json()["questions"][0]["id"]
        # 拿详情
        r2 = lp_client.get(
            f"/api/listening/practice/question/{qid}",
            headers=_auth_headers(body),
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["id"] == qid

    def test_question_detail_not_found(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.get(
            "/api/listening/practice/question/99999",
            headers=_auth_headers(body),
        )
        assert r.status_code == 404


# =============================================================
# 11-13. /submit
# =============================================================


class TestSubmit:
    def test_submit_correct_answer(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        # 拿到一道题
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 1},
            headers=_auth_headers(body),
        )
        qid = r.json()["questions"][0]["id"]
        # 提交正确答案 A
        r2 = lp_client.post(
            "/api/listening/practice/submit",
            json={
                "question_id": qid,
                "user_answer": "A",
                "duration_sec": 12.0,
                "played_count": 1,
            },
            headers=_auth_headers(body),
        )
        assert r2.status_code == 200
        out = r2.json()
        assert out["is_correct"] is True
        assert out["correct_answer"] == "A"
        assert out["attempt_id"] > 0

    def test_submit_wrong_answer(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 1},
            headers=_auth_headers(body),
        )
        qid = r.json()["questions"][0]["id"]
        r2 = lp_client.post(
            "/api/listening/practice/submit",
            json={"question_id": qid, "user_answer": "B"},
            headers=_auth_headers(body),
        )
        assert r2.status_code == 200
        assert r2.json()["is_correct"] is False

    def test_submit_empty_answer(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 1},
            headers=_auth_headers(body),
        )
        qid = r.json()["questions"][0]["id"]
        r2 = lp_client.post(
            "/api/listening/practice/submit",
            json={"question_id": qid, "user_answer": "  "},
            headers=_auth_headers(body),
        )
        assert r2.status_code == 422

    def test_submit_nonexistent_question(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        r = lp_client.post(
            "/api/listening/practice/submit",
            json={"question_id": 99999, "user_answer": "A"},
            headers=_auth_headers(body),
        )
        assert r.status_code == 404

    def test_submit_records_next_question(self, lp_client):
        """最后一题 → next_question_id=null;中间题 → next_question_id 非空。"""
        body = _register(lp_client, "alice@example.com")
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 1},
            headers=_auth_headers(body),
        )
        qs = r.json()["questions"]
        # 第 1 题 → next 非空
        r2 = lp_client.post(
            "/api/listening/practice/submit",
            json={"question_id": qs[0]["id"], "user_answer": "A"},
            headers=_auth_headers(body),
        )
        assert r2.json()["next_question_id"] is not None
        # 第 4 题(最后)→ next 为 null
        r3 = lp_client.post(
            "/api/listening/practice/submit",
            json={"question_id": qs[-1]["id"], "user_answer": "A"},
            headers=_auth_headers(body),
        )
        assert r3.json()["next_question_id"] is None


# =============================================================
# 14. /history
# =============================================================


class TestHistory:
    def test_history_returns_records(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        # 提交一次
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 1},
            headers=_auth_headers(body),
        )
        qid = r.json()["questions"][0]["id"]
        lp_client.post(
            "/api/listening/practice/submit",
            json={"question_id": qid, "user_answer": "A"},
            headers=_auth_headers(body),
        )
        # 拉历史
        r2 = lp_client.get(
            "/api/listening/practice/history",
            headers=_auth_headers(body),
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1


# =============================================================
# 15. /stats
# =============================================================


class TestStats:
    def test_stats_returns_aggregates(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        # 提交一次
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 1},
            headers=_auth_headers(body),
        )
        qid = r.json()["questions"][0]["id"]
        lp_client.post(
            "/api/listening/practice/submit",
            json={"question_id": qid, "user_answer": "A"},
            headers=_auth_headers(body),
        )
        # 查 stats
        r2 = lp_client.get(
            "/api/listening/practice/stats",
            headers=_auth_headers(body),
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["total_attempts"] >= 1
        assert "by_section" in data


# =============================================================
# 16. /audio/{qid}
# =============================================================


class TestAudio:
    def test_audio_not_generated_returns_404(self, lp_client):
        body = _register(lp_client, "alice@example.com")
        # 没合成音频 → 404
        r = lp_client.get(
            "/api/listening/practice/audio/1",
            headers=_auth_headers(body),
        )
        assert r.status_code == 404


# =============================================================
# 17. 数据隔离:用户 B 看不到用户 A 的 stats
# =============================================================


class TestUserIsolation:
    def test_user_b_sees_zero_stats(self, lp_client):
        body_a = _register(lp_client, "alice@example.com")
        body_b = _register(lp_client, "bob@example.com")

        # Alice 答一道题
        r = lp_client.post(
            "/api/listening/practice/start",
            json={"section": 1, "set_id": 1},
            headers=_auth_headers(body_a),
        )
        qid = r.json()["questions"][0]["id"]
        lp_client.post(
            "/api/listening/practice/submit",
            json={"question_id": qid, "user_answer": "A"},
            headers=_auth_headers(body_a),
        )

        # Alice stats ≥ 1
        ra = lp_client.get(
            "/api/listening/practice/stats",
            headers=_auth_headers(body_a),
        )
        assert ra.json()["total_attempts"] >= 1

        # Bob stats = 0
        rb = lp_client.get(
            "/api/listening/practice/stats",
            headers=_auth_headers(body_b),
        )
        assert rb.json()["total_attempts"] == 0

        # Bob 看不到 Alice 的 history
        rh = lp_client.get(
            "/api/listening/practice/history",
            headers=_auth_headers(body_b),
        )
        assert rh.json()["total"] == 0