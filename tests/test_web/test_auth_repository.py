"""SQLiteWebUserRepository 单测 + 内存库创建器。"""
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


def test_close_is_noop(repo: SQLiteWebUserRepository) -> None:
    """SQLiteWebUserRepository.close() 是 no-op（连接由调用方管理）。"""
    repo.close()  # 不应抛
    # 再 close 也不应抛
    repo.close()
