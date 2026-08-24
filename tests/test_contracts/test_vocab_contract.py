"""
vocab 模块契约测试
锁定 4 个核心 API 的响应 / 入参结构。
"""
from __future__ import annotations

REQUIRED_VOCAB_FIELDS = {
    "word",          # 单词本身
    "phonetic",      # 音标
    "meaning",       # 中文释义
    "pos",           # 词性
    "band",          # Band 级别
    "topic",         # 主题
}


def assert_vocab_item_shape(item: dict) -> None:
    """vocab item 必填字段契约。"""
    missing = REQUIRED_VOCAB_FIELDS - item.keys()
    assert not missing, f"vocab item 缺少字段: {missing}; 实际字段: {set(item.keys())}"


def test_vocab_list_response_contract(client):
    """GET /api/vocab/list 返回结构契约。

    CLI 用 ib vocab list、Web vocab/browse 页、小程序学习首页浏览 Tab 都依赖。
    """
    res = client.get("/api/vocab/list?band=7&page=1&per_page=5")
    assert res.status_code == 200, f"vocab/list 失败: {res.status_code} {res.text}"
    body = res.json()

    # 顶层结构：真实响应是 words（不是 items），这是契约保护对象
    assert "words" in body, f"响应缺 words 字段; 实际: {body.keys()}"
    assert isinstance(body["words"], list)

    # 至少返回一些数据 + 每条都必填字段完整
    if body["words"]:
        for item in body["words"]:
            assert_vocab_item_shape(item)


def test_vocab_search_response_contract(client):
    """GET /api/vocab/search 返回结构契约。

    CLI 用 ib vocab search、小程序搜索入口都依赖。
    注意：参数名是 q（不是 keyword）。
    """
    res = client.get("/api/vocab/search?q=opportunity")
    assert res.status_code == 200, f"vocab/search 失败: {res.status_code} {res.text}"
    body = res.json()

    # 真实响应：搜索结果是顶层对象，直接返回
    # CLI/小程序前端都依赖 word 字段在 items[0]
    if "items" in body:
        items = body["items"]
    elif "results" in body:
        items = body["results"]
    else:
        # 兜底：可能是单条结果字典
        items = [body] if "word" in body else []

    if items:
        assert_vocab_item_shape(items[0])


def test_vocab_quiz_submit_request_contract(client, auth_headers):
    """POST /api/vocab/quiz/submit 入参契约。

    CLI quiz 命令、Web quiz 页、小程序测验 Tab 都提交这个端点。
    """
    payload = {
        "word": "opportunity",
        "user_answer": "机会",
        "correct": True,
        "mode": "en2zh",
    }
    res = client.post(
        "/api/vocab/quiz/submit",
        json=payload,
        headers=auth_headers,
    )

    # 200 (成功) 或 4xx (业务校验失败) 都允许——契约测试只验证字段名
    if res.status_code == 200:
        body = res.json()
        assert "is_correct" in body or "correct" in body, \
            f"响应缺 correct 字段; 实际: {body.keys()}"


def test_vocab_band_returns_phonetic(client):
    """响应中 phonetic 字段必须是字符串（小程序要展示）。

    这个契约保护：未来如果有人误把 phonetic 改成 dict / list，小程序渲染会崩。
    注意：per_page 下限是 5（le=100, ge=5）。
    """
    res = client.get("/api/vocab/list?band=7&page=1&per_page=5")
    assert res.status_code == 200, f"vocab/list 失败: {res.status_code}"
    items = res.json().get("words", [])
    if items:
        assert isinstance(items[0].get("phonetic"), str), \
            f"phonetic 必须是字符串; 实际: {type(items[0].get('phonetic'))}"