"""``/speak`` 口语练习 Web 化端到端测试（v3.7 新增）。

覆盖：
1.  /speak 未登录 → 302 → /login
2.  /speak 已登录 → 200 + HTML 含「口语」
3.  /api/speak/topics 未登录 → 401
4.  /api/speak/topics → 200 + 默认全部话题
5.  /api/speak/topics?part=1 → 200 + 仅 Part 1
6.  /api/speak/parts → 200 + 包含 [1, 2, 3]
7.  /api/speak/random?part=2 → 200 + 返回一条 part=2 的话题
8.  /api/speak/vocab?topic=education → 200 + 返回词汇卡
9.  /api/speak/detail?topic_id=1 → 200 + 单条
10. /api/speak/count → 200 + 至少 30
"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


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


# =============================================================
# 1. /speak 页面路由
# =============================================================


def test_speak_page_unauthenticated_redirects_to_login(client_with_db: TestClient) -> None:
    """未登录访问 /speak → 302 → /login。"""
    r = client_with_db.get("/speak", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/login"


def test_speak_page_authenticated_returns_html(client_with_db: TestClient) -> None:
    """登录后访问 /speak → 200 + HTML 含「口语」。"""
    user = _register(client_with_db, email="speak-page@example.com")
    r = client_with_db.get("/speak", headers=user["headers"])
    assert r.status_code == 200, r.text
    assert "口语" in r.text


# =============================================================
# 2. /api/speak/topics
# =============================================================


def test_api_topics_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录 GET /api/speak/topics → 401。"""
    r = client_with_db.get("/api/speak/topics")
    assert r.status_code == 401


def test_api_topics_default_returns_all(client_with_db: TestClient) -> None:
    """默认 part=None → 返回全部话题（≥30）。

    builtin speaking_topics.json 共 61 个（Part1/2/3 各 20+）。
    """
    user = _register(client_with_db, email="speak-topics-all@example.com")
    r = client_with_db.get("/api/speak/topics", headers=user["headers"])
    assert r.status_code == 200, r.text
    topics = r.json()
    assert isinstance(topics, list)
    assert len(topics) >= 30

    # 字段完整性
    required = {"topic_id", "part", "topic", "questions", "vocab",
                "sample_answer", "tips"}
    for t in topics:
        assert required <= set(t.keys()), f"缺字段: {required - set(t.keys())}"

    # topic_id 必须 1-based 严格递增
    ids = [t["topic_id"] for t in topics]
    assert ids == list(range(1, len(topics) + 1))


def test_api_topics_part_1_only_returns_part1(client_with_db: TestClient) -> None:
    """part=1 → 仅返回 Part 1 话题。"""
    user = _register(client_with_db, email="speak-part1@example.com")
    r = client_with_db.get(
        "/api/speak/topics?part=1", headers=user["headers"]
    )
    assert r.status_code == 200, r.text
    topics = r.json()
    assert len(topics) >= 20
    for t in topics:
        assert t["part"] == 1


def test_api_topics_part_2_only_returns_part2(client_with_db: TestClient) -> None:
    """part=2 → 仅返回 Part 2 话题。"""
    user = _register(client_with_db, email="speak-part2@example.com")
    r = client_with_db.get(
        "/api/speak/topics?part=2", headers=user["headers"]
    )
    assert r.status_code == 200, r.text
    topics = r.json()
    assert len(topics) >= 20
    for t in topics:
        assert t["part"] == 2


def test_api_topics_invalid_part_returns_422(client_with_db: TestClient) -> None:
    """part=0 或 part=4 → 422（Pydantic Query 校验）。"""
    user = _register(client_with_db, email="speak-bad-part@example.com")
    for bad in (0, 4, -1):
        r = client_with_db.get(
            f"/api/speak/topics?part={bad}", headers=user["headers"]
        )
        assert r.status_code == 422, f"part={bad} 应被拒"


# =============================================================
# 3. /api/speak/parts
# =============================================================


def test_api_parts_returns_1_2_3(client_with_db: TestClient) -> None:
    """/api/speak/parts → 200 + [1, 2, 3]。"""
    user = _register(client_with_db, email="speak-parts@example.com")
    r = client_with_db.get("/api/speak/parts", headers=user["headers"])
    assert r.status_code == 200, r.text
    parts = r.json()
    assert parts == [1, 2, 3]


