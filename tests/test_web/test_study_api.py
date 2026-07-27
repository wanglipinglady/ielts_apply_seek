"""Web 端学习（随机 + 复习）端到端测试。

覆盖：
- 页面访问控制（未登录 302）
- 选题 + 答题端点：record_learn 调用 + DB 写入
- 多用户隔离
- 复习空队列提示
- 选词过滤（已学过的词不再出现）
"""
from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient


# =============================================================
# 工具
# =============================================================


def _register(client: TestClient, email: str = "study@example.com") -> dict:
    r = client.post(
        "/api/auth/register",
        data={"email": email, "password": "password123"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "email": email,
        "user_id": body["user"]["id"],
        "access_token": body["access_token"],
    }


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _count_learning_records(db_path: str, user_id: int) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM learning_records WHERE user_id = ?",
        (user_id,),
    ).fetchone()["c"]
    conn.close()
    return n


# =============================================================
# 访问控制
# =============================================================


def test_random_page_unauthenticated_redirects(client_with_db: TestClient) -> None:
    r = client_with_db.get("/study/random", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_review_page_unauthenticated_redirects(client_with_db: TestClient) -> None:
    r = client_with_db.get("/study/review", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_answer_endpoint_unauthenticated_401(client_with_db: TestClient) -> None:
    r = client_with_db.post(
        "/api/study/answer",
        data={"word": "anything", "correct": "true", "mode": "random"},
    )
    # 页面路径 /study/* 会 302 跳 /login，API 路径 /api/study/* 一律 401
    assert r.status_code == 401


# =============================================================
# 随机学习：页面 + 答题
# =============================================================


def test_random_page_renders_with_word(
    client_with_db: TestClient,
) -> None:
    u = _register(client_with_db, "r1@x.com")
    r = client_with_db.get("/study/random", headers=_auth(u["access_token"]))
    assert r.status_code == 200
    # 至少有"随机学习"标题
    assert "随机学习" in r.text


def test_random_answer_records_to_db(
    client_with_db: TestClient, web_db_path: str
) -> None:
    u = _register(client_with_db, "r2@x.com")
    h = _auth(u["access_token"])
    # 答题（用任意词，vocab 找不到时 API 返 404；这里用真实词）
    # 先看词库有没有这个 word
    from ielts_buddy.services.vocab_service import VocabService
    v = VocabService()
    v.load_all()
    sample = v.random_words(count=1)[0]

    before = _count_learning_records(web_db_path, u["user_id"])
    r = client_with_db.post(
        "/api/study/answer",
        data={"word": sample.word, "correct": "true", "mode": "random"},
        headers=h,
    )
    assert r.status_code == 200
    after = _count_learning_records(web_db_path, u["user_id"])
    assert after == before + 1


def test_random_answer_increments_count(
    client_with_db: TestClient, web_db_path: str
) -> None:
    u = _register(client_with_db, "r3@x.com")
    h = _auth(u["access_token"])
    from ielts_buddy.services.vocab_service import VocabService
    v = VocabService()
    v.load_all()
    # 连答 5 个不同词
    words = v.random_words(count=5)
    for w in words:
        r = client_with_db.post(
            "/api/study/answer",
            data={"word": w.word, "correct": "true", "mode": "random"},
            headers=h,
        )
        assert r.status_code == 200, r.text
    n = _count_learning_records(web_db_path, u["user_id"])
    assert n == 5


def test_random_unknown_word_returns_404(client_with_db: TestClient) -> None:
    u = _register(client_with_db, "r4@x.com")
    r = client_with_db.post(
        "/api/study/answer",
        data={"word": "this-word-does-not-exist-zzz", "correct": "true", "mode": "random"},
        headers=_auth(u["access_token"]),
    )
    assert r.status_code == 404


# =============================================================
# 复习
# =============================================================


def test_review_page_empty_queue_shows_done_msg(client_with_db: TestClient) -> None:
    u = _register(client_with_db, "rv1@x.com")
    r = client_with_db.get("/study/review", headers=_auth(u["access_token"]))
    assert r.status_code == 200
    # 队列空时 partial 渲染"今日复习已完成"
    assert "今日复习已完成" in r.text


def test_review_answer_advances_level(
    client_with_db: TestClient, web_db_path: str
) -> None:
    u = _register(client_with_db, "rv2@x.com")
    user_id = u["user_id"]
    h = _auth(u["access_token"])

    # 预置一个到期词（next_review=今天）
    conn = sqlite3.connect(web_db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS learning_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            word TEXT NOT NULL, word_data TEXT NOT NULL,
            memory_level INTEGER DEFAULT 0, next_review TEXT,
            learn_count INTEGER DEFAULT 0, correct_count INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0, first_learned TEXT, last_reviewed TEXT,
            is_starred INTEGER DEFAULT 0, is_difficult INTEGER DEFAULT 0,
            source TEXT DEFAULT 'builtin', UNIQUE (user_id, word));
    """)
    # 找一个真实词
    from ielts_buddy.services.vocab_service import VocabService
    v = VocabService()
    v.load_all()
    w = v.random_words(count=1)[0]
    conn.execute(
        """INSERT INTO learning_records
           (user_id, word, word_data, memory_level, next_review,
            learn_count, correct_count, wrong_count,
            first_learned, last_reviewed, source)
           VALUES (?, ?, ?, 0, ?, 1, 0, 0, ?, ?, 'web')""",
        (user_id, w.word, w.model_dump_json(),
         "2000-01-01", "2024-01-01T08:00:00", "2024-01-01T08:00:00"),
    )
    conn.commit()
    conn.close()

    # 进入复习页能看到这个词
    r = client_with_db.get("/study/review", headers=h)
    assert r.status_code == 200
    assert w.word in r.text

    # 答对 → memory_level 应该从 0 升到 1
    r2 = client_with_db.post(
        "/api/study/answer",
        data={"word": w.word, "correct": "true", "mode": "review"},
        headers=h,
    )
    assert r2.status_code == 200
    conn2 = sqlite3.connect(web_db_path)
    conn2.row_factory = sqlite3.Row
    row = conn2.execute(
        "SELECT memory_level FROM learning_records WHERE user_id = ? AND word = ?",
        (user_id, w.word),
    ).fetchone()
    conn2.close()
    assert row["memory_level"] == 1


# =============================================================
# 多用户隔离
# =============================================================


def test_study_user_isolation(
    client_with_db: TestClient, web_db_path: str
) -> None:
    a = _register(client_with_db, "iso-a@x.com")
    b = _register(client_with_db, "iso-b@x.com")
    from ielts_buddy.services.vocab_service import VocabService
    v = VocabService()
    v.load_all()
    w = v.random_words(count=1)[0]

    # A 答 1 题
    client_with_db.post(
        "/api/study/answer",
        data={"word": w.word, "correct": "true", "mode": "random"},
        headers=_auth(a["access_token"]),
    )
    # A 有 1 条
    assert _count_learning_records(web_db_path, a["user_id"]) == 1
    # B 是 0 条
    assert _count_learning_records(web_db_path, b["user_id"]) == 0


# =============================================================
# HTMX 连续交互测试（模拟真实用户行为）
# =============================================================


def _extract_word_from_html(html: str) -> str | None:
    """从页面 HTML 中提取当前单词。"""
    import re
    m = re.search(r'<span class="word">([^<]+)</span>', html)
    return m.group(1) if m else None


def test_htmx_sequential_submissions_work(
    client_with_db: TestClient, web_db_path: str
) -> None:
    """模拟 HTMX 连续提交：答题→显示下一题→再答题。

    这是真实用户场景：第一次提交成功后，第二次提交也应该成功。
    如果 hx-target 配置错误，第二次会 422。
    """
    u = _register(client_with_db, "htmx1@x.com")
    h = _auth(u["access_token"])

    # 第一次：获取页面，提取单词，提交答案
    r1 = client_with_db.get("/study/random", headers=h)
    assert r1.status_code == 200
    word1 = _extract_word_from_html(r1.text)
    assert word1 is not None, f"页面没有找到单词: {r1.text[:500]}"

    r1_answer = client_with_db.post(
        "/api/study/answer",
        data={"word": word1, "correct": "false", "mode": "random"},
        headers=h,
    )
    assert r1_answer.status_code == 200, f"第一次提交失败: {r1_answer.status_code} {r1_answer.text}"

    # 第二次：从响应提取新单词，提交答案
    word2 = _extract_word_from_html(r1_answer.text)
    assert word2 is not None, f"响应没有找到下一个单词: {r1_answer.text[:500]}"
    assert word2 != word1, f"第二次应该返回不同的单词"

    r2_answer = client_with_db.post(
        "/api/study/answer",
        data={"word": word2, "correct": "false", "mode": "random"},
        headers=h,
    )
    assert r2_answer.status_code == 200, f"第二次提交失败: {r2_answer.status_code} {r2_answer.text}"

    # 第三次：再答一题
    word3 = _extract_word_from_html(r2_answer.text)
    assert word3 is not None, f"响应没有找到第三个单词: {r2_answer.text[:500]}"
    assert word3 not in (word1, word2), f"第三个单词应该与前两个不同"

    r3_answer = client_with_db.post(
        "/api/study/answer",
        data={"word": word3, "correct": "false", "mode": "random"},
        headers=h,
    )
    assert r3_answer.status_code == 200, f"第三次提交失败: {r3_answer.status_code} {r3_answer.text}"

    # 验证数据库记录
    n = _count_learning_records(web_db_path, u["user_id"])
    assert n == 3, f"应该记录 3 条学习记录，实际 {n}"


def test_htmx_no_duplicate_words_in_session(
    client_with_db: TestClient, web_db_path: str
) -> None:
    """连续答题时，同一个单词不应重复出现。"""
    u = _register(client_with_db, "htmx2@x.com")
    h = _auth(u["access_token"])

    seen_words: set[str] = set()
    current_word = None

    # 连续答题 10 次
    for i in range(10):
        if current_word is None:
            # 第一次：获取页面
            r = client_with_db.get("/study/random", headers=h)
        else:
            r = client_with_db.post(
                "/api/study/answer",
                data={"word": current_word, "correct": "true", "mode": "random"},
                headers=h,
            )
        assert r.status_code == 200, f"第{i+1}次请求失败: {r.text}"

        current_word = _extract_word_from_html(r.text)
        if current_word is None:
            # 词库用完了，测试通过
            break

        assert current_word not in seen_words, \
            f"单词 {current_word} 重复出现（已见过: {seen_words}）"
        seen_words.add(current_word)
