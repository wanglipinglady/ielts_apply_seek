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
