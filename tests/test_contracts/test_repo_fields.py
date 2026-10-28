"""
仓储层"多实现字段一致性"回归测试。

背景（v4.0 线上事故）：
``MySQLWebUserRepository.get_by_openid()`` 漏了 ``wechat_openid`` 字段，
而 SQLite 实现用 ``SELECT *`` 天然带全字段 →
service 层拿到的 ``placeholder.wechat_openid`` 恒为 None
→ 合并时 openid 不转移 → 源账号被删 → **openid 彻底丢失**
→ 用户下次微信登录创建一个全新空账号（数据看不到）。

这与《技术复盘》"坑 8：多实现漏方法"是同一类问题 ——
多份实现之间**字段**也要对齐，不能只对齐方法名。

本测试锁定：SQLite / MySQL 两个实现的 get_by_* 返回的 WebUser
必须携带同一组字段。
"""
from __future__ import annotations

import sqlite3

import pytest

from ielts_buddy.web.auth.repository import (
    SQLiteWebUserRepository,
    WebUser,
)


def _sqlite_repo():
    from ielts_buddy.repositories.sqlite_repo import _SCHEMA

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_merge_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            merged_at TEXT NOT NULL DEFAULT (datetime('now')),
            merge_type TEXT NOT NULL DEFAULT 'wechat_to_email',
            from_data_backup TEXT,
            from_user_vocab_count INTEGER,
            to_user_vocab_count INTEGER
        );
        """
    )
    return SQLiteWebUserRepository(conn)


def test_get_by_openid_returns_wechat_openid():
    """get_by_openid 必须能带回 wechat_openid（合并链路依赖它）。"""
    repo = _sqlite_repo()
    user = repo.create("openid_field@example.com", "hash")
    repo.bind_wechat_openid(user.id, "wx_openid_xyz")

    fetched = repo.get_by_openid("wx_openid_xyz")
    assert fetched is not None, "按 openid 应能查到用户"
    assert fetched.wechat_openid == "wx_openid_xyz", (
        "get_by_openid 必须返回 wechat_openid —— "
        "合并时靠它把 openid 转移到目标账号，漏了会导致 openid 丢失"
    )
    assert fetched.id == user.id


def test_get_by_openid_returns_v4_fields():
    """get_by_openid 也要带上 v4 的两个字段。"""
    repo = _sqlite_repo()
    user = repo.create("openid_v4@example.com", "hash")
    repo.bind_wechat_openid(user.id, "wx_openid_v4")

    fetched = repo.get_by_openid("wx_openid_v4")
    assert fetched is not None
    assert hasattr(fetched, "pc_logged_in_at")
    assert hasattr(fetched, "email_verified")
    assert fetched.email_verified is False


def test_get_by_openid_not_found_returns_none():
    """查不到时返回 None（不抛异常）。"""
    repo = _sqlite_repo()
    assert repo.get_by_openid("not_exist_openid") is None
    assert repo.get_by_openid("") is None


def test_webuser_dataclass_has_all_fields():
    """WebUser 领域对象必须定义全部 v4 字段。"""
    import dataclasses

    names = {f.name for f in dataclasses.fields(WebUser)}
    required = {
        "id", "email", "password_hash",
        "wechat_openid", "pc_logged_in_at", "email_verified",
    }
    assert required <= names, f"WebUser 缺字段: {required - names}"


def test_mysql_get_by_openid_returns_wechat_openid():
    """MySQL 实现的 get_by_openid 必须返回 wechat_openid（防回归）。

    这里不连真库，直接用源码静态检查 ——
    断言 MySQLWebUserRepository.get_by_openid 的源码里出现了
    ``wechat_openid=m.get(...)``，防止以后又被"精简"掉。
    """
    import inspect

    from ielts_buddy.web.auth.repository import MySQLWebUserRepository

    src = inspect.getsource(MySQLWebUserRepository.get_by_openid)
    assert "wechat_openid=" in src, (
        "MySQLWebUserRepository.get_by_openid 必须返回 wechat_openid；"
        "漏掉会导致合并时 openid 丢失（v4.0 线上事故）"
    )
    assert "email_verified=" in src, (
        "MySQLWebUserRepository.get_by_openid 必须返回 email_verified"
    )


def test_merge_preserves_openid_end_to_end():
    """端到端：合并后 openid 必须在目标账号上，不能丢。"""
    from ielts_buddy.web.auth.security import hash_password
    from ielts_buddy.web.auth.service import WebAuthService

    repo = _sqlite_repo()
    svc = WebAuthService(repo, access_ttl_seconds=3600, refresh_ttl_seconds=604800)

    target = repo.create("preserve_openid@example.com", hash_password("password123"))
    source = repo.create(
        "wx+preserve@wechat.ielts-buddy.local", hash_password("placeholder")
    )
    repo.bind_wechat_openid(source.id, "wx_preserve_openid")

    svc.merge_wechat_to_existing(
        wechat_openid="wx_preserve_openid",
        target_email="preserve_openid@example.com",
        target_password="password123",
    )

    # 源账号已删除
    assert repo.get_by_id(source.id) is None
    # openid 必须活下来，且在目标账号上
    assert repo.get_by_id(target.id).wechat_openid == "wx_preserve_openid", (
        "合并后 openid 必须转移到目标账号"
    )
    # 按 openid 能查到目标账号
    assert repo.get_by_openid("wx_preserve_openid").id == target.id
