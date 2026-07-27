"""Web 测试共享 fixtures。"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    """FastAPI TestClient；强制 dev 模式 + 内存 SQLite。

    关键点：每个测试 session 构造独立 ``app``，避免 module-level 单例
    跨测试状态污染。
    """
    # 必须在导入 web 模块前设置环境变量
    os.environ["IELTS_BUDDY_ENV"] = "dev"
    os.environ["IELTS_BUDDY_JWT_SECRET"] = "test-secret-" + "x" * 32
    os.environ["IELTS_BUDDY_WEB_DB_MODE"] = "sqlite"

    from ielts_buddy.web.main import create_app
    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository

    app = create_app()
    # 用独立内存库替换 lifespan 默认开的临时文件
    repo = create_sqlite_web_user_repository(":memory:")
    app.state.web_user_repo = repo

    with TestClient(app) as c:
        yield c

    repo.close()


@pytest.fixture
def web_db_path(tmp_path) -> str:
    """给 stats / study 业务表用的真实 SQLite 文件路径（与 web_data.db 共享）。"""
    return str(tmp_path / "web_data.db")


@pytest.fixture
def client_with_db(web_db_path) -> Iterator[TestClient]:
    """带 web_data.db 路径注入的 TestClient。

    必须在导入 web 模块前设置环境变量，否则 config.py 已经缓存了路径。
    """
    # 必须在导入前设置
    os.environ["IELTS_BUDDY_ENV"] = "dev"
    os.environ["IELTS_BUDDY_JWT_SECRET"] = "test-secret-" + "x" * 32
    os.environ["IELTS_BUDDY_WEB_DB_MODE"] = "sqlite"
    os.environ["IELTS_BUDDY_WEB_SQLITE_PATH"] = web_db_path

    # 强制重新加载 config 模块（清除缓存）
    import importlib
    from ielts_buddy.web import config as web_config
    importlib.reload(web_config)

    from ielts_buddy.web.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def registered_user(client: TestClient) -> dict:
    """注册一个用户，返回 {"email", "password", "user_id", "access_token"}。

    供多场景复用：dashboard、me、token 过期等。
    """
    email = "alice@example.com"
    password = "password123"
    r = client.post(
        "/api/auth/register",
        data={"email": email, "password": password},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "email": email,
        "password": password,
        "user_id": body["user"]["id"],
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
    }