def test_api_parts_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录 /api/speak/parts → 401。"""
    r = client_with_db.get("/api/speak/parts")
    assert r.status_code == 401


# =============================================================
# 4. /api/speak/random
# =============================================================


def test_api_random_part_2_returns_part2(client_with_db: TestClient) -> None:
    """part=2 → 200 + 返回一条 part=2 的随机话题。"""
    user = _register(client_with_db, email="speak-rand2@example.com")
    r = client_with_db.get(
        "/api/speak/random?part=2", headers=user["headers"]
    )
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["part"] == 2
    # 字段完整性
    required = {"topic_id", "part", "part_label", "topic",
                "questions", "vocab", "sample_answer", "tips"}
    assert required <= set(t.keys())
    # Part 2 标签
    assert "Part 2" in t["part_label"]
    # 至少 1 个 question
    assert len(t["questions"]) >= 1
    # 至少 1 个词汇
    assert len(t["vocab"]) >= 1
    # sample_answer / tips 不为空
    assert len(t["sample_answer"]) > 0
    assert len(t["tips"]) > 0


def test_api_random_no_part_returns_any_part(client_with_db: TestClient) -> None:
    """无 part → 返回任意 Part 的话题（part ∈ [1,2,3]）。"""
    user = _register(client_with_db, email="speak-rand0@example.com")
    r = client_with_db.get("/api/speak/random", headers=user["headers"])
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["part"] in (1, 2, 3)


def test_api_random_invalid_part_returns_422(client_with_db: TestClient) -> None:
    """part=4 → 422。"""
    user = _register(client_with_db, email="speak-rand-bad@example.com")
    r = client_with_db.get(
        "/api/speak/random?part=4", headers=user["headers"]
    )
    assert r.status_code == 422


def test_api_random_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录 /api/speak/random → 401。"""
    r = client_with_db.get("/api/speak/random")
    assert r.status_code == 401


# =============================================================
# 5. /api/speak/vocab
# =============================================================


def test_api_vocab_topic_education_returns_card(client_with_db: TestClient) -> None:
    """?topic=education → 200 + 返回词汇卡。"""
    user = _register(client_with_db, email="speak-vocab@example.com")
    r = client_with_db.get(
        "/api/speak/vocab?topic=education", headers=user["headers"]
    )
    assert r.status_code == 200, r.text
    card = r.json()
    # 字段完整性
    required = {"part", "part_label", "topic", "vocab", "questions"}
    assert required <= set(card.keys())
    # 至少 1 个词汇 + 1 个 question
    assert len(card["vocab"]) >= 1
    assert len(card["questions"]) >= 1
    # topic 必须匹配关键词（不区分大小写、模糊）
    assert "education" in card["topic"].lower()


def test_api_vocab_case_insensitive(client_with_db: TestClient) -> None:
    """?topic=HOMETOWN 大小写不敏感。"""
    user = _register(client_with_db, email="speak-vocab-case@example.com")
    r = client_with_db.get(
        "/api/speak/vocab?topic=HOMETOWN", headers=user["headers"]
    )
    assert r.status_code == 200, r.text


def test_api_vocab_not_found_returns_404(client_with_db: TestClient) -> None:
    """不存在的 topic → 404。"""
    user = _register(client_with_db, email="speak-vocab-404@example.com")
    r = client_with_db.get(
        "/api/speak/vocab?topic=xyznonexistent_topic_qq",
        headers=user["headers"],
    )
    assert r.status_code == 404


