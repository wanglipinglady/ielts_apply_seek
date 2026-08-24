"""契约测试共享 fixtures。

复用 tests/test_web/conftest.py 的 client 风格，只暴露"用得到的"。
"""
from __future__ import annotations

import os
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    """FastAPI TestClient；强制 dev 模式 + 内存 SQLite。"""
    os.environ["IELTS_BUDDY_ENV"] = "dev"
    os.environ["IELTS_BUDDY_JWT_SECRET"] = "test-secret-" + "x" * 32
    os.environ["IELTS_BUDDY_WEB_DB_MODE"] = "sqlite"
    os.environ["IELTS_BUDDY_LISTENING_AUTO_SEED"] = "0"
    os.environ["IELTS_BUDDY_READING_AUTO_SEED"] = "0"

    from ielts_buddy.web.main import create_app
    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository

    app = create_app()
    repo = create_sqlite_web_user_repository(":memory:")
    app.state.web_user_repo = repo

    with TestClient(app) as c:
        yield c

    repo.close()


@pytest.fixture
def auth_headers(client: TestClient) -> dict:
    """注册并登录，返回带 Bearer token 的 headers。"""
    r = client.post(
        "/api/auth/register",
        data={"email": "contract@example.com", "password": "password123"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}