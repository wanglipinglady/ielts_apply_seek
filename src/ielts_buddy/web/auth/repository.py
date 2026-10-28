"""Web 端用户仓储层（v3+：统一走 users 表，与 CLI 共享）。

历史：早期 web_users 独立表，v3 合并到 users 表。本文件保留 WebUser /
WebUserRepository Protocol / SQLite & MySQL 双实现，但所有读写都改走 users
表，不再依赖 web_users。
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


@dataclass
class WebUser:
    """Web 端用户领域对象。

    字段说明：
    - ``wechat_openid``：2026-08-24 为微信小程序登录新增（v3.9+）
    - ``pc_logged_in_at``：v4.0+（2026-10-16）为 PC 端首次登录标记，用于
      锁定后禁止改邮箱的业务规则
    - ``email_verified``：v4.0+ 邮箱是否已验证（合并时设为 True）
    """

    id: int
    email: str
    password_hash: str
    created_at: str | None = None
    last_login_at: str | None = None
    wechat_openid: str | None = None
    pc_logged_in_at: str | None = None
    email_verified: bool = False


# =============================================================
# 异常
# =============================================================


class WebUserNotFoundError(Exception):
    """按 email 查不到用户。"""


class WebUserEmailConflictError(Exception):
    """email 已被注册。"""


def _sqlite_has_user_id(conn: sqlite3.Connection, table: str) -> bool:
    """判断 SQLite 表是否有 user_id 列。

    v4.0：SQLite 端的 ``vocab_category_words`` 结构是
    ``(category_id, word_id, added_at)`` —— **没有 user_id**，
    与 MySQL 端 ``(user_id, category_id, word)`` 完全不同。
    这类表无法按 user_id 迁移，合并时必须跳过（否则 SQL 直接报错）。
    """
    try:
        rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    except sqlite3.OperationalError:
        return False
    return any(str(r[1]) == "user_id" for r in rows)


def _is_missing_table(exc: Exception) -> bool:
    """判断 SQLAlchemy 异常是否是"表不存在"。

    MySQL 错误码 1146 (ER_NO_SUCH_TABLE)；SQLite 是 "no such table"。
    """
    msg = str(exc).lower()
    if "1146" in msg or "no such table" in msg:
        return True
    orig = getattr(exc, "orig", None)
    if orig is not None and str(orig).lower().find("1146") >= 0:
        return True
    return False


# =============================================================
# Protocol
# =============================================================


@runtime_checkable
class WebUserRepository(Protocol):
    """Web 端用户仓储接口（v3+：统一走 users 表）。

    两端（SQLite / MySQL）实现需保证：
    - 邮箱大小写不敏感（统一存小写）
    - ``get_by_id`` 不存在时返回 None
    - ``create`` 邮箱重复时抛 ``WebUserEmailConflictError``
    """

    def create(self, email: str, password_hash: str) -> WebUser:
        """创建用户；email 重复抛 WebUserEmailConflictError。"""
        ...

    def get_by_email(self, email: str) -> Optional[WebUser]:
        """按 email 查；找不到返回 None。"""
        ...

    def get_by_id(self, user_id: int) -> Optional[WebUser]:
        """按 id 查；找不到返回 None。"""
        ...

    def update_last_login(self, user_id: int, when: datetime | None = None) -> None:
        """更新 last_login_at。when=None 时用当前时间。"""
        ...

    def update_pc_logged_in_at(self, user_id: int, when: datetime | None = None) -> None:
        """v4.0+：更新 pc_logged_in_at。用于标记 PC 端首次登录。

        业务语义：一旦标记，该账号的邮箱会被业务规则锁定（不可修改），
        仅允许通过"忘记密码"流程重置密码。when=None 时用当前时间。
        """
        ...

    def set_password(self, user_id: int, new_password_hash: str) -> bool:
        """重置指定用户的密码 hash。成功返回 True；用户不存在返回 False。

        注意：调用方应传入 ``hash_password(plain)`` 的结果，不要把明文
        传过来。service 层负责校验明文 + 加盐哈希。
        """
        ...

    def get_by_openid(self, openid: str) -> Optional[WebUser]:
        """按微信 openid 查（小程序登录专用，2026-08-24 新增）。

        找不到返回 None；openid 通常 28 字符以内。
        """
        ...

    def bind_wechat_openid(self, user_id: int, openid: str) -> bool:
        """绑定用户的微信 openid（已存在用户绑定微信身份，2026-08-24 新增）。

        成功返回 True；用户不存在返回 False。
        """
        ...

    def set_email_and_password(
        self, user_id: int, email: str, password_hash: str,
    ) -> bool:
        """把账号的邮箱 + 密码改成指定值（小程序"开通 PC 端账号"用）。

        - 邮箱已被别人占用 → 抛 ``WebUserEmailConflictError``
        - ``username`` 跟随邮箱前缀派生；重名时自动加数字后缀
        - 用户不存在 → 返回 False
        """
        ...

    def merge_user_data(
        self,
        from_user_id: int,
        to_user_id: int,
        wechat_openid: str | None = None,
    ) -> dict[str, int]:
        """把 ``from_user_id`` 的全部业务数据迁移到 ``to_user_id``。

        事务语义：任一步失败整体回滚（调用方拿不到半成品状态）。

        副作用：
        - 所有含 ``user_id`` 的业务表 ``UPDATE ... SET user_id = to_user_id``
        - ``users.wechat_openid`` 转移到 ``to_user_id``
        - ``users.email_verified`` 置 1
        - 删除 ``from_user_id`` 这个账号行
        - 写 ``user_merge_log`` 审计日志

        返回：``{表名: 迁移行数}``。
        """
        ...

    def close(self) -> None:
        """关闭底层连接 / 释放资源。"""
        ...


# =============================================================
# SQLite 实现（测试 + 本地开发）
# =============================================================


# v4.0+：账号合并时需要迁移 user_id 的业务表清单。
# 必须与 MySQL 端实际存在的表保持一致（两��� schema 对齐）。
# 注意：这里**不能**出现 vocab / mistakes / study_plans —— 那是 v4 初版的错误清单，
# 实际库表是 personal_vocab / learning_records / mistakes→vocab_categories。
_MERGE_BUSINESS_TABLES = [
    "learning_records",
    "personal_vocab",
    "vocab_categories",
    "vocab_category_words",
    "exam_sessions",
    "grade_history",
    "typing_history",
    "focus_sessions",
    "articles",
    "speaking_practice_records",
    "listening_attempts",
    "reading_attempts",
]


# v3+：users 表由业务库 sqlite_repo._SCHEMA 统一创建，本仓储不再建任何表。
# 下面这个常量保留是为了不让旧测试导入报错，但实际不再使用。
_LEGACY_SCHEMA_NOOP = ""


def _row_to_user(row: sqlite3.Row) -> Optional[WebUser]:
    """sqlite3.Row → WebUser 转换（v3.9+ 含 wechat_openid, v4.0+ 含 pc_logged_in_at/email_verified）。"""
    if row is None:
        return None
    # sqlite3.Row 支持 keys() 检查字段是否存在（v3.9/v4.0 升级时老库可能没新列）
    cols = row.keys() if hasattr(row, "keys") else []
    openid = row["wechat_openid"] if "wechat_openid" in cols else None
    pc_logged_in_at = row["pc_logged_in_at"] if "pc_logged_in_at" in cols else None
    email_verified = bool(row["email_verified"]) if "email_verified" in cols else False
    return WebUser(
        id=row["id"],
        email=row["email"] or "",
        password_hash=row["password_hash"] or "",
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
        wechat_openid=openid,
        pc_logged_in_at=pc_logged_in_at,
        email_verified=email_verified,
    )


class SQLiteWebUserRepository:
    """SQLite 实现的 web 端用户仓储（v3+：读写都走 users 表）。

    users 表 schema 由业务库 ``sqlite_repo._SCHEMA`` 创建（已有 id /
    username / email / password_hash / display_name / created_at /
    last_login_at 等列）。

    email 唯一约束使用 COLLATE NOCASE，实现大小写不敏感。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        # v3+：users 表已在业务库 _SCHEMA 里建好；本仓储不做任何 DDL。
        # 若调用方传入 :memory: 全新库，需要先确保 users 表已建。
        self._ensure_users_schema()

    def _ensure_users_schema(self) -> None:
        """对 :memory: 等全新库，确保 users 表存在。生产 db 文件不需要这一步。

        v3.9（2026-08-24）：新增 ``wechat_openid`` 列，供小程序登录用。
        用 ALTER TABLE + 失败回退实现"幂等"——生产 db 已有表也能跑。
        """
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        if cur.fetchone() is None:
            # 没建就兜底建一个（仅 :memory: / 测试 fixture 场景）
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    username        TEXT NOT NULL COLLATE NOCASE,
                    email           TEXT COLLATE NOCASE,
                    password_hash   TEXT,
                    display_name    TEXT,
                    created_at      TEXT NOT NULL,
                    last_login_at   TEXT,
                    wechat_openid   TEXT COLLATE NOCASE,
                    pc_logged_in_at TEXT,
                    email_verified  INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (username COLLATE NOCASE),
                    UNIQUE (email COLLATE NOCASE),
                    UNIQUE (wechat_openid COLLATE NOCASE)
                );
                """
            )
            self._conn.commit()
            return

        # 生产 db 已存在 users 表 → 幂等补列（v3.9 / v4.0 升级用）
        cur = self._conn.execute("PRAGMA table_info(users)")
        cols = {row[1] for row in cur.fetchall()}
        if "wechat_openid" not in cols:
            try:
                self._conn.execute(
                    "ALTER TABLE users ADD COLUMN wechat_openid TEXT COLLATE NOCASE"
                )
                # 加唯一索引（UNIQUE 约束需单独建索引）
                self._conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_wechat_openid "
                    "ON users(wechat_openid COLLATE NOCASE) "
                    "WHERE wechat_openid IS NOT NULL"
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                # 已存在等无害错误，静默跳过
                pass

        # v4.0+：pc_logged_in_at / email_verified
        # 之前只有 update_pc_logged_in_at() 会临时补 pc_logged_in_at，
        # 但 email_verified 没有任何补列路径 → 合并时 "no such column" 直接炸。
        # 这里统一幂等补齐。
        cur = self._conn.execute("PRAGMA table_info(users)")
        cols = {row[1] for row in cur.fetchall()}
        for col, ddl in (
            ("pc_logged_in_at", "ALTER TABLE users ADD COLUMN pc_logged_in_at TEXT"),
            ("email_verified", "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in cols:
                try:
                    self._conn.execute(ddl)
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass

    def create(self, email: str, password_hash: str) -> WebUser:
        email_norm = email.strip().lower()
        now = datetime.now().isoformat(timespec="seconds")
        # 从 email 派生 username：取 @ 前缀；冲突时加数字后缀
        base_username = email_norm.split("@", 1)[0] or "user"
        username = base_username
        suffix = 1
        try:
            while True:
                row = self._conn.execute(
                    "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                    (username,),
                ).fetchone()
                if row is None:
                    break
                suffix += 1
                username = f"{base_username}{suffix}"
            cur = self._conn.execute(
                """INSERT INTO users (username, email, password_hash, display_name, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (username, email_norm, password_hash, email_norm, now),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise WebUserEmailConflictError(
                f"邮箱 '{email_norm}' 已被注册"
            ) from e
        new_id = cur.lastrowid or 0
        return WebUser(
            id=new_id,
            email=email_norm,
            password_hash=password_hash,
            created_at=now,
            last_login_at=None,
        )

    def get_by_email(self, email: str) -> Optional[WebUser]:
        email_norm = email.strip().lower()
        row = self._conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
            (email_norm,),
        ).fetchone()
        return _row_to_user(row) if row else None

    def get_by_id(self, user_id: int) -> Optional[WebUser]:
        row = self._conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,),
        ).fetchone()
        return _row_to_user(row) if row else None

    def update_last_login(self, user_id: int, when: datetime | None = None) -> None:
        ts = (when or datetime.now()).isoformat(timespec="seconds")
        self._conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (ts, user_id),
        )
        self._conn.commit()

    def update_pc_logged_in_at(self, user_id: int, when: datetime | None = None) -> None:
        """v4.0+：SQLite 实现。"""
        ts = (when or datetime.now()).isoformat(timespec="seconds")
        # 用 try/except 处理 v4 schema 升级前老库没有该列的情况
        try:
            self._conn.execute(
                "UPDATE users SET pc_logged_in_at = ? WHERE id = ?",
                (ts, user_id),
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            # 老库没有该列，先 ALTER 加上再 UPDATE
            self._conn.execute(
                "ALTER TABLE users ADD COLUMN pc_logged_in_at DATETIME"
            )
            self._conn.execute(
                "UPDATE users SET pc_logged_in_at = ? WHERE id = ?",
                (ts, user_id),
            )
            self._conn.commit()

    def set_password(self, user_id: int, new_password_hash: str) -> bool:
        """SQLite 实现：覆盖密码 hash。"""
        cur = self._conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_password_hash, user_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_by_openid(self, openid: str) -> Optional[WebUser]:
        """SQLite 实现：按 wechat_openid 查。"""
        if not openid:
            return None
        row = self._conn.execute(
            "SELECT * FROM users WHERE wechat_openid = ? COLLATE NOCASE",
            (openid,),
        ).fetchone()
        return _row_to_user(row) if row else None

    def bind_wechat_openid(self, user_id: int, openid: str) -> bool:
        """SQLite 实现：把 wechat_openid 写到指定用户。

        唯一约束保证 openid 不会被重复绑定（如果有冲突会抛 IntegrityError）。
        """
        if not openid:
            return False
        try:
            cur = self._conn.execute(
                "UPDATE users SET wechat_openid = ? WHERE id = ?",
                (openid, user_id),
            )
            self._conn.commit()
            return cur.rowcount > 0
        except sqlite3.IntegrityError:
            # openid 已被其他用户占用 → 拒绝绑定
            return False

    def set_email_and_password(
        self, user_id: int, email: str, password_hash: str,
    ) -> bool:
        """SQLite 实现：改邮箱 + 改密码（同一行 UPDATE，天然原子）。"""
        email_norm = email.strip().lower()
        row = self._conn.execute(
            "SELECT id FROM users WHERE email = ? COLLATE NOCASE",
            (email_norm,),
        ).fetchone()
        if row is not None and int(row["id"]) != int(user_id):
            raise WebUserEmailConflictError(f"邮箱 '{email_norm}' 已被注册")

        username = self._derive_username(email_norm, exclude_user_id=user_id)
        try:
            cur = self._conn.execute(
                "UPDATE users SET email = ?, password_hash = ?, username = ? "
                "WHERE id = ?",
                (email_norm, password_hash, username, user_id),
            )
        except sqlite3.IntegrityError as e:
            raise WebUserEmailConflictError(
                f"邮箱 '{email_norm}' 已被注册"
            ) from e
        self._conn.commit()
        return cur.rowcount > 0

    def _derive_username(self, email: str, exclude_user_id: int | None = None) -> str:
        """从邮箱派生唯一 username（与 create() 同一套规则）。"""
        base = email.split("@", 1)[0] or "user"
        username = base
        suffix = 1
        while True:
            row = self._conn.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
            if row is None or (
                exclude_user_id is not None and int(row["id"]) == exclude_user_id
            ):
                return username
            suffix += 1
            username = f"{base}{suffix}"

    def merge_user_data(
        self,
        from_user_id: int,
        to_user_id: int,
        wechat_openid: str | None = None,
    ) -> dict[str, int]:
        """SQLite 实现：事务内迁移业务数据 + 转移 openid + 删旧账号 + 写审计。

        业务表清单必须与 ``_MERGE_BUSINESS_TABLES`` 保持一致
        （MySQL 端表名相同，两端 schema 已对齐）。
        """
        import json

        from ielts_buddy.web.auth.merge_conflict import resolve_merge_conflicts

        moved: dict[str, int] = {}
        try:
            # 先提交可能残留的事务，避免 "cannot start a transaction within a transaction"
            self._conn.commit()
            self._conn.execute("BEGIN")
            # v4.0 关键：迁移 user_id **之前**先消解唯一约束冲突
            # （分类重名 / 同一个词两边都有 → 保留目标账号那份）
            resolve_merge_conflicts(self._conn, from_user_id, to_user_id)

            for table in _MERGE_BUSINESS_TABLES:
                # SQLite 端部分表结构与 MySQL 不同（vocab_category_words
                # 在 SQLite 是 (category_id, word_id, added_at)，没有 user_id），
                # 这类表无法按 user_id 迁移 → 跳过
                if not _sqlite_has_user_id(self._conn, table):
                    continue
                try:
                    cur = self._conn.execute(
                        f"UPDATE {table} SET user_id = ? WHERE user_id = ?",
                        (to_user_id, from_user_id),
                    )
                    moved[table] = cur.rowcount or 0
                except sqlite3.OperationalError as e:
                    # 老库缺这张表 → 跳过，不影响其它表迁移
                    if _is_missing_table(e):
                        logger.warning("[merge] 表 %s 不存在，跳过", table)
                        continue
                    raise

            if wechat_openid:
                # 关键顺序：先把**源账号**的 openid 置空，再写到目标账号。
                # 否则 UNIQUE(wechat_openid) 会因为两行同值而冲突。
                self._conn.execute(
                    "UPDATE users SET wechat_openid = NULL WHERE id = ?",
                    (from_user_id,),
                )
                self._conn.execute(
                    "UPDATE users SET wechat_openid = ? WHERE id = ?",
                    (wechat_openid, to_user_id),
                )
            self._conn.execute(
                "UPDATE users SET email_verified = 1 WHERE id = ?",
                (to_user_id,),
            )

            try:
                self._conn.execute(
                    "INSERT INTO user_merge_log "
                    "(from_user_id, to_user_id, merge_type, from_data_backup, "
                    " from_user_vocab_count, to_user_vocab_count) "
                    "VALUES (?, ?, 'wechat_to_email', ?, ?, ?)",
                    (
                        from_user_id,
                        to_user_id,
                        json.dumps({"id": from_user_id}, ensure_ascii=False),
                        moved.get("personal_vocab", 0),
                        moved.get("learning_records", 0),
                    ),
                )
            except sqlite3.OperationalError as e:
                # 审计表不存在（未跑 v4 迁移）→ 不阻断合并
                if not _is_missing_table(e):
                    raise
                logger.warning("[merge] user_merge_log 表不存在，跳过审计写入")

            self._conn.execute("DELETE FROM users WHERE id = ?", (from_user_id,))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return moved

    def close(self) -> None:
        # SQLite 连接由调用方管理；这里 no-op 保持接口对称
        pass


def create_sqlite_web_user_repository(
    db_path: str = ":memory:",
) -> SQLiteWebUserRepository:
    """便捷构造：传入 ``":memory:"``（默认）用于测试，传入文件路径用于本地开发。

    注：
    1. 连接所有权归仓储。FastAPI 同步端点会在 threadpool 跑，sqlite3 默认
       不允许跨线程，所以这里关掉 check_same_thread。
    2. 启用 WAL 模式 + busy_timeout：允许多个 web 进程同时读、单写者写入，
       避免数据库锁导致的 500 Internal Server Error（IDE 自动启动 8000 端口
       的 web 和用户手动启动 8765 端口的 web 共存场景）。
    """
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # WAL 模式 + busy_timeout：让多进程并发时不会直接 lock failed
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        # :memory: 模式或权限问题都不影响主流程
        pass
    return SQLiteWebUserRepository(conn)


# =============================================================
# MySQL 实现（生产环境）
# =============================================================


class MySQLWebUserRepository:
    """MySQL 实现 web 端用户仓储（v3+：读写都走 users 表）。"""

    def __init__(self, engine) -> None:
        self._engine = engine
        # users 表由 init_mysql.sql + migrate_v3_mysql_schema.py 维护；本仓储不做任何 DDL

    def _init_schema(self) -> None:
        """v3+：users 表由 init_mysql.sql + migrate_v3_mysql_schema.py 维护。"""
        pass

    def create(self, email: str, password_hash: str) -> WebUser:
        """v3+：写入统一 users 表。"""
        email_norm = email.strip().lower()
        now = datetime.now()
        base_username = email_norm.split("@", 1)[0] or "user"
        username = base_username
        suffix = 1
        from sqlalchemy import insert, select
        from sqlalchemy.exc import IntegrityError
        try:
            with self._engine.begin() as conn:
                while True:
                    exists = conn.execute(
                        select(t_users_mysql.c.id)
                        .where(t_users_mysql.c.username == username)
                    ).first()
                    if exists is None:
                        break
                    suffix += 1
                    username = f"{base_username}{suffix}"
                result = conn.execute(insert(t_users_mysql).values(
                    username=username,
                    email=email_norm,
                    password_hash=password_hash,
                    display_name=email_norm,
                    created_at=now,
                ))
                new_id = int(result.inserted_primary_key[0])
        except IntegrityError as e:
            raise WebUserEmailConflictError(
                f"邮箱 '{email_norm}' 已被注册"
            ) from e
        return WebUser(
            id=new_id,
            email=email_norm,
            password_hash=password_hash,
            created_at=now.isoformat(timespec="seconds"),
            last_login_at=None,
        )

    def get_by_email(self, email: str) -> Optional[WebUser]:
        """v3+：从统一 users 表按 email 查（v4.0+ 含 pc_logged_in_at/email_verified）。"""
        email_norm = email.strip().lower()
        from sqlalchemy import select
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_users_mysql).where(
                    t_users_mysql.c.email == email_norm
                )
            ).first()
            if row is None:
                return None
            m = row._mapping
            return WebUser(
                id=m["id"],
                email=m["email"],
                password_hash=m["password_hash"] or "",
                created_at=m["created_at"].isoformat() if m["created_at"] else None,
                last_login_at=m["last_login_at"].isoformat() if m["last_login_at"] else None,
                wechat_openid=m.get("wechat_openid"),
                pc_logged_in_at=m["pc_logged_in_at"].isoformat() if m.get("pc_logged_in_at") else None,
                email_verified=bool(m.get("email_verified", 0)),
            )

    def get_by_id(self, user_id: int) -> Optional[WebUser]:
        """v3+：从统一 users 表按 id 查（v4.0+ 含 pc_logged_in_at/email_verified）。"""
        from sqlalchemy import select
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_users_mysql).where(t_users_mysql.c.id == user_id)
            ).first()
            if row is None:
                return None
            m = row._mapping
            return WebUser(
                id=m["id"],
                email=m["email"],
                password_hash=m["password_hash"] or "",
                created_at=m["created_at"].isoformat() if m["created_at"] else None,
                last_login_at=m["last_login_at"].isoformat() if m["last_login_at"] else None,
                wechat_openid=m.get("wechat_openid"),
                pc_logged_in_at=m["pc_logged_in_at"].isoformat() if m.get("pc_logged_in_at") else None,
                email_verified=bool(m.get("email_verified", 0)),
            )

    def update_last_login(self, user_id: int, when: datetime | None = None) -> None:
        """v3+：更新 users.last_login_at。"""
        from sqlalchemy import update
        ts = when or datetime.now()
        with self._engine.begin() as conn:
            conn.execute(
                update(t_users_mysql)
                .where(t_users_mysql.c.id == user_id)
                .values(last_login_at=ts)
            )

    def update_pc_logged_in_at(self, user_id: int, when: datetime | None = None) -> None:
        """v4.0+：更新 users.pc_logged_in_at。"""
        from sqlalchemy import update
        ts = when or datetime.now()
        with self._engine.begin() as conn:
            conn.execute(
                update(t_users_mysql)
                .where(t_users_mysql.c.id == user_id)
                .values(pc_logged_in_at=ts)
            )

    def set_password(self, user_id: int, new_password_hash: str) -> bool:
        """v3+：更新 users.password_hash。"""
        from sqlalchemy import update
        with self._engine.begin() as conn:
            result = conn.execute(
                update(t_users_mysql)
                .where(t_users_mysql.c.id == user_id)
                .values(password_hash=new_password_hash)
            )
            return result.rowcount > 0

    def get_by_openid(self, openid: str) -> Optional[WebUser]:
        """v3+：从统一 users 表按 wechat_openid 查（小程序登录专用）。

        找不到返回 None；openid 通常 28 字符以内。
        """
        if not openid:
            return None
        from sqlalchemy import select
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_users_mysql).where(
                    t_users_mysql.c.wechat_openid == openid
                )
            ).first()
            if row is None:
                return None
            m = row._mapping
            # v4.0 修复：这里原来**漏了 wechat_openid**，
            # 导致 service 层 merge_wechat_to_existing 拿到的
            # placeholder.wechat_openid 恒为 None
            #   → from_user_snapshot['wechat_openid'] = None
            #   → merge_user_data(wechat_openid=None) 不转移 openid
            #   → 源账号被删 → openid 彻底丢失
            #   → 用户下次微信登录会创建一个全新空账号（数据看不到）
            # 同类问题见《技术复盘》"坑 8：多实现漏方法"——这里同理是漏字段。
            return WebUser(
                id=m["id"],
                email=m["email"],
                password_hash=m["password_hash"] or "",
                created_at=m["created_at"].isoformat() if m["created_at"] else None,
                last_login_at=m["last_login_at"].isoformat() if m["last_login_at"] else None,
                wechat_openid=m.get("wechat_openid"),
                pc_logged_in_at=(
                    m.get("pc_logged_in_at").isoformat()
                    if m.get("pc_logged_in_at") else None
                ),
                email_verified=bool(m.get("email_verified", 0)),
            )

    def bind_wechat_openid(self, user_id: int, openid: str) -> bool:
        """v3+：把 wechat_openid 写到指定用户（已存在用户绑定微信身份）。

        成功返回 True；用户不存在返回 False；openid 已被其他用户占用返回 False。
        """
        if not openid:
            return False
        from sqlalchemy import update
        from sqlalchemy.exc import IntegrityError
        try:
            with self._engine.begin() as conn:
                result = conn.execute(
                    update(t_users_mysql)
                    .where(t_users_mysql.c.id == user_id)
                    .values(wechat_openid=openid)
                )
                return result.rowcount > 0
        except IntegrityError:
            # openid 已被其他用户占用（唯一索引冲突）→ 拒绝绑定
            return False

    def set_email_and_password(
        self, user_id: int, email: str, password_hash: str,
    ) -> bool:
        """MySQL 实现：改邮箱 + 改密码。"""
        from sqlalchemy import select, update
        from sqlalchemy.exc import IntegrityError

        email_norm = email.strip().lower()
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_users_mysql.c.id).where(
                    t_users_mysql.c.email == email_norm
                )
            ).first()
        if row is not None and int(row[0]) != int(user_id):
            raise WebUserEmailConflictError(f"邮箱 '{email_norm}' 已被注册")

        username = self._derive_username(email_norm, exclude_user_id=user_id)
        try:
            with self._engine.begin() as conn:
                result = conn.execute(
                    update(t_users_mysql)
                    .where(t_users_mysql.c.id == user_id)
                    .values(
                        email=email_norm,
                        password_hash=password_hash,
                        username=username,
                    )
                )
                return result.rowcount > 0
        except IntegrityError as e:
            raise WebUserEmailConflictError(
                f"邮箱 '{email_norm}' 已被注册"
            ) from e

    def _derive_username(self, email: str, exclude_user_id: int | None = None) -> str:
        """从邮箱派生唯一 username（与 create() 同一套规则）。"""
        from sqlalchemy import select

        base = email.split("@", 1)[0] or "user"
        username = base
        suffix = 1
        with self._engine.connect() as conn:
            while True:
                row = conn.execute(
                    select(t_users_mysql.c.id).where(
                        t_users_mysql.c.username == username
                    )
                ).first()
                if row is None or (
                    exclude_user_id is not None and int(row[0]) == exclude_user_id
                ):
                    return username
                suffix += 1
                username = f"{base}{suffix}"

    def merge_user_data(
        self,
        from_user_id: int,
        to_user_id: int,
        wechat_openid: str | None = None,
    ) -> dict[str, int]:
        """MySQL 实现：事务内迁移业务数据 + 转移 openid + 删旧账号 + 写审计。

        v4 初版这里用的是 ``mysql_repo.get_mysql_engine()``（**该函数不存在**）
        + 一份与真实 schema 不符的表清单（vocab / mistakes / study_plans），
        导致合并 100% 抛 AttributeError / 表不存在。现在改为：
        - 直接用本仓储持有的 engine（不再另开连接）
        - 表清单改成 ``_MERGE_BUSINESS_TABLES``（与真实 schema 对齐）
        - 表不存在时跳过（兼容老库缺表的情况），而不是整单回滚
        """
        import json

        from sqlalchemy import text

        from ielts_buddy.web.auth.merge_conflict import resolve_merge_conflicts

        moved: dict[str, int] = {}
        with self._engine.begin() as conn:
            # v4.0 关键：迁移 user_id **之前**先消解唯一约束冲突。
            # 目标账号和源账号都持有系统内置分类 favorites/mistakes，
            # 而 vocab_categories 上有 UNIQUE(user_id, name)，
            # 不消解直接 UPDATE 必然报
            #   Duplicate entry '1155-favorites' for key 'vocab_categories.uk_vc_user_name'
            resolve_merge_conflicts(conn, from_user_id, to_user_id)

            for table in _MERGE_BUSINESS_TABLES:
                try:
                    result = conn.execute(
                        text(
                            f"UPDATE `{table}` SET user_id = :to_id "
                            "WHERE user_id = :from_id"
                        ),
                        {"to_id": to_user_id, "from_id": from_user_id},
                    )
                    moved[table] = result.rowcount or 0
                except SQLAlchemyError as e:
                    # 老库缺这张表 → 跳过，不影响其它表迁移
                    if _is_missing_table(e):
                        logger.warning(
                            "[merge] 表 %s 不存在，跳过", table
                        )
                        continue
                    raise

            if wechat_openid:
                # 关键顺序：先把**源账号**的 openid 置空，再写到目标账号。
                # 否则 UNIQUE(wechat_openid) 会因为两行同值而冲突。
                # 关键顺序：先把**源账号**的 openid 置空，再写到目标账号。
                # 否则 UNIQUE(wechat_openid) 会因为两行同值而冲突。
                conn.execute(
                    text("UPDATE users SET wechat_openid = NULL WHERE id = :uid"),
                    {"uid": from_user_id},
                )
                conn.execute(
                    text("UPDATE users SET wechat_openid = :openid WHERE id = :uid"),
                    {"openid": wechat_openid, "uid": to_user_id},
                )
            conn.execute(
                text("UPDATE users SET email_verified = 1 WHERE id = :uid"),
                {"uid": to_user_id},
            )

            try:
                conn.execute(
                    text(
                        "INSERT INTO user_merge_log "
                        "(from_user_id, to_user_id, merge_type, from_data_backup, "
                        " from_user_vocab_count, to_user_vocab_count) "
                        "VALUES (:from_id, :to_id, 'wechat_to_email', :backup, "
                        "        :from_vocab, :to_vocab)"
                    ),
                    {
                        "from_id": from_user_id,
                        "to_id": to_user_id,
                        "backup": json.dumps({"id": from_user_id}, ensure_ascii=False),
                        "from_vocab": moved.get("personal_vocab", 0),
                        "to_vocab": moved.get("learning_records", 0),
                    },
                )
            except SQLAlchemyError as e:
                if not _is_missing_table(e):
                    raise

            conn.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": from_user_id},
            )
        return moved

    def close(self) -> None:
        # MySQL 连接由 Engine 管理，这里 no-op
        pass


