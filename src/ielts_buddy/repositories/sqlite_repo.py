"""SQLite Repository 实现。

W2 阶段：把 9 个 Service 里的 SQL 集中到本模块。
所有方法都带 ``user_id`` 参数（共享缓存除外），强制数据隔离。

关联方案: docs/方案_数据层扩展_v2.2.md §14 W2.1
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from ielts_buddy.core.config import get_app_dir, get_db_path
from ielts_buddy.core.models import (
    ExamReport,
    ExamSession,
    GradeResult,
    LearningRecord,
    PersonalWord,
    VocabCategory,
    Word,
)

# 艾宾浩斯复习间隔（天数），memory_level 0-6 对应
# 与原 review_service.py 保持一致
REVIEW_INTERVALS = [0, 1, 2, 4, 7, 15, 30]

# =============================================================
# Schema 定义
# =============================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    word TEXT NOT NULL,
    word_data TEXT NOT NULL,
    memory_level INTEGER DEFAULT 0,
    next_review TEXT,
    learn_count INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    wrong_count INTEGER DEFAULT 0,
    first_learned TEXT,
    last_reviewed TEXT,
    is_starred INTEGER DEFAULT 0,
    is_difficult INTEGER DEFAULT 0,
    source TEXT DEFAULT 'builtin',
    UNIQUE (user_id, word)
);
CREATE INDEX IF NOT EXISTS idx_lr_user_review
    ON learning_records(user_id, next_review);
CREATE INDEX IF NOT EXISTS idx_lr_user_first
    ON learning_records(user_id, first_learned);
CREATE INDEX IF NOT EXISTS idx_lr_user_last
    ON learning_records(user_id, last_reviewed);

CREATE TABLE IF NOT EXISTS personal_vocab (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    word TEXT NOT NULL,
    phonetic TEXT DEFAULT '',
    meaning TEXT DEFAULT '',
    pos TEXT DEFAULT '',
    band INTEGER DEFAULT 5,
    topic TEXT DEFAULT '',
    example TEXT DEFAULT '',
    example_cn TEXT DEFAULT '',
    note TEXT DEFAULT '',
    source TEXT DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, word)
);
CREATE INDEX IF NOT EXISTS idx_pv_user ON personal_vocab(user_id);

CREATE TABLE IF NOT EXISTS vocab_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    is_system INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_vc_user ON vocab_categories(user_id);

CREATE TABLE IF NOT EXISTS vocab_category_words (
    category_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (category_id, word_id),
    FOREIGN KEY (category_id) REFERENCES vocab_categories(id) ON DELETE CASCADE,
    FOREIGN KEY (word_id) REFERENCES personal_vocab(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exam_sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1,
    questions TEXT NOT NULL,
    time_limit INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    band_filter INTEGER,
    score INTEGER,
    total INTEGER,
    accuracy REAL,
    duration INTEGER,
    weak_words TEXT,
    band_breakdown TEXT
);
CREATE INDEX IF NOT EXISTS idx_es_user_started
    ON exam_sessions(user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS grade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    essay_text TEXT NOT NULL,
    topic TEXT DEFAULT '',
    overall_score REAL NOT NULL,
    task_response_score REAL,
    coherence_score REAL,
    lexical_score REAL,
    grammar_score REAL,
    result_json TEXT NOT NULL,
    task_type TEXT DEFAULT 'task2',
    error_summary_json TEXT DEFAULT '{}',
    graded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gh_user_graded
    ON grade_history(user_id, graded_at DESC);

CREATE TABLE IF NOT EXISTS vocab_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL,
    phonetic TEXT DEFAULT '',
    meaning TEXT NOT NULL,
    pos TEXT DEFAULT '',
    band INTEGER NOT NULL,
    topic TEXT DEFAULT '',
    example TEXT DEFAULT '',
    example_cn TEXT DEFAULT '',
    collocations TEXT DEFAULT '[]',
    synonyms TEXT DEFAULT '[]',
    etymology TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_vocab_word ON vocab_cache(word);
CREATE INDEX IF NOT EXISTS idx_vocab_band ON vocab_cache(band);
CREATE INDEX IF NOT EXISTS idx_vocab_topic ON vocab_cache(topic);

CREATE TABLE IF NOT EXISTS cache_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Web 端用户表（与业务表共存于同一个 db 文件）
-- 字段含义与 MySQL 的 web_users 完全一致
CREATE TABLE IF NOT EXISTS web_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT,
    last_login_at TEXT,
    UNIQUE (email COLLATE NOCASE)
);
CREATE INDEX IF NOT EXISTS idx_wu_email ON web_users(email COLLATE NOCASE);
"""

# 系统内置分类（每个用户独立一份，不使用 user_id=0 模板）
_SYSTEM_CATEGORIES = [
    ("favorites", "收藏夹"),
    ("mistakes", "错词本"),
]


# =============================================================
# 工具函数
# =============================================================

def _row_to_learning_record(row: sqlite3.Row) -> LearningRecord:
    return LearningRecord(
        id=row["id"],
        user_id=row["user_id"],
        word_id=row["id"],  # SQLite 中 word_id == id
        memory_level=row["memory_level"],
        next_review=row["next_review"],
        learn_count=row["learn_count"],
        correct_count=row["correct_count"],
        wrong_count=row["wrong_count"],
        first_learned=row["first_learned"],
        last_reviewed=row["last_reviewed"],
        is_starred=bool(row["is_starred"]),
        is_difficult=bool(row["is_difficult"]),
    )


