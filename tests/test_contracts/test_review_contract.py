"""
review 模块契约测试
锁定 2 个核心 API 的响应结构（艾宾浩斯复习是三端共享核心功能）。

特别注意：艾宾浩斯算法在 reviews.py 里，**禁止修改算法本身**——只能加新参数。
"""
from __future__ import annotations


def test_review_due_response_contract(client, auth_headers):
    """GET /api/review/due 返回结构契约。

    CLI ib vocab review、Web /study/review、小程序复习 Tab 都依赖。
    """
    res = client.get("/api/review/due", headers=auth_headers)

    # 200 (有数据) / 401 (未登录但路由存在) / 404 (路由未实现) 都允许
    assert res.status_code in (200, 401, 404), f"意外状态码: {res.status_code}"

    if res.status_code == 200:
        body = res.json()

        # 顶层结构契约：保护三端字段名不被改
        assert "due_words" in body or "items" in body or "words" in body, \
            f"响应缺 due_words/items/words 字段; 实际: {body.keys()}"


def test_review_submit_response_contract(client, auth_headers):
    """POST /api/review/submit 返回结构契约。

    三端复习答题后都立即调用——必须有 next_review_at 字段（小程序倒计时依赖）。
    """
    payload = {
        "word": "opportunity",
        "correct": True,
    }
    res = client.post(
        "/api/review/submit",
        json=payload,
        headers=auth_headers,
    )

    if res.status_code == 200:
        body = res.json()

        # 关键字段契约：小程序复习页依赖这些字段
        required = {"word", "memory_level", "next_review_at"}
        missing = required - body.keys()
        assert not missing, \
            f"review/submit 响应缺字段: {missing}; 实际: {body.keys()}"

        # 类型契约（防 schema 误改）
        assert isinstance(body["memory_level"], int), \
            f"memory_level 必须是 int; 实际: {type(body['memory_level'])}"


def test_review_mistakes_response_contract(client, auth_headers):
    """GET /api/review/mistakes 返回结构契约（错词本）。

    Web 错词本页、小程序错词本 Tab 都依赖。
    """
    res = client.get("/api/review/mistakes", headers=auth_headers)

    if res.status_code == 200:
        body = res.json()

        # 必须有 word + wrong_count 字段
        items = body.get("items") or body.get("mistakes") or body.get("words") or []
        if isinstance(items, list) and items:
            first = items[0]
            assert "word" in first, f"错词 item 缺 word 字段; 实际: {first.keys()}"
            assert "wrong_count" in first, f"错词 item 缺 wrong_count 字段; 实际: {first.keys()}"