# MySQL 表元数据：v3+ 统一 users 表
from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Table, text as sa_text

_mysql_metadata = __import__("sqlalchemy", fromlist=["MetaData"]).MetaData()

t_users_mysql = Table(
    "users", _mysql_metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("username", String(64), nullable=False),
    Column("email", String(255), nullable=True),
    Column("password_hash", String(512), nullable=True),
    Column("display_name", String(64), nullable=True),
    Column("created_at", DateTime, nullable=False, server_default=sa_text("CURRENT_TIMESTAMP")),
    Column("last_login_at", DateTime, nullable=True),
    Column("wechat_openid", String(64), nullable=True, unique=True),
    Column("pc_logged_in_at", DateTime, nullable=True),  # v4.0+
    Column("email_verified", Integer, nullable=True, server_default="0"),  # v4.0+：合并时设为 1
)


def create_mysql_web_user_repository(connection_url: str | None = None):
    """创建 MySQL Web 用户仓储。

    Args:
        connection_url: SQLAlchemy MySQL URL，默认使用 mysql_repo.py 中的配置
    """
    from ielts_buddy.repositories.mysql_repo import create_mysql_repositories
    container = create_mysql_repositories(connection_url=connection_url)
    return MySQLWebUserRepository(container._engine)


__all__ = [
    "WebUser",
    "WebUserRepository",
    "SQLiteWebUserRepository",
    "MySQLWebUserRepository",
    "WebUserNotFoundError",
    "WebUserEmailConflictError",
    "create_sqlite_web_user_repository",
    "create_mysql_web_user_repository",
    "_LEGACY_SCHEMA_NOOP",  # 兼容旧测试可能导入
]
