"""阶段 0 骨架冒烟测试。"""

from __future__ import annotations


def test_app_starts(client) -> None:
    """app 工厂可构造，TestClient 可打开。"""
    assert client is not None


def test_index_page_returns_200(client) -> None:
    """GET / 返回 200，HTML 含 'IELTS'。"""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "IELTS" in r.text


def test_index_shows_phase_label(client) -> None:
    """首页展示阶段标签（当前阶段由 main.py 模板上下文决定）。"""
    r = client.get("/")
    # 阶段 2 起展示 "Phase 2"
    assert "Phase 2" in r.text or "Phase&nbsp;2" in r.text


def test_healthz(client) -> None:
    """健康检查返回 status=ok 与版本号。"""
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["app"] == "ielts-buddy-web"
    assert "version" in body


def test_static_css_served(client) -> None:
    """GET /static/css/app.css 返回 200 + text/css。"""
    r = client.get("/static/css/app.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    # 至少包含 root 变量定义
    assert "--bg" in r.text


def test_htmx_loaded(client) -> None:
    """GET /static/js/htmx.min.js 返回 200 + JavaScript 标识。

    Starlette StaticFiles 对 .js 返回 ``text/javascript; charset=utf-8``。
    我们只断言 mime 是 JavaScript 系（含 ``text/javascript`` 或 ``application/javascript``）。
    """
    r = client.get("/static/js/htmx.min.js")
    assert r.status_code == 200
    ctype = r.headers["content-type"]
    assert (
        ctype.startswith("text/javascript")
        or ctype.startswith("application/javascript")
    ), f"unexpected content-type: {ctype}"
    assert "htmx" in r.text.lower()


def test_htmx_loaded_in_base_html(client) -> None:
    """base.html 包含 HTMX 引入（首页检查）。"""
    r = client.get("/")
    assert r.status_code == 200
    assert '/static/js/htmx.min.js' in r.text
    assert '/static/css/app.css' in r.text


def test_404_for_unknown_route(client) -> None:
    """未注册路径返回 404。"""
    r = client.get("/this-route-does-not-exist")
    assert r.status_code == 404
