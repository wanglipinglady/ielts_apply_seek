"""Reading Practice API 端到端测试（v3.8 P3.2 Sprint 3 新增）。

覆盖:
1. /reading/practice 页面:未登录跳登录;登录返回 HTML
2. /api/reading/practice/sections:Section 概览
3. /api/reading/practice/section/{section}:按 section 列套题
4. /api/reading/practice/section/{section}:非法 section 返回 422
5. /api/reading/practice/start:成功返回完整题组
6. /api/reading/practice/start:不存在 → 404
7. /api/reading/practice/start:非法 section → 422
8. /api/reading/practice/random:随机抽套题
9. /api/reading/practice/question/{qid}:单题详情
10. /api/reading/practice/question/{qid}:不存在 → 404
11. /api/reading/practice/submit:选择题判分 + 落 attempts
12. /api/reading/practice/submit:T/F/NG 容错
13. /api/reading/practice/submit:空答案 → 422
14. /api/reading/practice/submit:duration 越界 → 422
15. /api/reading/practice/history:分页
16. /api/reading/practice/history:section 过滤
17. /api/reading/practice/stats:聚合统计
"""
from __future__ import annotations

import os
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fresh_db(tmp_path) -> Iterator[tuple]:
    """每个测试一个全新 SQLite + 关闭 listening 启动期 + 注册用户。"""
    db_path = str(tmp_path / "web.db")
    os.environ["IELTS_BUDDY_ENV"] = "dev"
    os.environ["IELTS_BUDDY_JWT_SECRET"] = "test-secret-" + "x" * 32
    os.environ["IELTS_BUDDY_WEB_DB_MODE"] = "sqlite"
    os.environ["IELTS_BUDDY_WEB_SQLITE_PATH"] = db_path
    os.environ["IELTS_BUDDY_LISTENING_AUTO_SEED"] = "0"
    os.environ["IELTS_BUDDY_READING_AUTO_SEED"] = "0"
    import importlib
    from ielts_buddy.web import config as web_config
    importlib.reload(web_config)

    from ielts_buddy.web.main import create_app
    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository

    app = create_app()
    repo = create_sqlite_web_user_repository(db_path)
    app.state.web_user_repo = repo

    with TestClient(app) as c:
        # 清空 reading 表
        conn = app.state.container.reading_practice._conn
        conn.execute("DELETE FROM reading_attempts")
        conn.execute("DELETE FROM reading_passages")
        conn.commit()
        # 注册用户
        r = c.post(
            "/api/auth/register",
            data={"email": "alice@example.com", "password": "password123"},
        )
        assert r.status_code == 201
        token = r.json()["access_token"]
        c.cookies.clear()
        yield c, app, token


