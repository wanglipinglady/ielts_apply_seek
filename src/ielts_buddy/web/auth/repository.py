"""Web 端用户仓储层（v3+：统一走 users 表，与 CLI 共享）。

历史：早期 web_users 独立表，v3 合并到 users 表。本文件保留 WebUser /
WebUserRepository Protocol / SQLite & MySQL 双实现，但所有读写都改走 users
表，不再依赖 web_users。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable


@dataclass
class WebUser:
    """Web 端用户领域对象。

    ``wechat_openid`` 是 2026-08-24 为微信小程序登录新增的字段，
    默认为 None（保持向后兼容，老用户不受影响）。
    """

    id: int
    email: str
    password_hash: str
    created_at: str | None = None
    last_login_at: str | None = None
    wechat_openid: str | None = None


# =============================================================
# 异常
# =============================================================


class WebUserNotFoundError(Exception):
    """按 email 查不到用户。"""


class WebUserEmailConflictError(Exception):
    """email 已被注册。"""


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

    def close(self) -> None:
        """关闭底层连接 / 释放资源。"""
        ...


# =============================================================
# SQLite 实现（测试 + 本地开发）
# =============================================================


# v3+：users 表由业务库 sqlite_repo._SCHEMA 统一创建，本仓储不再建任何表。
# 下面这个常量保留是为了不让旧测试导入报错，但实际不再使用。
_LEGACY_SCHEMA_NOOP = ""


def _row_to_user(row: sqlite3.Row) -> Optional[WebUser]:
    """sqlite3.Row → WebUser 转换（v3.9+ 含 wechat_openid 字段）。"""
    if row is None:
        return None
    # sqlite3.Row 支持 keys() 检查字段是否存在（v3.9 升级时老库可能没该列）
    cols = row.keys() if hasattr(row, "keys") else []
    openid = row["wechat_openid"] if "wechat_openid" in cols else None
    return WebUser(
        id=row["id"],
        email=row["email"] or "",
        password_hash=row["password_hash"] or "",
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
        wechat_openid=openid,
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
                    UNIQUE (username COLLATE NOCASE),
                    UNIQUE (email COLLATE NOCASE),
                    UNIQUE (wechat_openid COLLATE NOCASE)
                );
                """
            )
            self._conn.commit()
            return

        # 生产 db 已存在 users 表 → 幂等补列（v3.9 升级用）
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
        """v3+：从统一 users 表按 email 查。"""
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
            )

    def get_by_id(self, user_id: int) -> Optional[WebUser]:
        """v3+：从统一 users 表按 id 查。"""
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
            return WebUser(
                id=m["id"],
                email=m["email"],
                password_hash=m["password_hash"] or "",
                created_at=m["created_at"].isoformat() if m["created_at"] else None,
                last_login_at=m["last_login_at"].isoformat() if m["last_login_at"] else None,
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

    def close(self) -> None:
        # MySQL 连接由 Engine 管理，这里 no-op
        pass


# MySQL 表元数据：v3+ 统一 users 表
from sqlalchemy import BigInteger, Column, DateTime, String, Table, text as sa_text

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
