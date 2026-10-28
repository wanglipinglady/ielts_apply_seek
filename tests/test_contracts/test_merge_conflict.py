"""
合并冲突消解的回归测试。

这个文件锁定的是 v4.0 生产事故：
线上真机合并报 "合并失败（已自动回滚）"，根因是
``vocab_categories`` 上的 ``UNIQUE(user_id, name)`` ——
目标 PC 账号和微信占位账号**都**持有系统内置分类
``favorites`` / ``mistakes``，直接 UPDATE user_id 必然撞唯一键。

覆盖场景：
1. 两个账号都有内置分类 → 能合并成功（核心回归）
2. 两个账号学了同一个词 → 合并成功，目标账号那份保留
3. 分类下有词条 → 合并后词条挂到目标分类
4. 合并后源账号被删除、openid 转到目标账号
5. 合并后用户数据都在目标账号
"""
from __future__ import annotations

import sqlite3

import pytest

from ielts_buddy.web.auth.repository import (
    SQLiteWebUserRepository,
    WebUserEmailConflictError,
)
from ielts_buddy.web.auth.security import hash_password
from ielts_buddy.web.auth.service import AuthError, WebAuthService


@pytest.fixture
def repo():
    """带完整业务表的 SQLite 仓储（复用业务库真实 schema）。"""
    from ielts_buddy.repositories.sqlite_repo import _SCHEMA

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    # v4 审计表（SQLite 业务 schema 里没有，对齐 MySQL 端结构）
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


@pytest.fixture
def svc(repo):
    return WebAuthService(repo, access_ttl_seconds=3600, refresh_ttl_seconds=604800)


def _make_wx_user(repo, openid="wx_openid_1"):
    """造一个微信占位账号。"""
    from ielts_buddy.web.auth.service import _generate_random_password  # noqa: F401

    user = repo.create(
        f"wx+{openid[:8]}@wechat.ielts-buddy.local",
        hash_password("placeholder-password"),
    )
    repo.bind_wechat_openid(user.id, openid)
    return user


def _seed_categories(conn, user_id, names):
    """给用户塞分类（模拟内置 favorites/mistakes）。"""
    for name in names:
        conn.execute(
            "INSERT INTO vocab_categories "
            "(user_id, name, description, is_system, created_at, updated_at, sync_status) "
            "VALUES (?, ?, '', 1, '', '', 'synced')",
            (user_id, name),
        )
    conn.commit()


def _seed_words(conn, user_id, words, table="personal_vocab"):
    """给用户塞词条。"""
    for w in words:
        if table == "personal_vocab":
            conn.execute(
                "INSERT INTO personal_vocab "
                "(user_id, word, phonetic, meaning, pos, band, topic, example, example_cn, "
                " note, source, created_at, updated_at, sync_status) "
                "VALUES (?, ?, '', '', '', 7, '', '', '', '', 'manual', '', '', 'synced')",
                (user_id, w),
            )
        else:
            conn.execute(
                "INSERT INTO learning_records "
                "(user_id, word, word_data, memory_level, next_review, learn_count, "
                " correct_count, wrong_count, first_learned, last_reviewed, is_starred, "
                " is_difficult, source, updated_at, sync_status) "
                "VALUES (?, ?, '{}', 0, NULL, 0, 0, 0, NULL, NULL, 0, 0, 'builtin', '', 'synced')",
                (user_id, w),
            )
    conn.commit()


def _add_to_category(conn, user_id, category_name, word):
    """把词塞进分类。

    注意两端 ``vocab_category_words`` 结构不同：
    - MySQL：(user_id, category_id, word, added_at)
    - SQLite：(category_id, word_id, added_at) —— 没有 user_id，靠 word_id 关联
    这里按实际列动态适配。
    """
    row = conn.execute(
        "SELECT id FROM vocab_categories WHERE user_id = ? AND name = ?",
        (user_id, category_name),
    ).fetchone()
    if row is None:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(vocab_category_words)").fetchall()}
    try:
        if "user_id" in cols:
            conn.execute(
                "INSERT INTO vocab_category_words (user_id, category_id, word, added_at) "
                "VALUES (?, ?, ?, '')",
                (user_id, row["id"], word),
            )
        else:
            # SQLite：word_id 指向 personal_vocab.id
            pv = conn.execute(
                "SELECT id FROM personal_vocab WHERE user_id = ? AND word = ?",
                (user_id, word),
            ).fetchone()
            if pv is None:
                return
            conn.execute(
                "INSERT INTO vocab_category_words (category_id, word_id, added_at) "
                "VALUES (?, ?, '')",
                (row["id"], pv["id"]),
            )
        conn.commit()
    except sqlite3.IntegrityError:
        pass


