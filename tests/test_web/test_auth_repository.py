"""SQLiteWebUserRepository 单测（v3+：读写都走 users 表）。

v3 改造后，SQLiteWebUserRepository 的所有方法都走统一的 ``users`` 表，
与 CLI 的 ``UserRepository`` 共享命名空间。对外 API（``create`` /
``get_by_email`` / ``get_by_id`` / ``update_last_login`` / ``set_password``）
保持不变。
"""
from __future__ import annotations

import pytest

from ielts_buddy.web.auth.repository import (
    SQLiteWebUserRepository,
    WebUserEmailConflictError,
    create_sqlite_web_user_repository,
)


@pytest.fixture
def repo() -> SQLiteWebUserRepository:
    r = create_sqlite_web_user_repository(":memory:")
    yield r
    r.close()


def test_create_returns_user_with_id(repo: SQLiteWebUserRepository) -> None:
    u = repo.create("alice@example.com", "hashed_pw")
    assert u.id >= 1
    assert u.email == "alice@example.com"
    assert u.password_hash == "hashed_pw"
    assert u.created_at is not None
    assert u.last_login_at is None


def test_create_normalizes_email_lowercase(repo: SQLiteWebUserRepository) -> None:
    u1 = repo.create("Alice@Example.COM", "h1")
    assert u1.email == "alice@example.com"
    # 重复（大小写不同）应冲突
    with pytest.raises(WebUserEmailConflictError):
        repo.create("ALICE@example.com", "h2")


def test_create_conflict_raises(repo: SQLiteWebUserRepository) -> None:
    repo.create("bob@example.com", "h1")
    with pytest.raises(WebUserEmailConflictError) as exc:
        repo.create("bob@example.com", "h2")
    assert "bob@example.com" in str(exc.value)


def test_get_by_email_case_insensitive(repo: SQLiteWebUserRepository) -> None:
    repo.create("Carol@Example.com", "h")
    found = repo.get_by_email("carol@example.COM")
    assert found is not None
    assert found.email == "carol@example.com"


def test_get_by_email_not_found(repo: SQLiteWebUserRepository) -> None:
    assert repo.get_by_email("nobody@example.com") is None


def test_get_by_id(repo: SQLiteWebUserRepository) -> None:
    u = repo.create("dave@example.com", "h")
    found = repo.get_by_id(u.id)
    assert found is not None
    assert found.email == "dave@example.com"


def test_get_by_id_not_found(repo: SQLiteWebUserRepository) -> None:
    assert repo.get_by_id(99999) is None


def test_update_last_login(repo: SQLiteWebUserRepository) -> None:
    u = repo.create("eve@example.com", "h")
    assert u.last_login_at is None
    repo.update_last_login(u.id)
    after = repo.get_by_id(u.id)
    assert after is not None
    assert after.last_login_at is not None
    assert "T" in after.last_login_at  # ISO datetime


def test_set_password(repo: SQLiteWebUserRepository) -> None:
    u = repo.create("frank@example.com", "old_hash")
    ok = repo.set_password(u.id, "new_hash")
    assert ok is True
    after = repo.get_by_id(u.id)
    assert after is not None
    assert after.password_hash == "new_hash"


def test_set_password_returns_false_for_missing(repo: SQLiteWebUserRepository) -> None:
    ok = repo.set_password(99999, "x")
    assert ok is False


def test_close_is_noop(repo: SQLiteWebUserRepository) -> None:
    """SQLiteWebUserRepository.close() 是 no-op（连接由调用方管理）。"""
    repo.close()  # 不应抛
    # 再 close 也不应抛
    repo.close()


def test_write_to_users_table_not_web_users(repo: SQLiteWebUserRepository) -> None:
    """v3+：注册后能在 users 表看到行，web_users 不应被使用。"""
    repo.create("grace@example.com", "h")
    rows = repo._conn.execute(
        "SELECT email FROM users WHERE email = ?", ("grace@example.com",)
    ).fetchall()
    assert len(rows) == 1
    # 验证 web_users 表在 :memory: 库里压根不存在
    exists = repo._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='web_users'"
    ).fetchone()
    assert exists is None, "v3+ 不应再创建 web_users 表"
