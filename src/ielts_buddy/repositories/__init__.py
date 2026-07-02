"""Repository 实现包。

W2 阶段提供 SQLite 实现，W3 阶段提供 MySQL 实现。
上层代码（Services）通过 ``RepositoryContainer`` 接口注入。
"""
from ielts_buddy.repositories.sqlite_repo import (
    REVIEW_INTERVALS,
    SQLiteExamRepository,
    SQLiteGradeRepository,
    SQLiteLearningRepository,
    SQLitePersonalVocabRepository,
    SQLiteRepositoryContainer,
    SQLiteUserRepository,
    SQLiteVocabCacheRepository,
    create_sqlite_repositories,
)

# MySQL Repository（依赖 SQLAlchemy + PyMySQL，未安装时延迟导入失败）
try:
    from ielts_buddy.repositories.mysql_repo import (
        MySQLExamRepository,
        MySQLGradeRepository,
        MySQLLearningRepository,
        MySQLPersonalVocabRepository,
        MySQLRepositoryContainer,
        MySQLUserRepository,
        MySQLVocabCacheRepository,
        create_mysql_repositories,
    )
    _MYSQL_AVAILABLE = True
except ImportError:
    _MYSQL_AVAILABLE = False

__all__ = [
    "SQLiteLearningRepository",
    "SQLitePersonalVocabRepository",
    "SQLiteExamRepository",
    "SQLiteGradeRepository",
    "SQLiteVocabCacheRepository",
    "SQLiteUserRepository",
    "SQLiteRepositoryContainer",
    "create_sqlite_repositories",
    "REVIEW_INTERVALS",
]

if _MYSQL_AVAILABLE:
    __all__ += [
        "MySQLLearningRepository",
        "MySQLPersonalVocabRepository",
        "MySQLExamRepository",
        "MySQLGradeRepository",
        "MySQLVocabCacheRepository",
        "MySQLUserRepository",
        "MySQLRepositoryContainer",
        "create_mysql_repositories",
    ]


# =============================================================
# W4 阶段：模式分发工厂 create_repositories
# =============================================================
# Service 层从 ``from ielts_buddy.repositories import create_repositories``
# 拿工厂即可，不再 import 具体 SQLite/MySQL 字样。
# 传入 ``mode="online"`` 时透明切到 MySQL 容器；未安装 SQLAlchemy 则报错提示。


def create_repositories(
    mode: str = "local",
    *,
    db_path=None,
    cache_path=None,
    connection_url: str = "",
) -> "SQLiteRepositoryContainer | MySQLRepositoryContainer":
    """根据 mode 返回对应实现的容器。

    Args:
        mode: "local"（默认，SQLite）或 "online"（MySQL）
        db_path: 仅 local 模式使用；None 时取 get_db_path()
        cache_path: 仅 local 模式使用；None 时取 get_app_dir()/vocab_cache.db
        connection_url: 仅 online 模式使用；空串时取 get_mysql_url() 或模块默认

    Returns:
        SQLiteRepositoryContainer 或 MySQLRepositoryContainer
        （两者都满足 ``RepositoryContainer`` Protocol）

    Raises:
        ValueError: mode 非法
        ImportError: mode="online" 但 SQLAlchemy/PyMySQL 未安装
    """
    if mode == "local":
        return create_sqlite_repositories(db_path=db_path, cache_path=cache_path)
    if mode == "online":
        if not _MYSQL_AVAILABLE:
            raise ImportError(
                "在线模式需要安装 SQLAlchemy 与 PyMySQL："
                "pip install 'sqlalchemy>=2.0' pymysql cryptography"
            )
        url = connection_url or ""
        return create_mysql_repositories(connection_url=url or None)
    raise ValueError(
        f"未知 mode={mode!r}，应为 'local' 或 'online'"
    )


__all__ += ["create_repositories"]