def _row_to_personal_word(row: sqlite3.Row) -> PersonalWord:
    return PersonalWord(
        id=row["id"],
        user_id=row["user_id"],
        word=row["word"],
        phonetic=row["phonetic"],
        meaning=row["meaning"],
        pos=row["pos"],
        band=row["band"],
        topic=row["topic"],
        example=row["example"],
        example_cn=row["example_cn"],
        note=row["note"],
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_vocab_category(row: sqlite3.Row) -> VocabCategory:
    return VocabCategory(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        description=row["description"],
        is_system=bool(row["is_system"]),
        word_count=row["word_count"] if "word_count" in row.keys() else 0,
        created_at=row["created_at"],
    )


def _next_review_date(today_str: str, level: int) -> str:
    today = date.fromisoformat(today_str)
    interval = REVIEW_INTERVALS[min(level, len(REVIEW_INTERVALS) - 1)]
    return (today + timedelta(days=interval)).isoformat()


# =============================================================
# Schema 自动迁移
# =============================================================

# 旧版 → W2 版：需要补齐的列（业务表）
_MIGRATIONS = {
    "learning_records": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
        ("source", "TEXT DEFAULT 'builtin'"),
    ],
    "personal_vocab": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "vocab_categories": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "exam_sessions": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "grade_history": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
    ],
    # error_summary_json / task_type 旧版迁移（grading_service 原逻辑）
    "grade_history_legacy": [
        ("task_type", "TEXT DEFAULT 'task2'"),
        ("error_summary_json", "TEXT DEFAULT '{}'"),
    ],
}