def _seed_passages(container, section="easy", set_id=1, count=3, qtype="multiple_choice"):
    """落 N 道题。"""
    repo = container.reading_practice
    for i in range(1, count + 1):
        repo.seed_passage(
            section=section, set_id=set_id, qid=i,
            passage_number=((i - 1) // 2) + 1,
            title=f"Title {section}-{set_id}-{i}",
            topic="Test Topic",
            question_type=qtype,
            word_count=650,
            passage_text=f"Passage text for question {i}. Discusses several points.",
            stem=f"Question {i}: what does the text say?",
            options=(["A opt", "B opt", "C opt", "D opt"]
                     if qtype in ("multiple_choice", "matching") else None),
            answer="A" if qtype in ("multiple_choice", "matching") else "key_term",
            explanation=f"Explanation {i}.",
            source_line=i,
        )


# =============================================================
# 页面
# =============================================================


class TestReadingPracticePage:
    def test_page_unauthenticated_redirects_to_login(self, fresh_db) -> None:
        client, _, _ = fresh_db
        r = client.get("/reading/practice", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers.get("location", "")

    def test_page_authenticated_returns_html(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 3)
        r = client.get(
            "/reading/practice",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert "Reading" in r.text


# =============================================================
# sections
# =============================================================


class TestSectionsAPI:
    def test_sections_returns_list(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 3)
        _seed_passages(app.state.container, "medium", 1, 3)
        r = client.get(
            "/api/reading/practice/sections",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "sections" in data
        sec_keys = {s["section"] for s in data["sections"]}
        assert "easy" in sec_keys
        assert "medium" in sec_keys
        for s in data["sections"]:
            assert "name" in s
            assert "total_sets" in s
            assert "total_passages" in s
            if int(s["total_passages"]) > 0:
                assert s["user_attempts"] == 0
                assert s["user_accuracy"] is None


# =============================================================
# section/{section}
# =============================================================


class TestSectionSetsAPI:
    def test_section_returns_sets(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 3)
        r = client.get(
            "/api/reading/practice/section/easy",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        s = data[0]
        assert s["section"] == "easy"
        assert s["set_id"] == 1
        assert s["question_count"] == 3

    def test_section_invalid_returns_422(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.get(
            "/api/reading/practice/section/unknown_sec",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422


# =============================================================
# start
# =============================================================


class TestStartAPI:
    def test_start_returns_full_set(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 3)
        r = client.post(
            "/api/reading/practice/start",
            json={"section": "easy", "set_id": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["section"] == "easy"
        assert data["set_id"] == 1
        assert data["section_label"]
        assert len(data["questions"]) == 3
        for q in data["questions"]:
            assert "answer" not in q
            assert "explanation" not in q
            assert q["id"]
            assert q["question_type_label"]

    def test_start_missing_set_returns_404(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.post(
            "/api/reading/practice/start",
            json={"section": "easy", "set_id": 99},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404

    def test_start_invalid_section_returns_422(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.post(
            "/api/reading/practice/start",
            json={"section": "bad", "set_id": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422

    def test_start_invalid_set_id_returns_422(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.post(
            "/api/reading/practice/start",
            json={"section": "easy", "set_id": 0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422


# =============================================================
# random
# =============================================================


class TestRandomAPI:
    def test_random_returns_a_set(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 3)
        _seed_passages(app.state.container, "medium", 1, 3)
        r = client.post(
            "/api/reading/practice/random",
            json={"section": "easy"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["section"] == "easy"
        assert data["set_id"] == 1

    def test_random_empty_returns_404(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.post(
            "/api/reading/practice/random",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404


# =============================================================
# question
# =============================================================


class TestQuestionAPI:
    def test_question_returns_normalized(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 1)
        qs = app.state.container.reading_practice.list_passages_by_set("easy", 1)
        qid = int(qs[0]["id"])
        r = client.get(
            f"/api/reading/practice/question/{qid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == qid
        assert "answer" not in data
        assert "explanation" not in data

    def test_question_missing_returns_404(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.get(
            "/api/reading/practice/question/99999",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404

    def test_question_invalid_qid_returns_422(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.get(
            "/api/reading/practice/question/0",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422


# =============================================================
# submit
# =============================================================


class TestSubmitAPI:
    def test_submit_correct_choice(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 1)
        qs = app.state.container.reading_practice.list_passages_by_set("easy", 1)
        qid = int(qs[0]["id"])
        r = client.post(
            "/api/reading/practice/submit",
            json={"question_id": qid, "user_answer": "A", "duration_sec": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["is_correct"] is True
        assert data["correct_answer"] == "A"
        assert data["attempt_id"] > 0
        assert data["explanation"]
        assert data["transcript"]

    def test_submit_tfng_true_tolerated(self, fresh_db) -> None:
        client, app, token = fresh_db
        container = app.state.container
        _seed_passages(container, "easy", 1, 1, qtype="tfng")
        qs = container.reading_practice.list_passages_by_set("easy", 1)
        qid = int(qs[0]["id"])
        conn = container.reading_practice._conn
        conn.execute(
            "UPDATE reading_passages SET answer='T' WHERE id=?", (qid,)
        )
        conn.commit()
        r = client.post(
            "/api/reading/practice/submit",
            json={"question_id": qid, "user_answer": "true", "duration_sec": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["is_correct"] is True

    def test_submit_empty_answer_returns_422(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 1)
        qs = app.state.container.reading_practice.list_passages_by_set("easy", 1)
        qid = int(qs[0]["id"])
        r = client.post(
            "/api/reading/practice/submit",
            json={"question_id": qid, "user_answer": "", "duration_sec": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422

    def test_submit_invalid_duration_returns_422(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 1)
        qs = app.state.container.reading_practice.list_passages_by_set("easy", 1)
        qid = int(qs[0]["id"])
        r = client.post(
            "/api/reading/practice/submit",
            json={"question_id": qid, "user_answer": "A", "duration_sec": 9999},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422

    def test_submit_missing_question_returns_404(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.post(
            "/api/reading/practice/submit",
            json={"question_id": 99999, "user_answer": "A", "duration_sec": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404


# =============================================================
# history
# =============================================================


class TestHistoryAPI:
    def test_history_pagination(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 2)
        qs = app.state.container.reading_practice.list_passages_by_set("easy", 1)
        for q in qs:
            client.post(
                "/api/reading/practice/submit",
                json={"question_id": int(q["id"]), "user_answer": "A", "duration_sec": 10},
                headers={"Authorization": f"Bearer {token}"},
            )
        r = client.get(
            "/api/reading/practice/history?page=1&size=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2
        assert len(data["items"]) == 1
        r2 = client.get(
            "/api/reading/practice/history?page=2&size=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert len(r2.json()["items"]) == 1

    def test_history_filter_section(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 1)
        _seed_passages(app.state.container, "medium", 1, 1)
        container = app.state.container
        easy_q = container.reading_practice.list_passages_by_set("easy", 1)[0]
        medium_q = container.reading_practice.list_passages_by_set("medium", 1)[0]
        h = {"Authorization": f"Bearer {token}"}
        client.post(
            "/api/reading/practice/submit",
            json={"question_id": int(easy_q["id"]), "user_answer": "A", "duration_sec": 5},
            headers=h,
        )
        client.post(
            "/api/reading/practice/submit",
            json={"question_id": int(medium_q["id"]), "user_answer": "A", "duration_sec": 5},
            headers=h,
        )
        r_easy = client.get(
            "/api/reading/practice/history?section=easy", headers=h
        )
        assert r_easy.status_code == 200
        items = r_easy.json()["items"]
        for it in items:
            assert it["section"] == "easy"


# =============================================================
# stats
# =============================================================


class TestStatsAPI:
    def test_stats_empty(self, fresh_db) -> None:
        client, _, token = fresh_db
        r = client.get(
            "/api/reading/practice/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total_attempts"] == 0
        assert data["correct"] == 0
        assert data["accuracy"] is None
        assert data["by_section"] == {}

    def test_stats_after_attempts(self, fresh_db) -> None:
        client, app, token = fresh_db
        _seed_passages(app.state.container, "easy", 1, 2)
        qs = app.state.container.reading_practice.list_passages_by_set("easy", 1)
        h = {"Authorization": f"Bearer {token}"}
        client.post(
            "/api/reading/practice/submit",
            json={"question_id": int(qs[0]["id"]), "user_answer": "A", "duration_sec": 5},
            headers=h,
        )
        client.post(
            "/api/reading/practice/submit",
            json={"question_id": int(qs[1]["id"]), "user_answer": "B", "duration_sec": 5},
            headers=h,
        )
        r = client.get(
            "/api/reading/practice/stats", headers=h
        )
        data = r.json()
        assert data["total_attempts"] == 2
        assert data["correct"] == 1
        assert data["accuracy"] == 50.0
        assert "easy" in data["by_section"]
        assert data["by_section"]["easy"]["attempts"] == 2
        assert data["by_section"]["easy"]["correct"] == 1