# =============================================================
# 核心回归：两边都有内置分类
# =============================================================


def test_merge_with_duplicate_system_categories_succeeds(repo, svc):
    """v4.0 事故回归：两边都有 favorites/mistakes 时合并必须成功。

    修复前：Duplicate entry 'X-favorites' for key 'vocab_categories.uk_vc_user_name'
    → 整单回滚 → 用户看到"合并失败（已自动回滚）"
    """
    conn = repo._conn

    # 目标：PC 老账号
    target = repo.create("pc_user@example.com", hash_password("password123"))
    # 源：微信占位账号
    source = _make_wx_user(repo, "wx_conflict_openid")

    # 两边都有系统内置分类（真实场景就是这样）
    _seed_categories(conn, target.id, ["favorites", "mistakes"])
    _seed_categories(conn, source.id, ["favorites", "mistakes"])

    # 两边都有学习数据
    _seed_words(conn, target.id, ["apple", "banana"])
    _seed_words(conn, source.id, ["cherry", "date"])

    result, merged_id, moved = svc.merge_wechat_to_existing(
        wechat_openid="wx_conflict_openid",
        target_email="pc_user@example.com",
        target_password="password123",
    )

    assert result.user.id == target.id, "合并后应切换到目标账号"
    assert merged_id == source.id

    # 源账号已删除
    assert repo.get_by_id(source.id) is None

    # 分类：目标保留 2 个，源的重名分类被合并掉
    cats = conn.execute(
        "SELECT name FROM vocab_categories WHERE user_id = ? ORDER BY name",
        (target.id,),
    ).fetchall()
    names = [r["name"] for r in cats]
    assert names == ["favorites", "mistakes"], f"分类应去重，实际 {names}"

    # 词条全部到目标账号
    words = conn.execute(
        "SELECT word FROM personal_vocab WHERE user_id = ? ORDER BY word",
        (target.id,),
    ).fetchall()
    got = [r["word"] for r in words]
    assert got == ["apple", "banana", "cherry", "date"], f"词条应全部迁移，实际 {got}"

    # openid 转到目标账号
    assert repo.get_by_id(target.id).wechat_openid == "wx_conflict_openid"


def test_merge_with_same_word_in_both_accounts(repo, svc):
    """两边学了同一个词 → 合并成功，保留目标账号那份（进度不丢）。"""
    conn = repo._conn

    target = repo.create("dup_word@example.com", hash_password("password123"))
    source = _make_wx_user(repo, "wx_dup_word_openid")

    _seed_categories(conn, target.id, ["favorites"])
    _seed_categories(conn, source.id, ["favorites"])

    # 同一个词两边都有
    _seed_words(conn, target.id, ["shared", "only_target"])
    _seed_words(conn, source.id, ["shared", "only_source"])

    result, merged_id, _ = svc.merge_wechat_to_existing(
        wechat_openid="wx_dup_word_openid",
        target_email="dup_word@example.com",
        target_password="password123",
    )
    assert result.user.id == target.id

    words = conn.execute(
        "SELECT word FROM personal_vocab WHERE user_id = ? ORDER BY word",
        (target.id,),
    ).fetchall()
    got = [r["word"] for r in words]
    # shared 只能有一份，且两个独有词都在
    assert got == ["only_source", "only_target", "shared"], f"词条应去重合并，实际 {got}"


def test_merge_keeps_learning_records(repo, svc):
    """learning_records 同样要能合并（艾宾浩斯复习进度不能丢）。"""
    conn = repo._conn

    target = repo.create("lr_user@example.com", hash_password("password123"))
    source = _make_wx_user(repo, "wx_lr_openid")

    _seed_categories(conn, target.id, ["favorites"])
    _seed_categories(conn, source.id, ["favorites"])

    _seed_words(conn, target.id, ["alpha"], table="learning_records")
    _seed_words(conn, source.id, ["beta"], table="learning_records")

    svc.merge_wechat_to_existing(
        wechat_openid="wx_lr_openid",
        target_email="lr_user@example.com",
        target_password="password123",
    )

    rows = conn.execute(
        "SELECT word FROM learning_records WHERE user_id = ? ORDER BY word",
        (target.id,),
    ).fetchall()
    assert [r["word"] for r in rows] == ["alpha", "beta"]


