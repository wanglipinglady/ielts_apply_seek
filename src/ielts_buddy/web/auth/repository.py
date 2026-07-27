"""web_users 仓储层。

与 CLI 的 ``UserRepository``（``core/repository.py``）完全独立：
- CLI 端 username + 联网模式，无 password；
- Web 端 email + bcrypt 哈希 + last_login。

我们同样定义 Protocol + 双实现（SQLite / MySQL），但**不复用**现有任何 Repository
类，避免污染 CLI 路径。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable


@dataclass
class WebUser:
    """Web 端用户领域对象。"""

    id: int
    email: str
    password_hash: str
    created_at: str | None = None
    last_login_at: str | None = None


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
    """web_users 仓储接口。

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

    def close(self) -> None:
        """关闭底层连接 / 释放资源。"""
        ...


# =============================================================
# SQLite 实现（测试 + 本地开发）
# =============================================================


_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_login_at   TEXT,
    UNIQUE (email COLLATE NOCASE)
);
CREATE INDEX IF NOT EXISTS idx_wu_email ON web_users(email COLLATE NOCASE);
"""


def _row_to_user(row: sqlite3.Row) -> WebUser:
    return WebUser(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


class SQLiteWebUserRepository:
    """SQLite 实现的 web_users 仓储。

    默认 email 唯一约束 + COLLATE NOCASE，实现大小写不敏感。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        # 创建 schema（幂等）
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def create(self, email: str, password_hash: str) -> WebUser:
        email_norm = email.strip().lower()
        now = datetime.now().isoformat(timespec="seconds")
        try:
            cur = self._conn.execute(
                """INSERT INTO web_users (email, password_hash, created_at)
                   VALUES (?, ?, ?)""",
                (email_norm, password_hash, now),
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
            "SELECT * FROM web_users WHERE email = ? COLLATE NOCASE",
            (email_norm,),
        ).fetchone()
        return _row_to_user(row) if row else None

    def get_by_id(self, user_id: int) -> Optional[WebUser]:
        row = self._conn.execute(
            "SELECT * FROM web_users WHERE id = ?", (user_id,),
        ).fetchone()
        return _row_to_user(row) if row else None

    def update_last_login(self, user_id: int, when: datetime | None = None) -> None:
        ts = (when or datetime.now()).isoformat(timespec="seconds")
        self._conn.execute(
            "UPDATE web_users SET last_login_at = ? WHERE id = ?",
            (ts, user_id),
        )
        self._conn.commit()

    def close(self) -> None:
        # SQLite 连接由调用方管理；这里 no-op 保持接口对称
        pass


def create_sqlite_web_user_repository(
    db_path: str = ":memory:",
) -> SQLiteWebUserRepository:
    """便捷构造：传入 ``":memory:"``（默认）用于测试，传入文件路径用于本地开发。

    注：连接所有权归仓储。FastAPI 同步端点会在 threadpool 跑，sqlite3 默认
    不允许跨线程，所以这里关掉 check_same_thread。
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return SQLiteWebUserRepository(conn)


# =============================================================
# MySQL 实现（生产环境）
# =============================================================

_WEB_USERS_MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_users (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    email           VARCHAR(255) NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at   DATETIME,
    UNIQUE KEY uk_wu_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


class MySQLWebUserRepository:
    """MySQL 实现的 web_users 仓储（生产环境）。

    与 SQLite 版本接口完全一致。
    """

    def __init__(self, engine) -> None:
        self._engine = engine
        self._init_schema()

    def _init_schema(self) -> None:
        """初始化 MySQL 表结构。"""
        from sqlalchemy import text
        with self._engine.begin() as conn:
            conn.execute(text(_WEB_USERS_MYSQL_SCHEMA))

    def create(self, email: str, password_hash: str) -> WebUser:
        email_norm = email.strip().lower()
        now = datetime.now()
        from sqlalchemy import insert, select, text
        from sqlalchemy.exc import IntegrityError
        try:
            with self._engine.begin() as conn:
                result = conn.execute(insert(t_web_users_mysql).values(
                    email=email_norm,
                    password_hash=password_hash,
                    created_at=now,
                ))
                new_id = int(result.inserted_primary_key[0])
        except IntegrityError:
            raise WebUserEmailConflictError(
                f"邮箱 '{email_norm}' 已被注册"
            )
        return WebUser(
            id=new_id,
            email=email_norm,
            password_hash=password_hash,
            created_at=now.isoformat(timespec="seconds"),
            last_login_at=None,
        )

    def get_by_email(self, email: str) -> Optional[WebUser]:
        email_norm = email.strip().lower()
        from sqlalchemy import select
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_web_users_mysql).where(
                    t_web_users_mysql.c.email == email_norm
                )
            ).first()
            if row is None:
                return None
            m = row._mapping
            return WebUser(
                id=m["id"],
                email=m["email"],
                password_hash=m["password_hash"],
                created_at=m["created_at"].isoformat() if m["created_at"] else None,
                last_login_at=m["last_login_at"].isoformat() if m["last_login_at"] else None,
            )

    def get_by_id(self, user_id: int) -> Optional[WebUser]:
        from sqlalchemy import select
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_web_users_mysql).where(t_web_users_mysql.c.id == user_id)
            ).first()
            if row is None:
                return None
            m = row._mapping
            return WebUser(
                id=m["id"],
                email=m["email"],
                password_hash=m["password_hash"],
                created_at=m["created_at"].isoformat() if m["created_at"] else None,
                last_login_at=m["last_login_at"].isoformat() if m["last_login_at"] else None,
            )

    def update_last_login(self, user_id: int, when: datetime | None = None) -> None:
        from sqlalchemy import update
        ts = when or datetime.now()
        with self._engine.begin() as conn:
            conn.execute(
                update(t_web_users_mysql)
                .where(t_web_users_mysql.c.id == user_id)
                .values(last_login_at=ts)
            )

    def close(self) -> None:
        # MySQL 连接由 Engine 管理，这里 no-op
        pass


# MySQL 表元数据（与 mysql_repo.py 中的其他表一致）
from sqlalchemy import BigInteger, Column, DateTime, String, Table, text as sa_text

_mysql_metadata = __import__("sqlalchemy", fromlist=["MetaData"]).MetaData()

t_web_users_mysql = Table(
    "web_users", _mysql_metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("email", String(255), nullable=False, unique=True),
    Column("password_hash", String(512), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=sa_text("CURRENT_TIMESTAMP")),
    Column("last_login_at", DateTime, nullable=True),
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
    "_SCHEMA",  # 测试用
]