def test_api_vocab_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录 /api/speak/vocab → 401。"""
    r = client_with_db.get("/api/speak/vocab?topic=education")
    assert r.status_code == 401


# =============================================================
# 6. /api/speak/detail
# =============================================================


def test_api_detail_topic_id_1_returns_one_topic(client_with_db: TestClient) -> None:
    """?topic_id=1 → 200 + 单条话题。"""
    user = _register(client_with_db, email="speak-detail@example.com")
    r = client_with_db.get(
        "/api/speak/detail?topic_id=1", headers=user["headers"]
    )
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["topic_id"] == 1
    required = {"topic_id", "part", "topic", "questions", "vocab",
                "sample_answer", "tips"}
    assert required <= set(t.keys())


def test_api_detail_invalid_topic_id_returns_404(client_with_db: TestClient) -> None:
    """?topic_id=99999 → 404。"""
    user = _register(client_with_db, email="speak-detail-404@example.com")
    r = client_with_db.get(
        "/api/speak/detail?topic_id=99999", headers=user["headers"]
    )
    assert r.status_code == 404


def test_api_detail_invalid_topic_id_returns_422(client_with_db: TestClient) -> None:
    """?topic_id=0 → 422（Pydantic 校验）。"""
    user = _register(client_with_db, email="speak-detail-bad@example.com")
    r = client_with_db.get(
        "/api/speak/detail?topic_id=0", headers=user["headers"]
    )
    assert r.status_code == 422


def test_api_detail_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录 /api/speak/detail → 401。"""
    r = client_with_db.get("/api/speak/detail?topic_id=1")
    assert r.status_code == 401


# =============================================================
# 7. /api/speak/count
# =============================================================


def test_api_count_default_at_least_30(client_with_db: TestClient) -> None:
    """默认 count ≥ 30（builtin 实际为 61）。"""
    user = _register(client_with_db, email="speak-count@example.com")
    r = client_with_db.get("/api/speak/count", headers=user["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body
    assert body["total"] >= 30


def test_api_count_part_1(client_with_db: TestClient) -> None:
    """part=1 → 返回 Part 1 数量（≥20）。"""
    user = _register(client_with_db, email="speak-count-p1@example.com")
    r = client_with_db.get(
        "/api/speak/count?part=1", headers=user["headers"]
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 20


def test_api_count_invalid_part_returns_422(client_with_db: TestClient) -> None:
    """part=4 → 422。"""
    user = _register(client_with_db, email="speak-count-bad@example.com")
    r = client_with_db.get(
        "/api/speak/count?part=4", headers=user["headers"]
    )
    assert r.status_code == 422


def test_api_count_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """未登录 /api/speak/count → 401。"""
    r = client_with_db.get("/api/speak/count")
    assert r.status_code == 401


# =============================================================
# 8. 端到端：页面 + API 串联
# =============================================================


def test_speak_page_has_three_tab_panels(client_with_db: TestClient) -> None:
    """页面必须含 3 个 tab panel，且默认 topics 是 is-open。"""
    user = _register(client_with_db, email="speak-tabs@example.com")
    r = client_with_db.get("/speak", headers=user["headers"])
    assert r.status_code == 200

    # 三个 tab 按钮
    assert 'data-tab="topics"' in r.text
    assert 'data-tab="practice"' in r.text
    assert 'data-tab="vocab"' in r.text

    # 默认 panel-topics 必须 is-open，其余两个无 is-open
    # 抓 #panel-topics 的开标签
    import re
    m = re.search(r'<div[^>]*id="panel-topics"[^>]*>', r.text)
    assert m is not None, "页面必须含 #panel-topics 元素"
    assert "is-open" in m.group(0), "panel-topics 默认应 is-open"

    m2 = re.search(r'<div[^>]*id="panel-practice"[^>]*>', r.text)
    assert m2 is not None
    assert "is-open" not in m2.group(0), "panel-practice 默认应隐藏"

    m3 = re.search(r'<div[^>]*id="panel-vocab"[^>]*>', r.text)
    assert m3 is not None
    assert "is-open" not in m3.group(0), "panel-vocab 默认应隐藏"


def test_speak_e2e_topics_match_random(client_with_db: TestClient) -> None:
    """端到端：/topics 与 /random 返回的话题 ID 集合应一致。"""
    user = _register(client_with_db, email="speak-e2e@example.com")
    topics = client_with_db.get(
        "/api/speak/topics", headers=user["headers"]
    ).json()
    topic_ids = {t["topic_id"] for t in topics}

    # 抽 5 次
    seen = set()
    for _ in range(5):
        r = client_with_db.get(
            "/api/speak/random", headers=user["headers"]
        )
        seen.add(r.json()["topic_id"])

    # 抽到的 id 必须是 topics 中的
    assert seen <= topic_ids