def test_merge_moves_category_words_to_target_category(repo, svc):
    """源账号分类下的词条，合并后要挂到目标账号的同名分类上。"""
    conn = repo._conn

    target = repo.create("catword@example.com", hash_password("password123"))
    source = _make_wx_user(repo, "wx_catword_openid")

    _seed_categories(conn, target.id, ["favorites", "mistakes"])
    _seed_categories(conn, source.id, ["favorites", "mistakes"])

    _seed_words(conn, source.id, ["word_in_cat"])
    _add_to_category(conn, source.id, "favorites", "word_in_cat")

    svc.merge_wechat_to_existing(
        wechat_openid="wx_catword_openid",
        target_email="catword@example.com",
        target_password="password123",
    )

    # 关联行不应丢失，且要挂在目标账号的 favorites 分类上
    cols = {r[1] for r in conn.execute("PRAGMA table_info(vocab_category_words)").fetchall()}
    cat = conn.execute(
        "SELECT id FROM vocab_categories WHERE user_id = ? AND name = 'favorites'",
        (target.id,),
    ).fetchone()
    assert cat is not None, "目标账号的 favorites 分类应在"

    if "user_id" in cols:
        link = conn.execute(
            "SELECT user_id, category_id FROM vocab_category_words WHERE word = ?",
            ("word_in_cat",),
        ).fetchone()
        assert link is not None, "分类-词条关联不应丢失"
        assert link["user_id"] == target.id
        assert link["category_id"] == cat["id"]
    else:
        # SQLite 结构：靠 category_id 关联，分类被合并到目标分类
        pv = conn.execute(
            "SELECT id FROM personal_vocab WHERE user_id = ? AND word = ?",
            (target.id, "word_in_cat"),
        ).fetchone()
        assert pv is not None, "词条应迁移到目标账号"
        link = conn.execute(
            "SELECT category_id FROM vocab_category_words WHERE word_id = ?",
            (pv["id"],),
        ).fetchone()
        assert link is not None, "分类-词条关联不应丢失"
        assert link["category_id"] == cat["id"], "关联应挂到目标分类上"


def test_merge_source_only_category_is_moved(repo, svc):
    """源账号独有的分类要整体带到目标账号。"""
    conn = repo._conn

    target = repo.create("onlycat@example.com", hash_password("password123"))
    source = _make_wx_user(repo, "wx_onlycat_openid")

    _seed_categories(conn, target.id, ["favorites"])
    _seed_categories(conn, source.id, ["favorites", "my_custom"])

    svc.merge_wechat_to_existing(
        wechat_openid="wx_onlycat_openid",
        target_email="onlycat@example.com",
        target_password="password123",
    )

    names = [
        r["name"] for r in conn.execute(
            "SELECT name FROM vocab_categories WHERE user_id = ? ORDER BY name",
            (target.id,),
        ).fetchall()
    ]
    assert names == ["favorites", "my_custom"], f"源独有分类应迁移，实际 {names}"


def test_merge_audit_log_written(repo, svc):
    """合并要写审计日志。"""
    target = repo.create("audit@example.com", hash_password("password123"))
    source = _make_wx_user(repo, "wx_audit_openid")

    svc.merge_wechat_to_existing(
        wechat_openid="wx_audit_openid",
        target_email="audit@example.com",
        target_password="password123",
    )

    rows = repo._conn.execute(
        "SELECT from_user_id, to_user_id, merge_type FROM user_merge_log"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["from_user_id"] == source.id
    assert rows[0]["to_user_id"] == target.id
    assert rows[0]["merge_type"] == "wechat_to_email"


def test_merge_wrong_password_still_rejected(repo, svc):
    """密码错仍然要报错（冲突消解不能绕过鉴权）。"""
    target = repo.create("authcheck@example.com", hash_password("password123"))
    _make_wx_user(repo, "wx_authcheck_openid")

    with pytest.raises(AuthError) as exc:
        svc.merge_wechat_to_existing(
            wechat_openid="wx_authcheck_openid",
            target_email="authcheck@example.com",
            target_password="wrong-password",
        )
    assert exc.value.code == "INVALID_CREDENTIALS"
