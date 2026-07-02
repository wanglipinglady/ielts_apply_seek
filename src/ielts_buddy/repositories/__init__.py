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
