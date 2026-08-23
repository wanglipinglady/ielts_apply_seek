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
    Article,
    ArticleWord,
    ExamReport,
    ExamSession,
    FocusSession,
    GradeResult,
    LearningRecord,
    PersonalWord,
    TypingRecord,
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
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced',
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
    sync_status TEXT NOT NULL DEFAULT 'synced',
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
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced',
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
    band_breakdown TEXT,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
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
    graded_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_gh_user_graded
    ON grade_history(user_id, graded_at DESC);

CREATE TABLE IF NOT EXISTS typing_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    mode TEXT NOT NULL DEFAULT 'words',
    prompt_text TEXT NOT NULL,
    typed_text TEXT DEFAULT '',
    duration_sec INTEGER NOT NULL DEFAULT 0,
    wpm REAL NOT NULL DEFAULT 0,
    accuracy REAL NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    total_chars INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 1,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_th_user_created
    ON typing_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_th_user_mode
    ON typing_history(user_id, mode);

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

-- v3：统一用户表（CLI + Web 共享）
-- email/password_hash 可空（CLI 用户没邮箱、没密码）
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE,
    email TEXT COLLATE NOCASE,
    password_hash TEXT,
    display_name TEXT,
    created_at TEXT NOT NULL,
    last_login_at TEXT,
    UNIQUE (username COLLATE NOCASE),
    UNIQUE (email COLLATE NOCASE)
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email COLLATE NOCASE);

-- 文章翻译记录表（保存用户翻译过的文章 + 生词分析结果）
-- diff_words_json：ArticleWord 列表的 JSON 字符串
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    title TEXT DEFAULT '',
    source_text TEXT NOT NULL,
    translation TEXT DEFAULT '',
    word_count INTEGER DEFAULT 0,
    diff_words_json TEXT DEFAULT '[]',
    translation_source TEXT DEFAULT 'llm',
    analysis_source TEXT DEFAULT 'fallback',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_articles_user_created
    ON articles(user_id, created_at DESC);

-- v3.6：focus_sessions 番茄钟专注会话记录
CREATE TABLE IF NOT EXISTS focus_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    activity TEXT NOT NULL DEFAULT 'other',  -- vocab/writing/exam/typing/reading/other
    planned_sec INTEGER NOT NULL DEFAULT 1500,   -- 计划时长，秒（25 min = 1500）
    duration_sec INTEGER NOT NULL DEFAULT 0,     -- 实际专注时长（允许 < planned_sec）
    interrupted INTEGER NOT NULL DEFAULT 0,      -- 0=正常完成, 1=中途放弃
    note TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_fs_user_started
    ON focus_sessions(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_fs_user_activity
    ON focus_sessions(user_id, activity);

-- v3：同步元数据（单行表，记录上次同步时间和状态）
CREATE TABLE IF NOT EXISTS sync_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_pull_at TEXT,           -- MySQL → 本地，最近一次成功时间
    last_push_at TEXT,           -- 本地 → MySQL，最近一次成功时间
    last_error TEXT,
    last_error_at TEXT
);
INSERT OR IGNORE INTO sync_meta (id, last_pull_at, last_push_at)
    VALUES (1, NULL, NULL);

-- v3.7：口语对练历史记录（PRD phase-8-speaking-practice）
-- 每条记录 = 一次完整的「抽题 → 录音 → 转写 → 评分 → 错词回收」流程
-- audio_path 本地路径(可能因 7 天清理被置 NULL);webm 原始文件存磁盘
-- 所有 LLM 输出字段均为 JSON 字符串(SQLite 没有 JSON 列,文本存储即可)
CREATE TABLE IF NOT EXISTS speaking_practice_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
    part INTEGER NOT NULL,
    topic_id INTEGER,
    topic_name TEXT DEFAULT '',
    question TEXT NOT NULL,
    audio_path TEXT,
    audio_duration_sec REAL DEFAULT 0,
    audio_mime TEXT DEFAULT 'audio/webm',
    transcript TEXT DEFAULT '',
    transcript_tokens TEXT,        -- JSON: [{word, t0_ms, t1_ms, prob}]
    llm_scores TEXT,               -- JSON: {fluency, lexical, grammar, pronunciation, overall_band}
    llm_word_errors TEXT,          -- JSON: [{original, correction, context}]
    llm_grammar_errors TEXT,       -- JSON: [{original, correction, rule}]
    llm_highlights TEXT,           -- JSON: [str]
    llm_suggestions TEXT,          -- JSON: [str]
    whisper_model TEXT DEFAULT 'small.en',
    used_core_ml INTEGER DEFAULT 1,
    score_fallback INTEGER DEFAULT 0,  -- LLM mock 兜底时 = 1
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_spr_user_created
    ON speaking_practice_records(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_spr_session
    ON speaking_practice_records(session_id);
CREATE INDEX IF NOT EXISTS idx_spr_user_part
    ON speaking_practice_records(user_id, part);

-- v3.7 P2 真·听力题库(LLM 出题 + TTS 合成音频)
CREATE TABLE IF NOT EXISTS listening_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section INTEGER NOT NULL,            -- 1 / 2 / 3 / 4
    set_id INTEGER NOT NULL,             -- 套号 1-based
    qid INTEGER NOT NULL,                -- 套内题号 1-based
    scenario TEXT NOT NULL DEFAULT '',
    question_type TEXT NOT NULL,         -- multiple_choice / form_completion / matching
    stem TEXT NOT NULL,
    options_json TEXT,                   -- JSON 数组,填空题为 NULL
    answer TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    transcript TEXT NOT NULL DEFAULT '',
    audio_path TEXT,                     -- 相对 ~/.ielts-buddy/listening/
    audio_generated_at TEXT,             -- ISO 时间戳
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced',
    UNIQUE(section, set_id, qid)
);
CREATE INDEX IF NOT EXISTS idx_lq_section_set
    ON listening_questions(section, set_id);