def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    """为旧版数据库补齐缺失的列（幂等）。

    W2 阶段：所有业务表都加 ``user_id``，并补齐历史迁移
    （learning_records.source、grade_history.task_type 等）。
    """
    for table, columns in _MIGRATIONS.items():
        # 兼容特殊 key ``grade_history_legacy``（已在 grade_history 处理）
        actual_table = table.replace("_legacy", "")
        # 检查表是否存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (actual_table,),
        ).fetchone()
        if row is None:
            continue  # 表还没建，等下次 _SCHEMA 生效
        # 检查已有列
        cur = conn.execute(f"PRAGMA table_info({actual_table})")
        existing = {r[1] for r in cur.fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing:
                conn.execute(
                    f"ALTER TABLE {actual_table} ADD COLUMN {col_name} {col_def}"
                )
    conn.commit()


# =============================================================
# 1. SQLiteLearningRepository
# =============================================================


class SQLiteLearningRepository:
    """SQLite 实现的 LearningRepository。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---- 单条记录 ----

    def get_record(self, user_id: int, word: str) -> Optional[LearningRecord]:
        row = self._conn.execute(
            "SELECT * FROM learning_records WHERE user_id = ? AND word = ?",
            (user_id, word),
        ).fetchone()
        return _row_to_learning_record(row) if row else None

    def upsert_record(
        self,
        user_id: int,
        word: Word,
        correct: bool,
        source: str = "builtin",
    ) -> LearningRecord:
        """插入或更新学习记录，自动推进艾宾浩斯 level。"""
        now = datetime.now().isoformat(timespec="seconds")
        today = date.today().isoformat()

        row = self._conn.execute(
            "SELECT * FROM learning_records WHERE user_id = ? AND word = ?",
            (user_id, word.word),
        ).fetchone()

        if row is None:
            level = 1 if correct else 0
            next_review = _next_review_date(today, level)
            word_data = word.model_dump_json()
            self._conn.execute(
                """INSERT INTO learning_records
                   (user_id, word, word_data, memory_level, next_review,
                    learn_count, correct_count, wrong_count,
                    first_learned, last_reviewed, source)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                (
                    user_id, word.word, word_data, level, next_review,
                    1 if correct else 0,
                    0 if correct else 1,
                    now, now, source,
                ),
            )
        else:
            level = row["memory_level"]
            if correct:
                level = min(level + 1, len(REVIEW_INTERVALS) - 1)
            else:
                level = max(level - 1, 0)
            next_review = _next_review_date(today, level)
            self._conn.execute(
                """UPDATE learning_records SET
                   memory_level = ?,
                   next_review = ?,
                   learn_count = learn_count + 1,
                   correct_count = correct_count + ?,
                   wrong_count = wrong_count + ?,
                   last_reviewed = ?
                   WHERE user_id = ? AND word = ?""",
                (
                    level, next_review,
                    1 if correct else 0,
                    0 if correct else 1,
                    now, user_id, word.word,
                ),
            )

        self._conn.commit()
        return self.get_record(user_id, word.word)  # type: ignore[return-value]

    def toggle_star(self, user_id: int, word: str) -> bool:
        row = self._conn.execute(
            "SELECT is_starred FROM learning_records WHERE user_id = ? AND word = ?",
            (user_id, word),
        ).fetchone()
        if row is None:
            raise ValueError(f"未找到单词 '{word}' 的学习记录")
        new_state = 0 if row["is_starred"] else 1
        self._conn.execute(
            "UPDATE learning_records SET is_starred = ? WHERE user_id = ? AND word = ?",
            (new_state, user_id, word),
        )
        self._conn.commit()
        return bool(new_state)

    def toggle_difficult(self, user_id: int, word: str) -> bool:
        row = self._conn.execute(
            "SELECT is_difficult FROM learning_records WHERE user_id = ? AND word = ?",
            (user_id, word),
        ).fetchone()
        if row is None:
            raise ValueError(f"未找到单词 '{word}' 的学习记录")
        new_state = 0 if row["is_difficult"] else 1
        self._conn.execute(
            "UPDATE learning_records SET is_difficult = ? WHERE user_id = ? AND word = ?",
            (new_state, user_id, word),
        )
        self._conn.commit()
        return bool(new_state)

    # ---- 复习计划 ----

    def get_due_words(self, user_id: int, limit: int = 20) -> list[dict]:
        today = date.today().isoformat()
        rows = self._conn.execute(
            """SELECT * FROM learning_records
               WHERE user_id = ? AND next_review <= ?
               ORDER BY memory_level ASC, next_review ASC
               LIMIT ?""",
            (user_id, today, limit),
        ).fetchall()
        results = []
        for row in rows:
            word_data = Word(**json.loads(row["word_data"]))
            record = _row_to_learning_record(row)
            results.append({"word": row["word"], "word_data": word_data, "record": record})
        return results

    def get_due_count(self, user_id: int) -> int:
        today = date.today().isoformat()
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM learning_records WHERE user_id = ? AND next_review <= ?",
            (user_id, today),
        ).fetchone()
        return row["cnt"]

    def get_history(self, user_id: int, days: int = 30) -> list[dict]:
        """最近 N 天的学习活动（每日聚合）。"""
        today = date.today()
        start = today - timedelta(days=days - 1)
        start_str = start.isoformat()

        new_rows = self._conn.execute(
            """SELECT DATE(first_learned) as learn_date, COUNT(*) as cnt
               FROM learning_records
               WHERE user_id = ? AND DATE(first_learned) >= ?
               GROUP BY DATE(first_learned)""",
            (user_id, start_str),
        ).fetchall()
        review_rows = self._conn.execute(
            """SELECT DATE(last_reviewed) as review_date, COUNT(*) as cnt
               FROM learning_records
               WHERE user_id = ? AND DATE(last_reviewed) >= ?
               GROUP BY DATE(last_reviewed)""",
            (user_id, start_str),
        ).fetchall()

        new_counts = {row["learn_date"]: row["cnt"] for row in new_rows}
        review_counts = {row["review_date"]: row["cnt"] for row in review_rows}

        result = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            result.append({
                "date": d,
                "new_words": new_counts.get(d, 0),
                "reviewed_words": review_counts.get(d, 0),
            })
        return result

    # ---- 全量查询 ----

    def get_all_records(self, user_id: int) -> list[LearningRecord]:
        rows = self._conn.execute(
            "SELECT * FROM learning_records WHERE user_id = ? ORDER BY last_reviewed DESC",
            (user_id,),
        ).fetchall()
        return [_row_to_learning_record(row) for row in rows]

    def get_learned_count(self, user_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM learning_records WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["cnt"]

    def get_learned_words_today(self, user_id: int) -> list[str]:
        today = date.today().isoformat()
        rows = self._conn.execute(
            """SELECT word FROM learning_records
               WHERE user_id = ? AND DATE(first_learned) = ?""",
            (user_id, today),
        ).fetchall()
        return [row["word"] for row in rows]

    def get_learned_words(self, user_id: int) -> list[str]:
        """返回用户学过的所有词（任意时间），用于\"挑没学过的词\"。
        注意：与 get_learned_words_today 不同 —— 后者只看今天的。
        """
        rows = self._conn.execute(
            "SELECT word FROM learning_records WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return [row["word"] for row in rows]


# =============================================================
# 2. SQLitePersonalVocabRepository
# =============================================================


class SQLitePersonalVocabRepository:
    """SQLite 实现的 PersonalVocabRepository。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _ensure_system_categories(self, user_id: int) -> None:
        """确保当前用户的系统分类存在（幂等）"""
        now = datetime.now().isoformat(timespec="seconds")
        for name, desc in _SYSTEM_CATEGORIES:
            self._conn.execute(
                """INSERT OR IGNORE INTO vocab_categories
                   (user_id, name, description, is_system, created_at)
                   VALUES (?, ?, ?, 1, ?)""",
                (user_id, name, desc, now),
            )
        self._conn.commit()

    # ---- 单词 CRUD ----

    def add_word(self, user_id: int, pw: PersonalWord) -> int:
        self._ensure_system_categories(user_id)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            cur = self._conn.execute(
                """INSERT INTO personal_vocab
                   (user_id, word, phonetic, meaning, pos, band, topic,
                    example, example_cn, note, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id, pw.word, pw.phonetic, pw.meaning, pw.pos,
                    pw.band, pw.topic, pw.example, pw.example_cn,
                    pw.note, pw.source, now, now,
                ),
            )
            self._conn.commit()
            return cur.lastrowid or 0
        except sqlite3.IntegrityError:
            raise ValueError(f"单词 '{pw.word}' 已存在于个人词库中")

    def edit_word(self, user_id: int, word_name: str, **kwargs: Any) -> PersonalWord:
        existing = self.get_word(user_id, word_name)
        if existing is None:
            raise ValueError(f"单词 '{word_name}' 不在个人词库中")

        allowed_fields = {"phonetic", "meaning", "pos", "band", "topic", "example", "example_cn", "note"}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}
        if not updates:
            return existing

        now = datetime.now().isoformat(timespec="seconds")
        updates["updated_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id, word_name]
        self._conn.execute(
            f"UPDATE personal_vocab SET {set_clause} WHERE user_id = ? AND word = ?",
            values,
        )
        self._conn.commit()
        return self.get_word(user_id, word_name)  # type: ignore[return-value]

    def delete_word(self, user_id: int, word_name: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM personal_vocab WHERE user_id = ? AND word = ?",
            (user_id, word_name),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_word(self, user_id: int, word_name: str) -> Optional[PersonalWord]:
        row = self._conn.execute(
            "SELECT * FROM personal_vocab WHERE user_id = ? AND word = ?",
            (user_id, word_name),
        ).fetchone()
        return _row_to_personal_word(row) if row else None

    def list_words(
        self,
        user_id: int,
        category: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[PersonalWord], int]:
        if category:
            cat_row = self._conn.execute(
                "SELECT id FROM vocab_categories WHERE user_id = ? AND name = ?",
                (user_id, category),
            ).fetchone()
            if cat_row is None:
                return [], 0
            cat_id = cat_row["id"]

            count_row = self._conn.execute(
                """SELECT COUNT(*) as cnt FROM personal_vocab p
                   JOIN vocab_category_words cw ON p.id = cw.word_id
                   WHERE cw.category_id = ? AND p.user_id = ?""",
                (cat_id, user_id),
            ).fetchone()
            total = count_row["cnt"]

            offset = (page - 1) * per_page
            rows = self._conn.execute(
                """SELECT p.* FROM personal_vocab p
                   JOIN vocab_category_words cw ON p.id = cw.word_id
                   WHERE cw.category_id = ? AND p.user_id = ?
                   ORDER BY p.created_at DESC
                   LIMIT ? OFFSET ?""",
                (cat_id, user_id, per_page, offset),
            ).fetchall()
        else:
            count_row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM personal_vocab WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            total = count_row["cnt"]

            offset = (page - 1) * per_page
            rows = self._conn.execute(
                """SELECT * FROM personal_vocab WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (user_id, per_page, offset),
            ).fetchall()

        return [_row_to_personal_word(r) for r in rows], total

    def get_word_count(self, user_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM personal_vocab WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["cnt"]

    # ---- 分类管理 ----

    def create_category(
        self,
        user_id: int,
        name: str,
        description: str = "",
    ) -> VocabCategory:
        self._ensure_system_categories(user_id)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            self._conn.execute(
                """INSERT INTO vocab_categories
                   (user_id, name, description, is_system, created_at)
                   VALUES (?, ?, ?, 0, ?)""",
                (user_id, name, description, now),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"分类 '{name}' 已存在")
        cat = self._get_category_by_name(user_id, name)
        if cat is None:
            raise ValueError(f"分类 '{name}' 创建失败")
        return cat

    def delete_category(self, user_id: int, name: str) -> bool:
        self._ensure_system_categories(user_id)
        cat = self._get_category_by_name(user_id, name)
        if cat is None:
            raise ValueError(f"分类 '{name}' 不存在")
        if cat.is_system:
            raise ValueError(f"系统分类 '{name}' 不可删除")
        self._conn.execute(
            "DELETE FROM vocab_categories WHERE user_id = ? AND name = ?",
            (user_id, name),
        )
        self._conn.commit()
        return True

    def list_categories(self, user_id: int) -> list[VocabCategory]:
        self._ensure_system_categories(user_id)
        rows = self._conn.execute(
            """SELECT c.*, COUNT(cw.word_id) as word_count
               FROM vocab_categories c
               LEFT JOIN vocab_category_words cw ON c.id = cw.category_id
               WHERE c.user_id = ?
               GROUP BY c.id
               ORDER BY c.is_system DESC, c.name ASC""",
            (user_id,),
        ).fetchall()
        return [_row_to_vocab_category(r) for r in rows]

    def add_to_category(
        self,
        user_id: int,
        word: str,
        category: str,
    ) -> bool:
        word_row = self._conn.execute(
            "SELECT id FROM personal_vocab WHERE user_id = ? AND word = ?",
            (user_id, word),
        ).fetchone()
        if word_row is None:
            raise ValueError(f"单词 '{word}' 不在个人词库中")
        cat = self._get_category_by_name(user_id, category)
        if cat is None:
            raise ValueError(f"分类 '{category}' 不存在")
        now = datetime.now().isoformat(timespec="seconds")
        try:
            self._conn.execute(
                """INSERT INTO vocab_category_words (category_id, word_id, added_at)
                   VALUES (?, ?, ?)""",
                (cat.id, word_row["id"], now),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            return False
        return True

    def remove_from_category(
        self,
        user_id: int,
        word: str,
        category: str,
    ) -> bool:
        word_row = self._conn.execute(
            "SELECT id FROM personal_vocab WHERE user_id = ? AND word = ?",
            (user_id, word),
        ).fetchone()
        if word_row is None:
            raise ValueError(f"单词 '{word}' 不在个人词库中")
        cat = self._get_category_by_name(user_id, category)
        if cat is None:
            raise ValueError(f"分类 '{category}' 不存在")
        cur = self._conn.execute(
            "DELETE FROM vocab_category_words WHERE category_id = ? AND word_id = ?",
            (cat.id, word_row["id"]),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_word_categories(
        self,
        user_id: int,
        word: str,
    ) -> list[VocabCategory]:
        word_row = self._conn.execute(
            "SELECT id FROM personal_vocab WHERE user_id = ? AND word = ?",
            (user_id, word),
        ).fetchone()
        if word_row is None:
            return []
        rows = self._conn.execute(
            """SELECT c.*, 0 as word_count FROM vocab_categories c
               JOIN vocab_category_words cw ON c.id = cw.category_id
               WHERE cw.word_id = ? AND c.user_id = ?
               ORDER BY c.name""",
            (word_row["id"], user_id),
        ).fetchall()
        return [_row_to_vocab_category(r) for r in rows]

    # ---- 特殊方法 ----

    def add_mistake(
        self,
        user_id: int,
        word: Word | PersonalWord,
        source: str = "quiz_mistake",
    ) -> PersonalWord:
        existing = self.get_word(user_id, word.word)
        if existing is None:
            pw = PersonalWord(
                word=word.word,
                phonetic=getattr(word, "phonetic", ""),
                meaning=getattr(word, "meaning", ""),
                pos=getattr(word, "pos", ""),
                band=getattr(word, "band", 5),
                topic=getattr(word, "topic", ""),
                example=getattr(word, "example", ""),
                example_cn=getattr(word, "example_cn", ""),
                source=source,
            )
            self.add_word(user_id, pw)
            existing = self.get_word(user_id, word.word)
        self.add_to_category(user_id, existing.word, "mistakes")  # type: ignore[union-attr]
        return existing  # type: ignore[return-value]

    def add_from_grading(
        self,
        user_id: int,
        word: str,
        context: str = "",
        suggestion: str = "",
        comment: str = "",
    ) -> PersonalWord:
        existing = self.get_word(user_id, word)
        if existing is not None:
            return existing
        pw = PersonalWord(
            word=word,
            example=context,
            example_cn=suggestion,
            note=comment,
            source="grading",
        )
        self.add_word(user_id, pw)
        return self.get_word(user_id, word)  # type: ignore[return-value]

    # ---- 统计 ----

    def get_source_distribution(self, user_id: int) -> dict[str, int]:
        rows = self._conn.execute(
            """SELECT source, COUNT(*) as cnt
               FROM personal_vocab WHERE user_id = ?
               GROUP BY source ORDER BY cnt DESC""",
            (user_id,),
        ).fetchall()
        return {row["source"]: row["cnt"] for row in rows}

    def get_band_distribution(self, user_id: int) -> dict[int, int]:
        rows = self._conn.execute(
            """SELECT band, COUNT(*) as cnt
               FROM personal_vocab WHERE user_id = ?
               GROUP BY band ORDER BY band""",
            (user_id,),
        ).fetchall()
        return {row["band"]: row["cnt"] for row in rows}

    # ---- 导入导出（W2 阶段：纯 SQL 实现，无 Service 依赖） ----

    def import_words(
        self,
        user_id: int,
        file_path: Any,
        vocab_service: Any = None,
    ) -> dict[str, int]:
        """从文件导入单词（JSON / CSV / 纯文本）。

        W2 阶段：直接用底层 SQL + _repo.add_word 实现，避免与 Service 循环依赖。
        返回 ``{"imported": N, "skipped": M, "failed": K}``。
        """
        import csv as _csv
        import io as _io

        suffix = Path(file_path).suffix.lower()
        content = Path(file_path).read_text(encoding="utf-8").strip()
        if not content:
            return {"imported": 0, "skipped": 0, "failed": 0}

        # 解析文件
        words: list[PersonalWord] = []
        if suffix == ".json":
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                return {"imported": 0, "skipped": 0, "failed": 0}
            if not isinstance(data, list):
                return {"imported": 0, "skipped": 0, "failed": 0}
            for item in data:
                if not isinstance(item, dict) or "word" not in item:
                    continue
                try:
                    words.append(PersonalWord(
                        word=item["word"],
                        meaning=item.get("meaning", ""),
                        phonetic=item.get("phonetic", ""),
                        pos=item.get("pos", ""),
                        band=item.get("band", 5),
                        topic=item.get("topic", ""),
                        example=item.get("example", ""),
                        example_cn=item.get("example_cn", ""),
                        note=item.get("note", ""),
                        source="import",
                    ))
                except Exception:
                    continue
        elif suffix == ".csv":
            reader = _csv.DictReader(_io.StringIO(content))
            for row in reader:
                if "word" not in row:
                    continue
                try:
                    band = int(row.get("band", 5))
                    band = max(5, min(9, band))
                except (ValueError, TypeError):
                    band = 5
                try:
                    words.append(PersonalWord(
                        word=row["word"].strip(),
                        meaning=row.get("meaning", "").strip(),
                        phonetic=row.get("phonetic", "").strip(),
                        pos=row.get("pos", "").strip(),
                        band=band,
                        topic=row.get("topic", "").strip(),
                        example=row.get("example", "").strip(),
                        example_cn=row.get("example_cn", "").strip(),
                        note=row.get("note", "").strip(),
                        source="import",
                    ))
                except Exception:
                    continue
        else:
            # 纯文本
            for line in content.splitlines():
                word_text = line.strip()
                if not word_text:
                    continue
                if vocab_service:
                    builtin = vocab_service.get_word(word_text)
                    if builtin:
                        words.append(PersonalWord(
                            word=builtin.word,
                            phonetic=builtin.phonetic,
                            meaning=builtin.meaning,
                            pos=builtin.pos,
                            band=builtin.band,
                            topic=builtin.topic,
                            example=builtin.example,
                            example_cn=builtin.example_cn,
                            source="import",
                        ))
                        continue
                words.append(PersonalWord(word=word_text, source="import"))

        # 写入
        imported = 0
        skipped = 0
        failed = 0
        for pw in words:
            if not pw.word.strip():
                failed += 1
                continue
            try:
                self.add_word(user_id, pw)
                imported += 1
            except ValueError:
                skipped += 1
            except Exception:
                failed += 1
        return {"imported": imported, "skipped": skipped, "failed": failed}

    def export_words(
        self,
        user_id: int,
        fmt: str = "json",
        category: Optional[str] = None,
    ) -> str:
        """导出为 JSON / CSV。"""
        import csv as _csv
        import io as _io

        words, _ = self.list_words(user_id, category=category, page=1, per_page=999_999)
        if not words:
            return "[]" if fmt == "json" else ""

        if fmt == "csv":
            output = _io.StringIO()
            writer = _csv.DictWriter(
                output,
                fieldnames=["word", "phonetic", "meaning", "pos", "band", "topic", "example", "example_cn", "note"],
            )
            writer.writeheader()
            for w in words:
                writer.writerow({
                    "word": w.word, "phonetic": w.phonetic, "meaning": w.meaning,
                    "pos": w.pos, "band": w.band, "topic": w.topic,
                    "example": w.example, "example_cn": w.example_cn, "note": w.note,
                })
            return output.getvalue()

        # JSON
        data = [{
            "word": w.word, "phonetic": w.phonetic, "meaning": w.meaning,
            "pos": w.pos, "band": w.band, "topic": w.topic,
            "example": w.example, "example_cn": w.example_cn, "note": w.note,
        } for w in words]
        return json.dumps(data, ensure_ascii=False, indent=2)

    # ---- 内部 ----

    def _get_category_by_name(
        self, user_id: int, name: str
    ) -> Optional[VocabCategory]:
        row = self._conn.execute(
            "SELECT * FROM vocab_categories WHERE user_id = ? AND name = ?",
            (user_id, name),
        ).fetchone()
        if row is None:
            return None
        return _row_to_vocab_category(row)


# =============================================================
# 3. SQLiteExamRepository
# =============================================================


class SQLiteExamRepository:
    """SQLite 实现的 ExamRepository。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_exam(
        self,
        user_id: int,
        band: int,
        count: int,
        time_limit: int = 20,
    ) -> ExamSession:
        """创建一场模拟考试（题目由 VocabService 注入时生成）。

        注：v2.2 W2.1 阶段，题目生成仍由 Service 层负责（依赖 VocabService），
        Repository 只负责 session 落库。Service 层将题目构造好后调用
        ``_save_exam`` 持久化。
        """
        # 占位实现：实际生成由 ExamService.create_exam 完成
        return ExamSession(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            time_limit=time_limit,
            started_at=datetime.now().isoformat(timespec="seconds"),
            band_filter=band,
        )

    def submit_answer(
        self,
        user_id: int,
        session_id: str,
        q_index: int,
        answer: str,
    ) -> dict:
        """提交一题答案（题目从 DB 反序列化）。"""
        row = self._conn.execute(
            "SELECT questions FROM exam_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"考试 {session_id} 不存在")
        questions = json.loads(row["questions"])
        if q_index < 0 or q_index >= len(questions):
            raise IndexError(f"题号 {q_index} 超出范围")
        q = questions[q_index]
        # 判分逻辑
        if q["mode"] == "en2zh":
            meanings = q["answer"].replace("；", "，").replace(",", "，").split("，")
            is_correct = any(
                m.strip() in answer or answer in m.strip()
                for m in meanings if m.strip()
            )
        else:
            is_correct = answer.strip().lower() == q["answer"].strip().lower()
        q["user_answer"] = answer
        q["is_correct"] = is_correct
        # 写回
        self._conn.execute(
            "UPDATE exam_sessions SET questions = ? WHERE id = ?",
            (json.dumps(questions, ensure_ascii=False), session_id),
        )
        self._conn.commit()
        return {"correct": is_correct, "answer": q["answer"]}

    def finish_exam(self, user_id: int, session_id: str) -> ExamReport:
        row = self._conn.execute(
            "SELECT * FROM exam_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"考试 {session_id} 不存在")
        questions = json.loads(row["questions"])
        finished_at = datetime.now().isoformat(timespec="seconds")

        answered = [q for q in questions if q.get("is_correct") is not None]
        correct_count = sum(1 for q in answered if q.get("is_correct"))
        total = len(answered)
        accuracy = correct_count / total if total > 0 else 0.0

        band_breakdown: dict[int, dict[str, int]] = {}
        for q in answered:
            b = q.get("band", 5)
            if b not in band_breakdown:
                band_breakdown[b] = {"correct": 0, "wrong": 0}
            if q.get("is_correct"):
                band_breakdown[b]["correct"] += 1
            else:
                band_breakdown[b]["wrong"] += 1

        weak_words = [q["word"] for q in answered if not q.get("is_correct")]

        started = datetime.fromisoformat(row["started_at"])
        finished = datetime.fromisoformat(finished_at)
        duration = int((finished - started).total_seconds())

        report = ExamReport(
            session_id=session_id,
            user_id=user_id,
            score=correct_count,
            total=total,
            accuracy=accuracy,
            band_breakdown=band_breakdown,
            weak_words=weak_words,
            duration=duration,
            finished_at=finished_at,
        )

        self._conn.execute(
            """UPDATE exam_sessions SET
               finished_at = ?, score = ?, total = ?, accuracy = ?,
               duration = ?, weak_words = ?, band_breakdown = ?
               WHERE id = ?""",
            (
                finished_at, report.score, report.total, report.accuracy,
                report.duration,
                json.dumps(report.weak_words, ensure_ascii=False),
                json.dumps(report.band_breakdown, ensure_ascii=False),
                session_id,
            ),
        )
        self._conn.commit()
        return report

    def save_exam_session(self, user_id: int, session: ExamSession) -> None:
        """显式落库考试 session（被 Service 层 / web router 调用）。

        注：与 MySQL 版同名同语义。exam_sessions 表已有 id (session_id)、
        user_id、questions (json 字符串)、time_limit、started_at、band_filter
        等字段；这里只插入，让后续 submit_answer/finish_exam 走 UPDATE。
        """
        questions_json = json.dumps(
            [q.model_dump() for q in session.questions], ensure_ascii=False
        )
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO exam_sessions
                   (id, user_id, questions, time_limit, started_at, band_filter)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session.id, user_id, questions_json,
                    session.time_limit, session.started_at,
                    session.band_filter,
                ),
            )

    def get_exam_history(
        self,
        user_id: int,
        limit: int = 20,
    ) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM exam_sessions
               WHERE user_id = ? AND finished_at IS NOT NULL
               ORDER BY finished_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        results = []
        for row in rows:
            results.append({
                "session_id": row["id"],
                "score": row["score"] or 0,
                "total": row["total"] or 0,
                "accuracy": row["accuracy"] or 0.0,
                "band_breakdown": json.loads(row["band_breakdown"])
                if row["band_breakdown"] else {},
                "weak_words": json.loads(row["weak_words"])
                if row["weak_words"] else [],
                "duration": row["duration"] or 0,
                "finished_at": row["finished_at"] or "",
            })
        return results

    def get_exam_session(
        self,
        user_id: int,
        session_id: str,
    ) -> Optional[ExamSession]:
        row = self._conn.execute(
            "SELECT * FROM exam_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        if row is None:
            return None
        questions_data = json.loads(row["questions"])
        from ielts_buddy.core.models import ExamQuestion

        questions = [ExamQuestion(**q) for q in questions_data]
        return ExamSession(
            id=row["id"],
            user_id=row["user_id"],
            questions=questions,
            time_limit=row["time_limit"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            band_filter=row["band_filter"],
        )


# =============================================================
# 4. SQLiteGradeRepository
# =============================================================


class SQLiteGradeRepository:
    """SQLite 实现的 GradeRepository。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_result(self, user_id: int, result: GradeResult) -> int:
        cur = self._conn.execute(
            """INSERT INTO grade_history
               (user_id, essay_text, topic, overall_score,
                task_response_score, coherence_score, lexical_score, grammar_score,
                result_json, task_type, error_summary_json, graded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                result.essay_text,
                result.topic,
                result.overall_score,
                result.task_response.score,
                result.coherence.score,
                result.lexical_resource.score,
                result.grammar.score,
                result.model_dump_json(),
                result.task_type,
                json.dumps(result.error_summary, ensure_ascii=False),
                result.graded_at or datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self._conn.commit()
        return cur.lastrowid or 0

    def get_history(
        self,
        user_id: int,
        limit: int = 20,
        task_type: Optional[str] = None,
    ) -> list[GradeResult]:
        if task_type:
            rows = self._conn.execute(
                """SELECT result_json FROM grade_history
                   WHERE user_id = ? AND task_type = ?
                   ORDER BY id DESC LIMIT ?""",
                (user_id, task_type, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT result_json FROM grade_history
                   WHERE user_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        results = []
        for row in rows:
            try:
                data = json.loads(row["result_json"])
                results.append(GradeResult(**data))
            except (json.JSONDecodeError, Exception):
                continue
        return results

    def get_average_score(self, user_id: int) -> float:
        row = self._conn.execute(
            """SELECT AVG(overall_score) as avg_score FROM grade_history
               WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        return row["avg_score"] or 0.0

    def get_error_trend(self, user_id: int, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            """SELECT graded_at, overall_score, error_summary_json
               FROM grade_history
               WHERE user_id = ?
               ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        result = []
        for row in reversed(rows):
            try:
                summary = json.loads(row["error_summary_json"])
            except (json.JSONDecodeError, TypeError):
                summary = {}
            result.append({
                "graded_at": row["graded_at"],
                "overall_score": row["overall_score"],
                "error_summary": summary,
            })
        return result


# =============================================================
# 5. SQLiteVocabCacheRepository
# =============================================================


class SQLiteVocabCacheRepository:
    """SQLite 实现的 VocabCacheRepository（缓存层不带 user_id）。"""

    def __init__(self, cache_path: Path) -> None:
        self._cache_path = cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(cache_path))
        self._conn.row_factory = sqlite3.Row
        # 初始化 schema
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def get_cached(self, word: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM vocab_cache WHERE word = ?", (word,)
        ).fetchone()
        if row is None:
            return None
        return {
            "word": row["word"],
            "phonetic": row["phonetic"],
            "meaning": row["meaning"],
            "pos": row["pos"],
            "band": row["band"],
            "topic": row["topic"],
            "example": row["example"],
            "example_cn": row["example_cn"],
            "collocations": json.loads(row["collocations"]) if row["collocations"] else [],
            "synonyms": json.loads(row["synonyms"]) if row["synonyms"] else [],
            "etymology": row["etymology"],
        }

    def put_cached(
        self,
        word: str,
        band: int,
        topic: str,
        payload: dict,
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO vocab_cache
               (word, phonetic, meaning, pos, band, topic, example, example_cn,
                collocations, synonyms, etymology)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                word,
                payload.get("phonetic", ""),
                payload.get("meaning", ""),
                payload.get("pos", ""),
                band,
                topic,
                payload.get("example", ""),
                payload.get("example_cn", ""),
                json.dumps(payload.get("collocations", []), ensure_ascii=False),
                json.dumps(payload.get("synonyms", []), ensure_ascii=False),
                payload.get("etymology", ""),
            ),
        )
        self._conn.commit()

    def get_mtime(self, key: str) -> str:
        row = self._conn.execute(
            "SELECT value FROM cache_meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else ""

    def set_mtime(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache_meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def clear_cache(self) -> None:
        self._conn.execute("DELETE FROM vocab_cache")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# =============================================================
# 6. SQLiteUserRepository（单机模式 no-op）
# =============================================================


class SQLiteUserRepository:
    """单机模式下的 UserRepository（no-op，固定 user_id=1）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_or_create(self, username: str) -> int:
        """单机模式忽略 username，固定返回 1。"""
        return 1

    def get_by_id(self, user_id: int) -> Optional[dict]:
        """单机模式固定返回当前用户（user_id=1）。"""
        if user_id == 1:
            return {
                "id": 1,
                "username": "local",
                "created_at": "1970-01-01T00:00:00",
                "last_login_at": None,
            }
        return None

    def update_last_login(self, user_id: int) -> None:
        """单机模式无操作。"""
        pass

    def list_users(self) -> list[dict]:
        """单机模式只有 1 个用户。"""
        return [self.get_by_id(1)]  # type: ignore[list-item]

    def ensure_system_categories(self, user_id: int) -> None:
        """单机模式下由 PersonalVocabService 自动保证；这里 no-op。"""
        pass


# =============================================================
# 7. SQLiteRepositoryContainer
# =============================================================


class SQLiteRepositoryContainer:
    """6 个 SQLite Repository 的容器。"""

    def __init__(
        self,
        db_path: Path,
        cache_path: Optional[Path] = None,
    ) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False 使连接可跨 FastAPI worker 线程复用
        # (FastAPI 同步路由在线程池中执行，与 lifespan 所在线程不同)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL 模式允许多读一写并发，避免同进程内"短事务被前一个长事务锁住"
        # 报 "attempt to write a readonly database" 的误报。
        # 在 in-memory db（"::memory::"）上 WAL 不会生效，try 即可。
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        # 1) 先做迁移：旧表补齐 user_id / source / task_type 等列
        #    必须在 CREATE INDEX 之前，否则旧表会缺列导致索引创建失败
        _migrate_legacy_schema(self._conn)
        # 2) 再建表（IF NOT EXISTS 幂等）
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

        self.learning = SQLiteLearningRepository(self._conn)
        self.personal_vocab = SQLitePersonalVocabRepository(self._conn)
        self.exam = SQLiteExamRepository(self._conn)
        self.grade = SQLiteGradeRepository(self._conn)
        self.user = SQLiteUserRepository(self._conn)

        if cache_path is None:
            cache_path = get_app_dir() / "vocab_cache.db"
        self.vocab_cache = SQLiteVocabCacheRepository(cache_path)

    def close(self) -> None:
        self._conn.close()
        self.vocab_cache.close()


# =============================================================
# 工厂函数（向后兼容）
# =============================================================


def create_sqlite_repositories(
    db_path: Optional[Path] = None,
    cache_path: Optional[Path] = None,
) -> SQLiteRepositoryContainer:
    """创建 SQLiteRepositoryContainer（W2 阶段便捷函数）。"""
    if db_path is None:
        db_path = get_db_path()
    return SQLiteRepositoryContainer(db_path=db_path, cache_path=cache_path)


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
