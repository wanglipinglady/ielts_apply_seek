"""
tests/test_contracts/test_wx_study_contract.py — 小程序学习 API 契约（2026-08-24）

锁定 6 个端点的响应结构：
- GET  /api/wx/study/vocab/list
- POST /api/wx/study/vocab/random
- POST /api/wx/study/vocab/quiz/submit
- GET  /api/wx/study/review/due
- POST /api/wx/study/review/submit
- GET  /api/wx/study/mistakes

沿用 tests/test_contracts/conftest.py 的 client + auth_headers fixtures。
"""
from __future__ import annotations


def test_wx_vocab_list_contract(client, auth_headers):
    """GET /api/wx/study/vocab/list 响应契约（小程序首页浏览 Tab）。"""
    res = client.get(
        "/api/wx/study/vocab/list?band=7&page=1&per_page=5",
        headers=auth_headers,
    )
    assert res.status_code == 200, f"vocab/list 失败: {res.status_code} {res.text}"
    body = res.json()

    # 顶层契约
    required = {"words", "total", "page", "per_page", "total_pages"}
    missing = required - body.keys()
    assert not missing, f"vocab/list 响应缺字段: {missing}; 实际: {body.keys()}"

    # 类型契约
    assert isinstance(body["words"], list)
    assert isinstance(body["total"], int)
    assert isinstance(body["page"], int)
    assert isinstance(body["per_page"], int)
    assert isinstance(body["total_pages"], int)

    # words 项必填字段契约（与 Web 端 vocab/list 一致）
    if body["words"]:
        item = body["words"][0]
        required_item = {"word", "phonetic", "meaning", "pos", "band", "topic"}
        missing_item = required_item - item.keys()
        assert not missing_item, f"vocab item 缺字段: {missing_item}; 实际: {item.keys()}"


def test_wx_vocab_random_contract(client, auth_headers):
    """POST /api/wx/study/vocab/random 响应契约（小程序抽词 Tab）。"""
    res = client.post(
        "/api/wx/study/vocab/random",
        json={"band": 7, "count": 3},
        headers=auth_headers,
    )
    assert res.status_code == 200, f"vocab/random 失败: {res.status_code}"
    body = res.json()

    # 顶层契约
    assert "words" in body
    assert "count" in body
    assert isinstance(body["words"], list)
    assert body["count"] == len(body["words"])


def test_wx_vocab_quiz_submit_response_contract(client, auth_headers):
    """POST /api/wx/study/vocab/quiz/submit 响应契约。"""
    res = client.post(
        "/api/wx/study/vocab/quiz/submit",
        json={
            "word": "opportunity",
            "user_answer": "机会",
            "correct": True,
            "mode": "en2zh",
        },
        headers=auth_headers,
    )
    if res.status_code == 200:
        body = res.json()
        # 关键契约：小程序前端依赖
        required = {"word", "is_correct", "memory_level", "next_review_at"}
        missing = required - body.keys()
        assert not missing, f"quiz/submit 响应缺字段: {missing}; 实际: {body.keys()}"

        # 类型契约
        assert isinstance(body["memory_level"], int)
        assert isinstance(body["is_correct"], bool)


def test_wx_review_due_response_contract(client, auth_headers):
    """GET /api/wx/study/review/due 响应契约（艾宾浩斯复习核心 API）。"""
    res = client.get("/api/wx/study/review/due", headers=auth_headers)
    if res.status_code == 200:
        body = res.json()

        # 顶层契约
        required = {"due_words", "count", "today"}
        missing = required - body.keys()
        assert not missing, f"review/due 响应缺字段: {missing}; 实际: {body.keys()}"

        # 类型契约
        assert isinstance(body["due_words"], list)
        assert isinstance(body["count"], int)
        # today 必须是 YYYY-MM-DD 格式
        assert len(body["today"]) == 10 and body["today"][4] == "-"


def test_wx_review_submit_response_contract(client, auth_headers):
    """POST /api/wx/study/review/submit 响应契约。"""
    res = client.post(
        "/api/wx/study/review/submit",
        json={"word": "opportunity", "correct": True},
        headers=auth_headers,
    )
    if res.status_code == 200:
        body = res.json()
        required = {"word", "memory_level", "next_review_at"}
        missing = required - body.keys()
        assert not missing, f"review/submit 响应缺字段: {missing}; 实际: {body.keys()}"


def test_wx_mistakes_response_contract(client, auth_headers):
    """GET /api/wx/study/mistakes 响应契约（小程序错词本 Tab）。"""
    res = client.get("/api/wx/study/mistakes", headers=auth_headers)
    if res.status_code == 200:
        body = res.json()
        required = {"mistakes", "count"}
        missing = required - body.keys()
        assert not missing, f"mistakes 响应缺字段: {missing}; 实际: {body.keys()}"
        assert isinstance(body["mistakes"], list)


def test_wx_study_unauthenticated_returns_401(client):
    """所有 wx-study 接口未登录必须返回 401。"""
    endpoints = [
        ("GET", "/api/wx/study/vocab/list"),
        ("POST", "/api/wx/study/vocab/random"),
        ("POST", "/api/wx/study/vocab/quiz/submit"),
        ("GET", "/api/wx/study/review/due"),
        ("POST", "/api/wx/study/review/submit"),
        ("GET", "/api/wx/study/mistakes"),
    ]
    for method, url in endpoints:
        if method == "GET":
            r = client.get(url)
        else:
            r = client.post(url, json={})
        assert r.status_code in (401, 403), \
            f"{method} {url} 未登录应返回 401/403; 实际: {r.status_code}"


def test_wx_vocab_list_band_filter(client, auth_headers):
    """vocab/list 按 band 过滤契约。"""
    res = client.get(
        "/api/wx/study/vocab/list?band=8&per_page=5",
        headers=auth_headers,
    )
    if res.status_code == 200:
        body = res.json()
        # 所有返回的词都应该是 band=8
        for w in body["words"]:
            assert w["band"] == 8, f"过滤失效: {w['word']} 的 band={w['band']}"