CREATE TABLE IF NOT EXISTS listening_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    user_answer TEXT NOT NULL,
    is_correct INTEGER NOT NULL DEFAULT 0,
    duration_sec REAL DEFAULT 0,
    played_count INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_la_user_created
    ON listening_attempts(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_la_user_q
    ON listening_attempts(user_id, question_id);

-- v3.8 备考资源广场(v3.8 P3 新增)
CREATE TABLE IF NOT EXISTS prep_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    bv_id TEXT NOT NULL,
    url TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_uid INTEGER,
    uploader_name TEXT NOT NULL DEFAULT '',
    uploader_uid INTEGER,
    skill TEXT NOT NULL,                 -- listening | reading | speaking | writing | general
    video_type TEXT NOT NULL,            -- methodology | planning | tips | pitfalls | mock | vocab
    level TEXT NOT NULL,                  -- 0-5 | 5-6 | 6.5-7 | 7+
    method_summary TEXT NOT NULL,
    source_status TEXT NOT NULL DEFAULT 'verified_repost',  -- official | institution | verified_repost | unverified_repost
    publish_date TEXT,
    duration_sec INTEGER DEFAULT 0,
    outdated_risk TEXT NOT NULL DEFAULT 'low',  -- low | medium | high
    format_compatible TEXT NOT NULL DEFAULT 'computer',  -- computer | paper_based | both
    computer_delivery_only INTEGER NOT NULL DEFAULT 1,
    is_featured INTEGER NOT NULL DEFAULT 0,
    recommend_score REAL NOT NULL DEFAULT 0.0,
    sort_order INTEGER NOT NULL DEFAULT 100,
    related_action_url TEXT,
    related_action_label TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced',
    UNIQUE(bv_id)
);
CREATE INDEX IF NOT EXISTS idx_pr_skill ON prep_resources(skill);
CREATE INDEX IF NOT EXISTS idx_pr_score ON prep_resources(recommend_score DESC);
CREATE INDEX IF NOT EXISTS idx_pr_author ON prep_resources(author_name);

-- v3.8 Reading 真题题库(v3.8 P3 新增)
CREATE TABLE IF NOT EXISTS reading_passages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section TEXT NOT NULL,                -- easy | medium | hard | academic
    set_id INTEGER NOT NULL,
    qid INTEGER NOT NULL,
    passage_number INTEGER NOT NULL,       -- 1 / 2 / 3
    title TEXT NOT NULL,
    topic TEXT NOT NULL DEFAULT '',
    question_type TEXT NOT NULL,           -- tfng | multiple_choice | matching | summary | sentence_completion
    word_count INTEGER NOT NULL DEFAULT 0,
    passage_text TEXT NOT NULL,
    stem TEXT NOT NULL,
    options_json TEXT,
    answer TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    source_line INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced',
    UNIQUE(section, set_id, qid)
);
CREATE INDEX IF NOT EXISTS idx_rp_section_set ON reading_passages(section, set_id);

