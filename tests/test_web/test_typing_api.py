"""``/api/typing/*`` 机考打字端到端测试。

覆盖场景：
1. /typing 未登录 → 302 → /login
2. /api/typing/material 不需登录,默认 mode=words 返回 20 个词
3. /api/typing/submit 未登录 → 401
4. /api/typing/submit 成功路径：服务端复核 wpm / accuracy 并入库
5. /api/typing/history 按 user 隔离
6. /api/typing/stats 默认值 + 提交后聚合
7. /api/typing/submit 服务端 receipt：返回值含 server_metrics
8. mode 非法 → 默认 fallback words
"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


# =============================================================
# Fixtures
# =============================================================


ESSAY = (
    "The impact of climate change on global ecosystems cannot be overstated."
) * 3   # 长一些让 wpm 计算有意义


def _register(client: TestClient, email: str = "typer@example.com", password: str = "password123") -> dict:
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


def test_typing_page_unauthenticated_redirects_to_login(client_with_db: TestClient) -> None:
    """未登录访问 /typing → 302 → /login。"""
    r = client_with_db.get("/typing", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/login"


def test_typing_page_authenticated_returns_html(client_with_db: TestClient) -> None:
    """登录后访问 /typing → 200 + HTML 页面。"""
    user = _register(client_with_db, email="typer-html@example.com")
    r = client_with_db.get("/typing", headers=user["headers"])
    assert r.status_code == 200
    assert "机考打字" in r.text


# =============================================================
# 2. /api/typing/material (无需登录)
# =============================================================


def test_typing_material_words_default(client_with_db: TestClient) -> None:
    """默认 mode=words 返回 ≥1 个单词。"""
    r = client_with_db.get("/api/typing/material?mode=words&count=10")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "words"
    assert data["total_chars"] >= 10
    assert data["word_count"] >= 1
    # text 用空格分隔,至少 2 个词
    words = [w for w in data["text"].split() if w]
    assert len(words) >= 2


def test_typing_material_invalid_mode_falls_back_to_words(client_with_db: TestClient) -> None:
    """非法 mode → 默认 fallback words。"""
    r = client_with_db.get("/api/typing/material?mode=hack_me")
    assert r.status_code == 200
    assert r.json()["mode"] == "words"


def test_typing_material_passage_mode_returns_full_paragraph(client_with_db: TestClient) -> None:
    """passage 模式返回一整段长文本。"""
    r = client_with_db.get("/api/typing/material?mode=passage")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "passage"
    # passage 是预设短文,通常 ≥ 200 字符
    assert data["total_chars"] >= 100
    assert data["word_count"] >= 20


def test_typing_material_sentences_mode(client_with_db: TestClient) -> None:
    """sentences 模式从 Word.example 抽句。"""
    r = client_with_db.get("/api/typing/material?mode=sentences&count=3&band=7")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "sentences"
    # sentences 模式 word_count ≤ count(每个 example 就是 1 句)
    assert data["word_count"] >= 1


# =============================================================
# 3. /api/typing/submit
# =============================================================


def test_typing_submit_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    r = client_with_db.post(
        "/api/typing/submit",
        data={
            "mode": "words",
            "prompt_text": ESSAY,
            "typed_text": ESSAY,
            "duration_sec": 60,
            "completed": "true",
        },
    )
    assert r.status_code == 401


def test_typing_submit_records_into_db(client_with_db: TestClient) -> None:
    """成功路径：服务端复核后入库,history 看得到。"""
    user = _register(client_with_db, email="submit@example.com")

    # 故意 1 处拼错（"impact" → "imact"），且 typed 比 prompt 短 1 字符
    # → 总会有错误字符,但具体多少不精确,只断言 ≥1
    prompt = "The imact of climate change is serious."
    typed = "The impact of climate change is serious."

    r = client_with_db.post(
        "/api/typing/submit",
        data={
            "mode": "sentences",
            "prompt_text": prompt,
            "typed_text": typed,
            "duration_sec": 12,
            "completed": "true",
        },
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert "record" in body
    assert "server_metrics" in body

    sm = body["server_metrics"]
    assert sm["error_count"] >= 1
    assert 0 < sm["accuracy"] < 1.0
    assert sm["wpm"] > 0
    # total_chars 基于 prompt 总长（不是 typed）
    assert sm["total_chars"] == len(prompt)

    # 数据库里能查到
    hist = client_with_db.get(
        "/api/typing/history",
        headers=user["headers"],
    )
    assert hist.status_code == 200
    rows = hist.json()
    assert len(rows) == 1
    assert rows[0]["mode"] == "sentences"
    assert rows[0]["duration_sec"] == 12
    assert rows[0]["error_count"] >= 1


def test_typing_submit_short_duration_rejected(client_with_db: TestClient) -> None:
    """duration_sec < 1 → 422。"""
    user = _register(client_with_db, email="short-dur@example.com")
    r = client_with_db.post(
        "/api/typing/submit",
        data={
            "mode": "words",
            "prompt_text": "hello",
            "typed_text": "hello",
            "duration_sec": 0,
            "completed": "true",
        },
        headers=user["headers"],
    )
    assert r.status_code == 422


def test_typing_submit_empty_prompt_rejected(client_with_db: TestClient) -> None:
    """prompt_text 为空 → 422。"""
    user = _register(client_with_db, email="empty-prompt@example.com")
    r = client_with_db.post(
        "/api/typing/submit",
        data={
            "mode": "words",
            "prompt_text": "",
            "typed_text": "anything",
            "duration_sec": 5,
            "completed": "true",
        },
        headers=user["headers"],
    )
    assert r.status_code == 422


def test_typing_submit_invalid_mode_normalized(client_with_db: TestClient) -> None:
    """非法 mode 不报错,自动规范成 words。"""
    user = _register(client_with_db, email="bad-mode@example.com")
    r = client_with_db.post(
        "/api/typing/submit",
        data={
            "mode": "hacker_injected",
            "prompt_text": "test prompt",
            "typed_text": "test prompt",
            "duration_sec": 5,
            "completed": "true",
        },
        headers=user["headers"],
    )
    assert r.status_code == 200
    rec = r.json()["record"]
    assert rec["mode"] == "words"


# =============================================================
# 4. /api/typing/history
# =============================================================


def test_typing_history_user_isolation(client_with_db: TestClient) -> None:
    """Alice 与 Bob 各自提交,A 看不到 B 的。"""
    alice = _register(client_with_db, email="alice-typer@example.com")
    bob = _register(client_with_db, email="bob-typer@example.com")

    # Alice 提交 words 模式,Bob 提交 sentences 模式
    client_with_db.post(
        "/api/typing/submit",
        data={
            "mode": "words",
            "prompt_text": "alpha beta gamma",
            "typed_text": "alpha beta gamma",
            "duration_sec": 5,
            "completed": "true",
        },
        headers=alice["headers"],
    )
    client_with_db.post(
        "/api/typing/submit",
        data={
            "mode": "sentences",
            "prompt_text": "Climate change matters.",
            "typed_text": "clmate change matters.",
            "duration_sec": 7,
            "completed": "true",
        },
        headers=bob["headers"],
    )

    # Alice 看历史：1 条（words）
    alice_hist = client_with_db.get(
        "/api/typing/history",
        headers=alice["headers"],
    ).json()
    assert len(alice_hist) == 1
    assert alice_hist[0]["mode"] == "words"

    # Bob 看历史：1 条（sentences）
    bob_hist = client_with_db.get(
        "/api/typing/history",
        headers=bob["headers"],
    ).json()
    assert len(bob_hist) == 1
    assert bob_hist[0]["mode"] == "sentences"

    # cross mode 过滤：Alice 看 sentences 应为空
    only_s = client_with_db.get(
        "/api/typing/history?mode=sentences",
        headers=alice["headers"],
    ).json()
    assert only_s == []


def test_typing_history_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    r = client_with_db.get("/api/typing/history")
    assert r.status_code == 401


# =============================================================
# 5. /api/typing/stats
# =============================================================


def test_typing_stats_empty_returns_zero(client_with_db: TestClient) -> None:
    """从未练习过 → 总数=0,avg=0,max=0。"""
    user = _register(client_with_db, email="empty-stats@example.com")
    r = client_with_db.get(
        "/api/typing/stats",
        headers=user["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_count"] == 0
    assert body["average_wpm"] == 0.0
    assert body["max_wpm"] == 0.0


def test_typing_stats_aggregates_after_multiple_sessions(client_with_db: TestClient) -> None:
    """多次提交后 total/avg/max_wpm 正确聚合。"""
    user = _register(client_with_db, email="multi-stats@example.com")
    # 三次分别 WPM=20, 30, 50
    for wpm in (20.0, 30.0, 50.0):
        client_with_db.post(
            "/api/typing/submit",
            data={
                "mode": "words",
                "prompt_text": "x" * 100,
                "typed_text": "x" * 100,
                "duration_sec": 60,    # 全字符正确 → wpm = 100/5 = 20
                "completed": "true",
            },
            headers=user["headers"],
        )

    r = client_with_db.get(
        "/api/typing/stats",
        headers=user["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_count"] == 3
    # wpm 全部相同：100/5/1 = 20.0
    assert abs(body["average_wpm"] - 20.0) < 0.5
    assert body["max_wpm"] == 20.0


def test_typing_stats_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    r = client_with_db.get("/api/typing/stats")
    assert r.status_code == 401


# =============================================================
# 6. 服务端指标复核
# =============================================================


def test_typing_submit_server_metrics_differ_from_typed_when_partial(client_with_db: TestClient) -> None:
    """typed 短于 prompt 时：服务端按 prompt 计算 total_chars;accuracy 反映真实比例。"""
    user = _register(client_with_db, email="partial@example.com")
    prompt = "hello world"        # 11 chars
    typed = "hello"               # 5 chars（前 5 个与 prompt 完全相同；剩余 6 个未打）

    r = client_with_db.post(
        "/api/typing/submit",
        data={
            "mode": "words",
            "prompt_text": prompt,
            "typed_text": typed,
            "duration_sec": 5,
            "completed": "false",
        },
        headers=user["headers"],
    )
    assert r.status_code == 200
    sm = r.json()["server_metrics"]
    # total_chars 基于 prompt（11 字符）
    assert sm["total_chars"] == 11
    # typed 前 5 字符与 prompt 一致；剩余 6 个位置 typed 为空,算错误
    # 我们的算法 min(prompt, typed)=5,for i in 0..4 一致 → correct=5
    # errors = total_chars - correct_chars = 11 - 5 = 6
    assert sm["error_count"] == 6
    # accuracy = 5/11 ≈ 0.4545
    assert 0.45 < sm["accuracy"] < 0.46
    assert r.json()["record"]["completed"] is False