CREATE TABLE IF NOT EXISTS reading_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    user_answer TEXT NOT NULL,
    is_correct INTEGER NOT NULL DEFAULT 0,
    duration_sec REAL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'synced'
);
CREATE INDEX IF NOT EXISTS idx_rat_user_created
    ON reading_attempts(user_id, created_at DESC);
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
        # v3：sync 字段
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ("sync_status", "TEXT NOT NULL DEFAULT 'synced'"),
    ],
    "personal_vocab": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
        # v3：sync 字段（personal_vocab.updated_at 早就有；sync_status 新增）
        ("sync_status", "TEXT NOT NULL DEFAULT 'synced'"),
    ],
    "vocab_categories": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ("sync_status", "TEXT NOT NULL DEFAULT 'synced'"),
    ],
    "exam_sessions": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ("sync_status", "TEXT NOT NULL DEFAULT 'synced'"),
    ],
    "grade_history": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ("sync_status", "TEXT NOT NULL DEFAULT 'synced'"),
    ],
    # v3.6：typing_history 机考打字记录
    "typing_history": [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ("sync_status", "TEXT NOT NULL DEFAULT 'synced'"),
    ],
    # error_summary_json / task_type 旧版迁移（grading_service 原逻辑）
    "grade_history_legacy": [
        ("task_type", "TEXT DEFAULT 'task2'"),
        ("error_summary_json", "TEXT DEFAULT '{}'"),
    ],
    # v3：articles 加 updated_at / sync_status
    "articles": [
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ("sync_status", "TEXT NOT NULL DEFAULT 'synced'"),
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

    # ---- 错词本 (v3.6 新增) ----
    def get_wrong_words(
        self,
        user_id: int,
        min_wrong: int = 1,
        days: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """按 wrong_count DESC 返回错词列表(原始 dict,含 word/word_data)。

        返回 dict 而非 LearningRecord 是因为前端需要 word 字符串本身,
        而 LearningRecord 仅暴露 word_id。web router 层直接序列化。
        """
        params: list[Any] = [user_id, min_wrong]
        sql = """SELECT * FROM learning_records
                 WHERE user_id = ? AND wrong_count >= ?"""
        if days is not None:
            since = (date.today() - timedelta(days=days - 1)).isoformat()
            sql += " AND DATE(last_reviewed) >= ?"
            params.append(since)
        sql += """ ORDER BY wrong_count DESC, last_reviewed DESC
                   LIMIT ?"""
        params.append(limit)
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def reset_mistake(self, user_id: int, word: str) -> bool:
        """重置错词状态:wrong_count=0, memory_level=6(标记已掌握)。"""
        cur = self._conn.execute(
            """UPDATE learning_records
               SET wrong_count = 0, memory_level = 6,
                   last_reviewed = ?
             WHERE user_id = ? AND word = ?""",
            (datetime.now().isoformat(timespec="seconds"), user_id, word),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_mistake_stats(self, user_id: int) -> dict:
        """错词本聚合统计。"""
        try:
            row = self._conn.execute(
                """SELECT
                       COUNT(CASE WHEN wrong_count > 0 THEN 1 END) AS distinct_words,
                       COALESCE(SUM(wrong_count), 0) AS total_wrong_count
                   FROM learning_records WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
            since_7d = (date.today() - timedelta(days=6)).isoformat()
            row7 = self._conn.execute(
                """SELECT COUNT(*) AS cnt
                   FROM learning_records
                   WHERE user_id = ?
                     AND wrong_count > 0
                     AND DATE(last_reviewed) >= ?""",
                (user_id, since_7d),
            ).fetchone()
            top_rows = self._conn.execute(
                """SELECT word, wrong_count, last_reviewed
                   FROM learning_records
                   WHERE user_id = ? AND wrong_count > 0
                   ORDER BY wrong_count DESC, last_reviewed DESC
                   LIMIT 5""",
                (user_id,),
            ).fetchall()
            return {
                "distinct_words": int(row["distinct_words"] or 0),
                "total_wrong_count": int(row["total_wrong_count"] or 0),
                "last_7d_wrong": int(row7["cnt"] or 0),
                "top_offenders": [
                    {
                        "word": r["word"],
                        "wrong_count": int(r["wrong_count"]),
                        "last_reviewed": r["last_reviewed"],
                    }
                    for r in top_rows
                ],
            }
        except Exception:
            print("[sqlite] get_mistake_stats failed")
            return {
                "distinct_words": 0,
                "total_wrong_count": 0,
                "last_7d_wrong": 0,
                "top_offenders": [],
            }

    def get_learned_words(self, user_id: int) -> list[str]:
        """返回用户学过的所有词（任意时间），用于"挑没学过的词"。
        注意：与 get_learned_words_today 不同 —— 后者只看今天的。
        """
        rows = self._conn.execute(
            "SELECT word FROM learning_records WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return [row["word"] for row in rows]

    # ---- 口语对练错词回收 (v3.7 P1 新增) ----
    def record_speaking_error(
        self,
        user_id: int,
        word: str,
        source: str = "speaking",
    ) -> bool:
        """对学习记录做"口语来源的错误信号"。
        不推进 memory_level，仅 wrong_count +1。
        若用户没学过该词，新建一条 learning_records 行
        (wrong_count=1, correct_count=0, memory_level=0, last_reviewed=now)。
        """
        word_clean = (word or "").strip().lower()
        if not word_clean:
            return False
        now_iso = datetime.now().isoformat(timespec="seconds")
        try:
            existing = self._conn.execute(
                "SELECT id, wrong_count FROM learning_records "
                "WHERE user_id = ? AND word = ?",
                (user_id, word_clean),
            ).fetchone()
            if existing is None:
                # 最小 word_data 占位（前端不依赖此字段，原始 vocab 数据由 personal_vocab 维护）
                placeholder_data = json.dumps(
                    {"word": word_clean, "meaning": "", "band": 5},
                    ensure_ascii=False,
                )
                self._conn.execute(
                    """INSERT INTO learning_records
                       (user_id, word, word_data, memory_level, next_review,
                        learn_count, correct_count, wrong_count,
                        first_learned, last_reviewed, source)
                       VALUES (?, ?, ?, 0, ?, 0, 0, 1, ?, ?, ?)""",
                    (user_id, word_clean, placeholder_data,
                     date.today().isoformat(),
                     now_iso, now_iso, source),
                )
            else:
                self._conn.execute(
                    """UPDATE learning_records
                       SET wrong_count = wrong_count + 1,
                           last_reviewed = ?
                     WHERE user_id = ? AND word = ?""",
                    (now_iso, user_id, word_clean),
                )
            self._conn.commit()
            return True
        except Exception as exc:
            print(f"[sqlite] record_speaking_error failed: {exc}", file=__import__("sys").stderr)
            return False


# =============================================================
# SQLiteSpeakingPracticeRepository (v3.7 P1 新增)
# =============================================================


class SQLiteSpeakingPracticeRepository:
    """SQLite 实现的 SpeakingPracticeRepository。
    所有方法都带 user_id 隔离。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---- 写入 ----
    def create_practice_record(
        self,
        user_id: int,
        session_id: str,
        part: int,
        topic_id: Optional[int],
        topic_name: str,
        question: str,
        audio_path: Optional[str],
        audio_duration_sec: float,
        audio_mime: str = "audio/webm",
    ) -> int:
        """创建一条记录。transcript/scores 等字段留空，后续 update 填。"""
        now_iso = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            """INSERT INTO speaking_practice_records
               (user_id, session_id, part, topic_id, topic_name,
                question, audio_path, audio_duration_sec, audio_mime,
                created_at, updated_at, sync_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced')""",
            (user_id, session_id, int(part), topic_id, topic_name or "",
             question, audio_path, float(audio_duration_sec), audio_mime,
             now_iso, now_iso),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def update_practice_transcript(
        self,
        user_id: int,
        session_id: str,
        transcript: str,
        transcript_tokens: Optional[list[dict]] = None,
        whisper_model: str = "small.en",
        used_core_ml: bool = True,
    ) -> bool:
        tokens_json = json.dumps(
            transcript_tokens or [], ensure_ascii=False
        )
        cur = self._conn.execute(
            """UPDATE speaking_practice_records
               SET transcript = ?, transcript_tokens = ?,
                   whisper_model = ?, used_core_ml = ?,
                   updated_at = ?
             WHERE user_id = ? AND session_id = ?""",
            (transcript, tokens_json, whisper_model,
             1 if used_core_ml else 0,
             datetime.now().isoformat(timespec="seconds"),
             user_id, session_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_practice_score(
        self,
        user_id: int,
        session_id: str,
        scores: dict,
        word_errors: list[dict],
        grammar_errors: list[dict],
        highlights: list[str],
        suggestions: list[str],
        score_fallback: bool = False,
    ) -> bool:
        cur = self._conn.execute(
            """UPDATE speaking_practice_records
               SET llm_scores = ?, llm_word_errors = ?,
                   llm_grammar_errors = ?, llm_highlights = ?,
                   llm_suggestions = ?, score_fallback = ?,
                   updated_at = ?
             WHERE user_id = ? AND session_id = ?""",
            (json.dumps(scores, ensure_ascii=False),
             json.dumps(word_errors, ensure_ascii=False),
             json.dumps(grammar_errors, ensure_ascii=False),
             json.dumps(highlights, ensure_ascii=False),
             json.dumps(suggestions, ensure_ascii=False),
             1 if score_fallback else 0,
             datetime.now().isoformat(timespec="seconds"),
             user_id, session_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ---- 读取 ----
    def get_practice_record(
        self,
        user_id: int,
        record_id: int,
    ) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM speaking_practice_records "
            "WHERE user_id = ? AND id = ?",
            (user_id, record_id),
        ).fetchone()
        return dict(row) if row else None

    def get_practice_by_session(
        self,
        user_id: int,
        session_id: str,
    ) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM speaking_practice_records "
            "WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        ).fetchone()
        return dict(row) if row else None

    def list_practice_history(
        self,
        user_id: int,
        part: Optional[int] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict], int]:
        # 统计 + 分页
        if part is not None:
            total = self._conn.execute(
                "SELECT COUNT(*) AS c FROM speaking_practice_records "
                "WHERE user_id = ? AND part = ?",
                (user_id, part),
            ).fetchone()["c"]
            rows = self._conn.execute(
                """SELECT * FROM speaking_practice_records
                   WHERE user_id = ? AND part = ?
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (user_id, part, size, (page - 1) * size),
            ).fetchall()
        else:
            total = self._conn.execute(
                "SELECT COUNT(*) AS c FROM speaking_practice_records "
                "WHERE user_id = ?",
                (user_id,),
            ).fetchone()["c"]
            rows = self._conn.execute(
                """SELECT * FROM speaking_practice_records
                   WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (user_id, size, (page - 1) * size),
            ).fetchall()
        return [dict(r) for r in rows], int(total)

    # ---- 清理 ----
    def set_audio_null(self, user_id: int, session_id: str) -> bool:
        cur = self._conn.execute(
            "UPDATE speaking_practice_records SET audio_path = NULL, "
            "updated_at = ? WHERE user_id = ? AND session_id = ?",
            (datetime.now().isoformat(timespec="seconds"),
             user_id, session_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def list_expired_audio_paths(
        self,
        retention_days: int,
    ) -> list[tuple[int, str, str]]:
        """返回所有 retention_days 天前的录音记录 (user_id, session_id, audio_path)。

        Service 层据此删除文件 + 调 set_audio_null 把 DB 标记置空。
        """
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat(
            timespec="seconds"
        )
        rows = self._conn.execute(
            "SELECT user_id, session_id, audio_path "
            "FROM speaking_practice_records "
            "WHERE audio_path IS NOT NULL AND created_at < ?",
            (cutoff,),
        ).fetchall()
        return [(int(r["user_id"]), r["session_id"], r["audio_path"])
                for r in rows]

    def delete_old_records_keeping_audio_path(
        self,
        cutoff_days: int,
    ) -> int:
        """调用前通常已经 NULL 化 audio_path；本方法只删整行。"""
        cutoff = (date.today() - timedelta(days=cutoff_days)).isoformat()
        cur = self._conn.execute(
            "DELETE FROM speaking_practice_records "
            "WHERE audio_path IS NULL AND DATE(created_at) < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cur.rowcount


# =============================================================
# 1b. SQLiteListeningPracticeRepository (v3.7 P2 新增)
# =============================================================


class SQLiteListeningPracticeRepository:
    """SQLite 实现的 ListeningPracticeRepository。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---- 题库 ----
    def seed_question(
        self,
        section: int,
        set_id: int,
        qid: int,
        scenario: str,
        question_type: str,
        stem: str,
        options: Optional[list[str]],
        answer: str,
        explanation: str,
        transcript: str,
        audio_path: Optional[str] = None,
        audio_generated_at: Optional[str] = None,
    ) -> int:
        """插入或更新一道题(UNIQUE(section, set_id, qid) 兜底 upsert)。"""
        now = datetime.now().isoformat(timespec="seconds")
        opts_json = json.dumps(options, ensure_ascii=False) if options else None
        try:
            cur = self._conn.execute(
                """INSERT INTO listening_questions
                   (section, set_id, qid, scenario, question_type, stem,
                    options_json, answer, explanation, transcript,
                    audio_path, audio_generated_at,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (section, set_id, qid, scenario, question_type, stem,
                 opts_json, answer, explanation, transcript,
                 audio_path, audio_generated_at,
                 now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            # 已存在 → UPDATE
            cur = self._conn.execute(
                """UPDATE listening_questions
                   SET scenario = ?, question_type = ?, stem = ?,
                       options_json = ?, answer = ?, explanation = ?,
                       transcript = ?, updated_at = ?
                 WHERE section = ? AND set_id = ? AND qid = ?""",
                (scenario, question_type, stem,
                 opts_json, answer, explanation, transcript,
                 now, section, set_id, qid),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id FROM listening_questions "
                "WHERE section=? AND set_id=? AND qid=?",
                (section, set_id, qid),
            ).fetchone()
            return int(row["id"]) if row else -1

    def get_question(self, question_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM listening_questions WHERE id = ?",
            (question_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("options_json"):
            try:
                d["options"] = json.loads(d["options_json"])
            except Exception:
                d["options"] = []
        else:
            d["options"] = None
        return d

    def list_sections_with_counts(self) -> list[dict]:
        """返回 [{section, total_sets, total_questions}]。"""
        rows = self._conn.execute(
            """SELECT section,
                      COUNT(DISTINCT set_id) AS total_sets,
                      COUNT(*) AS total_questions
               FROM listening_questions
               GROUP BY section
               ORDER BY section"""
        ).fetchall()
        return [
            {
                "section": int(r["section"]),
                "total_sets": int(r["total_sets"]),
                "total_questions": int(r["total_questions"]),
            }
            for r in rows
        ]

    def list_sets_by_section(self, section: int) -> list[dict]:
        """返回该 Section 下每个套的元信息(题数 + 场景)。"""
        rows = self._conn.execute(
            """SELECT set_id, scenario,
                      COUNT(*) AS question_count,
                      MIN(stem) AS first_stem
               FROM listening_questions
               WHERE section = ?
               GROUP BY set_id, scenario
               ORDER BY set_id""",
            (section,),
        ).fetchall()
        return [
            {
                "set_id": int(r["set_id"]),
                "section": section,
                "scenario": r["scenario"] or "",
                "question_count": int(r["question_count"]),
                "first_stem": r["first_stem"] or "",
            }
            for r in rows
        ]

    def list_questions_by_set(self, section: int, set_id: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM listening_questions
               WHERE section = ? AND set_id = ?
               ORDER BY qid""",
            (section, set_id),
        ).fetchall()
        items = []
        for row in rows:
            d = dict(row)
            if d.get("options_json"):
                try:
                    d["options"] = json.loads(d["options_json"])
                except Exception:
                    d["options"] = []
            else:
                d["options"] = None
            items.append(d)
        return items

    def set_audio_path(
        self,
        question_id: int,
        audio_path: Optional[str],
        audio_generated_at: Optional[str],
    ) -> None:
        self._conn.execute(
            "UPDATE listening_questions "
            "SET audio_path = ?, audio_generated_at = ?, updated_at = ? "
            "WHERE id = ?",
            (audio_path, audio_generated_at,
             datetime.now().isoformat(timespec="seconds"),
             question_id),
        )
        self._conn.commit()

    def count_questions(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM listening_questions"
        ).fetchone()
        return int(row["c"])

    # ---- 答题记录 ----
    def record_attempt(
        self,
        user_id: int,
        question_id: int,
        user_answer: str,
        is_correct: bool,
        duration_sec: float = 0.0,
        played_count: int = 1,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            """INSERT INTO listening_attempts
               (user_id, question_id, user_answer, is_correct,
                duration_sec, played_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, question_id, user_answer,
             1 if is_correct else 0, duration_sec, played_count, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_user_attempts(
        self,
        user_id: int,
        page: int = 1,
        size: int = 20,
        section: Optional[int] = None,
    ) -> tuple[list[dict], int]:
        """返回 (items, total)。section 过滤会 JOIN listening_questions。"""
        where_parts = ["a.user_id = ?"]
        params: list[Any] = [user_id]
        if section is not None:
            where_parts.append("q.section = ?")
            params.append(section)
        where = " AND ".join(where_parts)

        total_row = self._conn.execute(
            f"""SELECT COUNT(*) AS c FROM listening_attempts a
                LEFT JOIN listening_questions q ON a.question_id = q.id
                WHERE {where}""",
            params,
        ).fetchone()
        total = int(total_row["c"])

        offset = (page - 1) * size
        rows = self._conn.execute(
            f"""SELECT a.*, q.section, q.set_id, q.qid, q.scenario,
                       q.stem, q.transcript, q.answer AS correct_answer,
                       q.audio_path
                FROM listening_attempts a
                LEFT JOIN listening_questions q ON a.question_id = q.id
                WHERE {where}
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT ? OFFSET ?""",
            params + [size, offset],
        ).fetchall()
        items = [dict(r) for r in rows]
        return items, total

    def get_user_stats(self, user_id: int) -> dict:
        """返回 {total_attempts, correct_count, accuracy,
        by_section: {1: {...}, 2: {...}, 3: {...}, 4: {...}}}。"""
        total_row = self._conn.execute(
            """SELECT COUNT(*) AS total_attempts,
                      SUM(is_correct) AS correct_count
               FROM listening_attempts WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        total = int(total_row["total_attempts"] or 0)
        correct = int(total_row["correct_count"] or 0)

        by_section_rows = self._conn.execute(
            """SELECT q.section,
                      COUNT(*) AS attempts,
                      SUM(a.is_correct) AS correct
               FROM listening_attempts a
               LEFT JOIN listening_questions q ON a.question_id = q.id
               WHERE a.user_id = ? AND q.section IS NOT NULL
               GROUP BY q.section
               ORDER BY q.section""",
            (user_id,),
        ).fetchall()
        by_section = {
            int(r["section"]): {
                "attempts": int(r["attempts"]),
                "correct": int(r["correct"] or 0),
                "accuracy": (
                    round((int(r["correct"] or 0) / int(r["attempts"])) * 100, 1)
                    if int(r["attempts"]) > 0 else 0.0
                ),
            }
            for r in by_section_rows
        }

        return {
            "total_attempts": total,
            "correct_count": correct,
            "accuracy": round(correct / total * 100, 1) if total > 0 else 0.0,
            "by_section": by_section,
        }

    # ---- 清理 ----
    def list_expired_audio_paths(
        self,
        retention_days: int,
    ) -> list[tuple[int, str]]:
        """返回所有 retention_days 天前生成的音频(question_id, audio_path)。

        Service 层据此删除文件 + 调 set_audio_path 标 NULL 触发重新合成。
        """
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat(
            timespec="seconds"
        )
        rows = self._conn.execute(
            "SELECT id, audio_path FROM listening_questions "
            "WHERE audio_path IS NOT NULL "
            "AND audio_generated_at IS NOT NULL "
            "AND audio_generated_at < ?",
            (cutoff,),
        ).fetchall()
        return [(int(r["id"]), r["audio_path"]) for r in rows]


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
                    example, example_cn, note, source, created_at,
                    updated_at, sync_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_upload')""",
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
        updates["sync_status"] = "pending_upload"

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
# 4.6 SQLiteTypingRepository
# =============================================================


class SQLiteTypingRepository:
    """SQLite 实现的 TypingRepository。

    持久化机考打字练习的成绩：
    - save_record：插入一行（含 result_json 完整 dump）
    - get_history：按 user_id 列最近 N 条
    - get_history_count：user 总练习次数
    - get_average_wpm / get_average_accuracy：聚合统计
    - get_max_wpm：历史最佳
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_record(self, user_id: int, record: TypingRecord) -> int:
        cur = self._conn.execute(
            """INSERT INTO typing_history
               (user_id, mode, prompt_text, typed_text, duration_sec,
                wpm, accuracy, error_count, total_chars, completed,
                result_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                record.mode,
                record.prompt_text,
                record.typed_text,
                record.duration_sec,
                float(record.wpm),
                float(record.accuracy),
                record.error_count,
                record.total_chars,
                1 if record.completed else 0,
                record.model_dump_json(),
                record.created_at
                or datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self._conn.commit()
        return cur.lastrowid or 0

    def get_history(
        self,
        user_id: int,
        limit: int = 20,
        mode: Optional[str] = None,
    ) -> list[TypingRecord]:
        if mode:
            rows = self._conn.execute(
                """SELECT result_json FROM typing_history
                   WHERE user_id = ? AND mode = ?
                   ORDER BY id DESC LIMIT ?""",
                (user_id, mode, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT result_json FROM typing_history
                   WHERE user_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        results: list[TypingRecord] = []
        for row in rows:
            try:
                data = json.loads(row["result_json"])
                results.append(TypingRecord(**data))
            except (json.JSONDecodeError, Exception):
                continue
        return results

    def get_history_count(self, user_id: int, mode: Optional[str] = None) -> int:
        if mode:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM typing_history WHERE user_id = ? AND mode = ?",
                (user_id, mode),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM typing_history WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["cnt"] or 0)

    def get_average_wpm(self, user_id: int, mode: Optional[str] = None) -> float:
        if mode:
            row = self._conn.execute(
                "SELECT AVG(wpm) AS avg_wpm FROM typing_history WHERE user_id = ? AND mode = ?",
                (user_id, mode),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT AVG(wpm) AS avg_wpm FROM typing_history WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return float(row["avg_wpm"] or 0.0)

    def get_average_accuracy(self, user_id: int, mode: Optional[str] = None) -> float:
        if mode:
            row = self._conn.execute(
                "SELECT AVG(accuracy) AS avg_acc FROM typing_history WHERE user_id = ? AND mode = ?",
                (user_id, mode),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT AVG(accuracy) AS avg_acc FROM typing_history WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return float(row["avg_acc"] or 0.0)

    def get_max_wpm(self, user_id: int, mode: Optional[str] = None) -> float:
        if mode:
            row = self._conn.execute(
                "SELECT MAX(wpm) AS max_wpm FROM typing_history WHERE user_id = ? AND mode = ?",
                (user_id, mode),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT MAX(wpm) AS max_wpm FROM typing_history WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return float(row["max_wpm"] or 0.0)


# =============================================================
# 4.6 SQLiteFocusSessionRepository (v3.6 番茄钟)
# =============================================================


class SQLiteFocusSessionRepository:
    """SQLite 实现的 FocusSession 仓库（v3.6 番茄钟新增）。

    持久化专注会话：
    - start_session：插入一行（duration_sec 默认 0，interrupted=0）
    - complete_session：结束时 UPDATE duration_sec / interrupted / note / ended_at
    - get_history：按 user_id 取最近 N 条
    - get_today_summary：今日累计（番茄数 + 总专注秒数）
    - get_total_count：用户累计番茄数
    """

    VALID_ACTIVITIES = ("vocab", "writing", "exam", "typing", "reading", "other")

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def _normalize_activity(cls, activity: str) -> str:
        return activity if activity in cls.VALID_ACTIVITIES else "other"

    def start_session(self, user_id: int, session: FocusSession) -> int:
        """开始一次专注会话：插入一行，duration_sec=0, interrupted=0。"""
        now = datetime.now().isoformat(timespec="seconds")
        activity = self._normalize_activity(session.activity)
        cur = self._conn.execute(
            """INSERT INTO focus_sessions
               (user_id, activity, planned_sec, duration_sec, interrupted,
                note, started_at, ended_at, created_at)
               VALUES (?, ?, ?, 0, 0, ?, ?, '', ?)""",
            (
                user_id,
                activity,
                session.planned_sec,
                session.note or "",
                session.started_at or now,
                now,
            ),
        )
        self._conn.commit()
        return cur.lastrowid or 0

    def complete_session(
        self,
        user_id: int,
        session_id: int,
        duration_sec: int,
        interrupted: bool,
        note: Optional[str],
    ) -> bool:
        """结束一次会话：写入 duration_sec / interrupted / note / ended_at。

        返回 True=成功更新,False=未找到对应行。
        """
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            """UPDATE focus_sessions
               SET duration_sec = ?, interrupted = ?, note = ?, ended_at = ?,
                   updated_at = ?, sync_status = 'pending_upload'
               WHERE id = ? AND user_id = ?""",
            (
                max(0, int(duration_sec)),
                1 if interrupted else 0,
                note or "",
                now,
                now,
                session_id,
                user_id,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_history(
        self, user_id: int, limit: int = 20
    ) -> list[FocusSession]:
        """按 started_at DESC 取最近 N 条。"""
        rows = self._conn.execute(
            """SELECT id, user_id, activity, planned_sec, duration_sec,
                      interrupted, note, started_at, ended_at, created_at
               FROM focus_sessions
               WHERE user_id = ?
               ORDER BY started_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        results: list[FocusSession] = []
        for row in rows:
            results.append(FocusSession(
                id=int(row["id"]),
                user_id=int(row["user_id"]),
                activity=row["activity"] or "other",
                planned_sec=int(row["planned_sec"] or 0),
                duration_sec=int(row["duration_sec"] or 0),
                interrupted=bool(row["interrupted"]),
                note=row["note"] or "",
                started_at=row["started_at"] or "",
                ended_at=row["ended_at"] or "",
                created_at=row["created_at"] or "",
            ))
        return results

    def get_today_summary(self, user_id: int) -> dict[str, Any]:
        """今日累计: 番茄数 + 总专注秒数 + 完成数 + 放弃数。

        按本地日期分界（ISO 日期前缀 YYYY-MM-DD）。
        """
        today = datetime.now().date().isoformat()
        row = self._conn.execute(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(duration_sec), 0) AS total_sec,
                      SUM(CASE WHEN interrupted = 0 AND duration_sec >= planned_sec * 0.8
                               THEN 1 ELSE 0 END) AS completed,
                      SUM(CASE WHEN interrupted = 1
                               THEN 1 ELSE 0 END) AS abandoned
               FROM focus_sessions
               WHERE user_id = ? AND substr(started_at, 1, 10) = ?""",
            (user_id, today),
        ).fetchone()
        return {
            "date": today,
            "total": int(row["total"] or 0),
            "total_sec": int(row["total_sec"] or 0),
            "completed": int(row["completed"] or 0),
            "abandoned": int(row["abandoned"] or 0),
        }

    def get_total_count(self, user_id: int) -> int:
        """用户累计番茄数（不区分今日）。"""
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM focus_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row["cnt"] or 0)


# =============================================================
# 4.5 SQLiteArticleRepository
# =============================================================


def _row_to_article(row: sqlite3.Row) -> Article:
    return Article(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"] or "",
        source_text=row["source_text"],
        translation=row["translation"] or "",
        word_count=row["word_count"] or 0,
        diff_words_json=row["diff_words_json"] or "[]",
        translation_source=row["translation_source"] or "llm",
        analysis_source=row["analysis_source"] or "fallback",
        created_at=row["created_at"],
    )


class SQLiteArticleRepository:
    """SQLite 实现的 Article 仓库。

    用于文章翻译+生词分析功能的持久化：
    - 原文 + 中文翻译 + 生词分析结果一起存
    - 支持按用户列出历史、按 ID 查询完整记录
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: int,
        title: str,
        source_text: str,
        translation: str,
        word_count: int,
        diff_words: list[ArticleWord],
        translation_source: str = "llm",
        analysis_source: str = "fallback",
    ) -> int:
        """插入一篇文章，返回新 id。"""
        now = datetime.now().isoformat(timespec="seconds")
        diff_words_json = json.dumps(
            [w.model_dump() for w in diff_words], ensure_ascii=False
        )
        cur = self._conn.execute(
            """INSERT INTO articles
               (user_id, title, source_text, translation, word_count,
                diff_words_json, translation_source, analysis_source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, title, source_text, translation, word_count,
                diff_words_json, translation_source, analysis_source, now,
            ),
        )
        self._conn.commit()
        return cur.lastrowid or 0

    def get_by_id(self, user_id: int, article_id: int) -> Optional[Article]:
        """按 id 查询完整记录（带 user_id 过滤，避免越权）。"""
        row = self._conn.execute(
            "SELECT * FROM articles WHERE id = ? AND user_id = ?",
            (article_id, user_id),
        ).fetchone()
        return _row_to_article(row) if row else None

    def list_recent(
        self,
        user_id: int,
        limit: int = 30,
    ) -> list[Article]:
        """最近的文章列表（按时间倒序）。"""
        rows = self._conn.execute(
            """SELECT * FROM articles WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [_row_to_article(r) for r in rows]

    def count(self, user_id: int) -> int:
        """用户的文章总数。"""
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM articles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["cnt"]

    def delete(self, user_id: int, article_id: int) -> bool:
        """删除一篇文章。"""
        cur = self._conn.execute(
            "DELETE FROM articles WHERE id = ? AND user_id = ?",
            (article_id, user_id),
        )
        self._conn.commit()
        return cur.rowcount > 0


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
# 6b. SQLitePrepResourceRepository (v3.8 P3 新增 - 备考资源广场)
# =============================================================


class SQLitePrepResourceRepository:
    """SQLite 实现的 PrepResourceRepository。

    跨用户共享的 B 站资源元数据;不在 SYNC_TABLES。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def seed_resource(
        self,
        title: str,
        bv_id: str,
        url: str,
        author_name: str,
        skill: str,
        video_type: str,
        level: str,
        method_summary: str,
        source_status: str,
        author_uid: Optional[int] = None,
        uploader_name: Optional[str] = None,
        uploader_uid: Optional[int] = None,
        publish_date: Optional[str] = None,
        duration_sec: int = 0,
        outdated_risk: str = "low",
        format_compatible: str = "computer",
        computer_delivery_only: bool = True,
        is_featured: bool = False,
        recommend_score: float = 0.0,
        sort_order: int = 100,
        related_action_url: Optional[str] = None,
        related_action_label: Optional[str] = None,
    ) -> int:
        """插入或更新一条资源(UNIQUE bv_id 兜底 upsert)。"""
        now = datetime.now().isoformat(timespec="seconds")
        try:
            cur = self._conn.execute(
                """INSERT INTO prep_resources
                   (title, bv_id, url, author_name, author_uid,
                    uploader_name, uploader_uid, skill, video_type, level,
                    method_summary, source_status, publish_date,
                    duration_sec, outdated_risk, format_compatible,
                    computer_delivery_only, is_featured, recommend_score,
                    sort_order, related_action_url, related_action_label,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?)""",
                (title, bv_id, url, author_name, author_uid,
                 uploader_name or "", uploader_uid, skill, video_type, level,
                 method_summary, source_status, publish_date,
                 duration_sec, outdated_risk, format_compatible,
                 1 if computer_delivery_only else 0,
                 1 if is_featured else 0, float(recommend_score),
                 int(sort_order), related_action_url, related_action_label,
                 now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            # 已存在 → UPDATE
            self._conn.execute(
                """UPDATE prep_resources SET
                     title = ?, url = ?, author_name = ?, author_uid = ?,
                     uploader_name = ?, uploader_uid = ?, skill = ?,
                     video_type = ?, level = ?, method_summary = ?,
                     source_status = ?, publish_date = ?,
                     duration_sec = ?, outdated_risk = ?, format_compatible = ?,
                     computer_delivery_only = ?, is_featured = ?,
                     recommend_score = ?, sort_order = ?,
                     related_action_url = ?, related_action_label = ?,
                     updated_at = ?
                   WHERE bv_id = ?""",
                (title, url, author_name, author_uid,
                 uploader_name or "", uploader_uid, skill, video_type, level,
                 method_summary, source_status, publish_date,
                 duration_sec, outdated_risk, format_compatible,
                 1 if computer_delivery_only else 0,
                 1 if is_featured else 0, float(recommend_score),
                 int(sort_order), related_action_url, related_action_label,
                 now, bv_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id FROM prep_resources WHERE bv_id = ?",
                (bv_id,),
            ).fetchone()
            return int(row["id"]) if row else -1

    def get_resource(self, resource_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM prep_resources WHERE id = ?",
            (int(resource_id),),
        ).fetchone()
        return dict(row) if row else None

    def get_resource_by_bv(self, bv_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM prep_resources WHERE bv_id = ?",
            (bv_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_resources(
        self,
        skill: Optional[str] = None,
        level: Optional[str] = None,
        source_status: Optional[str] = None,
        is_featured: Optional[bool] = None,
        sort_by: str = "recommend_score",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        where = ["1=1"]
        params: list[Any] = []
        if skill:
            where.append("skill = ?")
            params.append(skill)
        if level:
            where.append("level = ?")
            params.append(level)
        if source_status:
            where.append("source_status = ?")
            params.append(source_status)
        if is_featured is not None:
            where.append("is_featured = ?")
            params.append(1 if is_featured else 0)
        order_map = {
            "recommend_score": "recommend_score DESC, sort_order ASC",
            "sort_order": "sort_order ASC, recommend_score DESC",
            "publish_date": "publish_date DESC NULLS LAST, recommend_score DESC",
        }
        order = order_map.get(sort_by, order_map["recommend_score"])
        sql = (
            "SELECT * FROM prep_resources WHERE "
            + " AND ".join(where)
            + f" ORDER BY {order} LIMIT ? OFFSET ?"
        )
        params.extend([int(limit), int(offset)])
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def list_featured(self, skill: Optional[str] = None, limit: int = 5) -> list[dict]:
        return self.list_resources(
            skill=skill, is_featured=True, sort_by="recommend_score",
            limit=limit, offset=0,
        )

    def list_by_up(self, author_name: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM prep_resources
               WHERE author_name = ?
               ORDER BY recommend_score DESC, sort_order ASC
               LIMIT ?""",
            (author_name, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_resources(
        self,
        skill: Optional[str] = None,
        level: Optional[str] = None,
        source_status: Optional[str] = None,
        is_featured: Optional[bool] = None,
    ) -> int:
        """按条件统计(与 list_resources 过滤维度对齐)。"""
        where = ["1=1"]
        params: list[Any] = []
        if skill:
            where.append("skill = ?")
            params.append(skill)
        if level:
            where.append("level = ?")
            params.append(level)
        if source_status:
            where.append("source_status = ?")
            params.append(source_status)
        if is_featured is not None:
            where.append("is_featured = ?")
            params.append(1 if is_featured else 0)
        sql = (
            "SELECT COUNT(*) AS c FROM prep_resources WHERE "
            + " AND ".join(where)
        )
        row = self._conn.execute(sql, params).fetchone()
        return int(row["c"])

    def update_resource(self, resource_id: int, **kwargs: Any) -> bool:
        """更新任意字段(只更新传入的非 None 值)。"""
        if not kwargs:
            return False
        # 字段白名单(避免 SQL 注入)
        allowed = {
            "title", "url", "method_summary", "source_status", "publish_date",
            "duration_sec", "outdated_risk", "is_featured",
            "recommend_score", "sort_order",
            "related_action_url", "related_action_label",
        }
        sets = []
        params: list[Any] = []
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                sets.append(f"{k} = ?")
                params.append(v)
        if not sets:
            return False
        sets.append("updated_at = ?")
        params.append(datetime.now().isoformat(timespec="seconds"))
        params.append(int(resource_id))
        sql = f"UPDATE prep_resources SET {', '.join(sets)} WHERE id = ?"
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur.rowcount > 0

    def delete_resource(self, resource_id: int) -> bool:
        cur = self._conn.execute(
            "DELETE FROM prep_resources WHERE id = ?",
            (int(resource_id),),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def list_distinct_ups(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT author_name, COUNT(*) AS cnt
               FROM prep_resources
               GROUP BY author_name
               ORDER BY cnt DESC, author_name ASC"""
        ).fetchall()
        return [{"author_name": r["author_name"], "count": int(r["cnt"])}
                for r in rows]


# =============================================================
# 6c. SQLiteReadingPracticeRepository (v3.8 P3 新增 - Reading 真题题库)
# =============================================================


class SQLiteReadingPracticeRepository:
    """SQLite 实现的 ReadingPracticeRepository。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---- 题库 ----
    def seed_passage(
        self,
        section: str,
        set_id: int,
        qid: int,
        passage_number: int,
        title: str,
        topic: str,
        question_type: str,
        passage_text: str,
        stem: str,
        options: Optional[list[str]],
        answer: str,
        explanation: str,
        word_count: int = 0,
        source_line: Optional[int] = None,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        opts_json = json.dumps(options, ensure_ascii=False) if options else None
        try:
            cur = self._conn.execute(
                """INSERT INTO reading_passages
                   (section, set_id, qid, passage_number, title, topic,
                    question_type, word_count, passage_text, stem,
                    options_json, answer, explanation, source_line,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (section, set_id, qid, passage_number, title, topic,
                 question_type, word_count, passage_text, stem,
                 opts_json, answer, explanation, source_line,
                 now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            self._conn.execute(
                """UPDATE reading_passages SET
                     passage_number = ?, title = ?, topic = ?,
                     question_type = ?, word_count = ?, passage_text = ?,
                     stem = ?, options_json = ?, answer = ?, explanation = ?,
                     source_line = ?, updated_at = ?
                 WHERE section = ? AND set_id = ? AND qid = ?""",
                (passage_number, title, topic, question_type, word_count,
                 passage_text, stem, opts_json, answer, explanation,
                 source_line, now, section, set_id, qid),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id FROM reading_passages "
                "WHERE section=? AND set_id=? AND qid=?",
                (section, set_id, qid),
            ).fetchone()
            return int(row["id"]) if row else -1

    def get_passage(self, question_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM reading_passages WHERE id = ?",
            (int(question_id),),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("options_json"):
            try:
                d["options"] = json.loads(d["options_json"])
            except Exception:
                d["options"] = []
        else:
            d["options"] = None
        return d

    def list_sections_with_counts(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT section,
                      COUNT(DISTINCT set_id) AS total_sets,
                      COUNT(*) AS total_passages
               FROM reading_passages
               GROUP BY section
               ORDER BY section"""
        ).fetchall()
        return [
            {
                "section": r["section"],
                "total_sets": int(r["total_sets"]),
                "total_passages": int(r["total_passages"]),
            }
            for r in rows
        ]

    def list_sets_by_section(self, section: str) -> list[dict]:
        rows = self._conn.execute(
            """SELECT set_id, MIN(passage_number) AS first_passage,
                      COUNT(*) AS question_count,
                      MIN(title) AS first_title,
                      MIN(topic) AS first_topic
               FROM reading_passages
               WHERE section = ?
               GROUP BY set_id
               ORDER BY set_id""",
            (section,),
        ).fetchall()
        return [
            {
                "set_id": int(r["set_id"]),
                "section": section,
                "first_passage": int(r["first_passage"] or 1),
                "question_count": int(r["question_count"]),
                "title": r["first_title"] or "",
                "topic": r["first_topic"] or "",
            }
            for r in rows
        ]

    def list_passages_by_set(self, section: str, set_id: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM reading_passages
               WHERE section = ? AND set_id = ?
               ORDER BY qid""",
            (section, set_id),
        ).fetchall()
        items = []
        for row in rows:
            d = dict(row)
            if d.get("options_json"):
                try:
                    d["options"] = json.loads(d["options_json"])
                except Exception:
                    d["options"] = []
            else:
                d["options"] = None
            items.append(d)
        return items

    def count_passages(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM reading_passages"
        ).fetchone()
        return int(row["c"])

    # ---- 答题记录 ----
    def record_attempt(
        self,
        user_id: int,
        question_id: int,
        user_answer: str,
        is_correct: bool,
        duration_sec: float = 0.0,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._conn.execute(
            """INSERT INTO reading_attempts
               (user_id, question_id, user_answer, is_correct,
                duration_sec, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, question_id, user_answer,
             1 if is_correct else 0, duration_sec, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_user_attempts(
        self,
        user_id: int,
        page: int = 1,
        size: int = 20,
        section: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        where_parts = ["a.user_id = ?"]
        params: list[Any] = [user_id]
        if section is not None:
            where_parts.append("p.section = ?")
            params.append(section)
        total_row = self._conn.execute(
            f"SELECT COUNT(*) AS cnt FROM reading_attempts a "
            f"LEFT JOIN reading_passages p ON a.question_id = p.id "
            f"WHERE {' AND '.join(where_parts)}",
            params,
        ).fetchone()
        total = int(total_row["cnt"])
        offset = max(0, (page - 1) * size)
        rows = self._conn.execute(
            f"""SELECT a.id, a.user_id, a.question_id, a.user_answer,
                       a.is_correct, a.duration_sec, a.created_at,
                       p.section AS section, p.set_id, p.qid,
                       p.title, p.question_type
                FROM reading_attempts a
                LEFT JOIN reading_passages p ON a.question_id = p.id
                WHERE {' AND '.join(where_parts)}
                ORDER BY a.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [size, offset],
        ).fetchall()
        return [dict(r) for r in rows], total

    def get_user_stats(self, user_id: int) -> dict:
        total_row = self._conn.execute(
            """SELECT COUNT(*) AS total_attempts,
                      SUM(is_correct) AS correct_count
               FROM reading_attempts WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        total = int(total_row["total_attempts"] or 0)
        correct = int(total_row["correct_count"] or 0)

        by_section_rows = self._conn.execute(
            """SELECT p.section,
                      COUNT(*) AS attempts,
                      SUM(a.is_correct) AS correct
               FROM reading_attempts a
               LEFT JOIN reading_passages p ON a.question_id = p.id
               WHERE a.user_id = ? AND p.section IS NOT NULL
               GROUP BY p.section
               ORDER BY p.section""",
            (user_id,),
        ).fetchall()
        by_section = {
            r["section"]: {
                "attempts": int(r["attempts"]),
                "correct": int(r["correct"] or 0),
                "accuracy": (
                    round((int(r["correct"] or 0) / int(r["attempts"])) * 100, 1)
                    if int(r["attempts"]) > 0 else 0.0
                ),
            }
            for r in by_section_rows
        }
        return {
            "total_attempts": total,
            "correct_count": correct,
            "accuracy": round(correct / total * 100, 1) if total > 0 else 0.0,
            "by_section": by_section,
        }


# =============================================================
# 7. SQLiteRepositoryContainer
# =============================================================


class SQLiteRepositoryContainer:
    """SQLite Repository 容器(v3.8 升级为 10 个)。"""

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
        self.typing = SQLiteTypingRepository(self._conn)
        self.focus_sessions = SQLiteFocusSessionRepository(self._conn)
        self.article = SQLiteArticleRepository(self._conn)
        self.user = SQLiteUserRepository(self._conn)
        # v3.7 P1：口语对练历史仓储
        self.speaking_practice = SQLiteSpeakingPracticeRepository(self._conn)
        # v3.7 P2：真·听力题库仓储
        self.listening_practice = SQLiteListeningPracticeRepository(self._conn)
        # v3.8 P3.1：备考资源广场
        self.prep_resource = SQLitePrepResourceRepository(self._conn)
        # v3.8 P3.2：Reading 真题题库
        self.reading_practice = SQLiteReadingPracticeRepository(self._conn)

        if cache_path is None:
            # v3：vocab_cache 与业务共用同一个 db 文件（避免维护多份 cache 拷贝）
            cache_path = self._db_path
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
    "SQLiteArticleRepository",
    "SQLiteVocabCacheRepository",
    "SQLiteUserRepository",
    "SQLiteSpeakingPracticeRepository",
    "SQLiteListeningPracticeRepository",
    "SQLiteRepositoryContainer",
    "create_sqlite_repositories",
    "REVIEW_INTERVALS",
]
