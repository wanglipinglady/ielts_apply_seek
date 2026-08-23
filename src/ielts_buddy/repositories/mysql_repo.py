"""MySQL Repository 实现。

W3 阶段：把 SQLite Repository 的 6 个接口翻译为 MySQL 8.0 实现。
所有业务方法都带 ``user_id`` 参数，与 SQLite 端语义一致。

设计要点：
1. 使用 SQLAlchemy Core（不是 ORM），保持 SQL 透明
2. ``vocab_cache`` / ``cache_meta`` 是跨用户共享的，不带 user_id
3. 首登时调用 ``seed_default_categories_for_user`` 把 user_id=0 的分类复制给新用户
4. 与 SQLite 端方法签名完全一致，可由 Service 层无差别调用
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, DECIMAL, Integer,
    Numeric, SmallInteger, MetaData, String,
    Table, Text, UniqueConstraint, Index, insert, select, update, delete, text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from ielts_buddy.core.models import (
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

# =============================================================
# 表元数据（用 SQLAlchemy Core 描述）
# =============================================================

metadata = MetaData()

t_users = Table(
    "users", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("username", String(64), nullable=False, unique=True),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("last_login_at", DateTime, nullable=True),
)

t_learning_records = Table(
    "learning_records", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False, server_default=text("1")),
    Column("word", String(128), nullable=False),
    Column("word_data", Text, nullable=False),
    Column("memory_level", Integer, nullable=False, server_default=text("0")),
    Column("next_review", Date, nullable=True),
    Column("learn_count", Integer, nullable=False, server_default=text("0")),
    Column("correct_count", Integer, nullable=False, server_default=text("0")),
    Column("wrong_count", Integer, nullable=False, server_default=text("0")),
    Column("first_learned", DateTime, nullable=True),
    Column("last_reviewed", DateTime, nullable=True),
    Column("is_starred", Boolean, nullable=False, server_default=text("0")),
    Column("is_difficult", Boolean, nullable=False, server_default=text("0")),
    Column("source", String(32), nullable=False, server_default=text("'builtin'")),
    UniqueConstraint("user_id", "word", name="uk_lr_user_word"),
    Index("idx_lr_user_review", "user_id", "next_review"),
    Index("idx_lr_user_level", "user_id", "memory_level"),
)

t_personal_vocab = Table(
    "personal_vocab", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False, server_default=text("1")),
    Column("word", String(128), nullable=False),
    Column("phonetic", String(128), nullable=True),
    Column("meaning", String(512), nullable=True),
    Column("pos", String(16), nullable=True),
    Column("band", Integer, nullable=True),
    Column("topic", String(64), nullable=True),
    Column("example", Text, nullable=True),
    Column("example_cn", Text, nullable=True),
    Column("note", Text, nullable=True),
    Column("source", String(32), nullable=False, server_default=text("'manual'")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False,
           server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    UniqueConstraint("user_id", "word", name="uk_pv_user_word"),
    Index("idx_pv_user_source", "user_id", "source"),
)

t_vocab_categories = Table(
    "vocab_categories", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False, server_default=text("1")),
    Column("name", String(64), nullable=False),
    Column("description", String(512), nullable=True),
    Column("is_system", Boolean, nullable=False, server_default=text("0")),
    Column("word_count", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("user_id", "name", name="uk_vc_user_name"),
)

t_vocab_category_words = Table(
    "vocab_category_words", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False, server_default=text("1")),
    Column("category_id", BigInteger, nullable=False),
    Column("word", String(128), nullable=False),
    Column("added_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("user_id", "category_id", "word", name="uk_vcw_user_cat_word"),
    Index("idx_vcw_user_word", "user_id", "word"),
)

t_exam_sessions = Table(
    "exam_sessions", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False, server_default=text("1")),
    Column("session_id", String(32), nullable=False),
    Column("questions_json", Text, nullable=False),
    Column("answers_json", Text, nullable=True),
    Column("time_limit", Integer, nullable=False, server_default=text("20")),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime, nullable=True),
    Column("band_filter", Integer, nullable=True),
    Column("score", DECIMAL(5, 2), nullable=True),
    Column("total", Integer, nullable=True),
    Column("accuracy", DECIMAL(5, 2), nullable=True),
    UniqueConstraint("user_id", "session_id", name="uk_es_user_session"),
    Index("idx_es_user_started", "user_id", "started_at"),
)

t_grade_history = Table(
    "grade_history", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False, server_default=text("1")),
    Column("overall_score", DECIMAL(3, 1), nullable=True),
    Column("task_type", String(32), nullable=True),
    Column("topic", String(256), nullable=True),
    Column("essay_text", Text, nullable=True),
    Column("result_json", Text, nullable=False),
    Column("graded_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Index("idx_gh_user_graded", "user_id", "graded_at"),
    Index("idx_gh_user_task", "user_id", "task_type"),
)

t_typing_history = Table(
    "typing_history", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False, server_default=text("1")),
    Column("mode", String(16), nullable=False, server_default=text("'words'")),
    Column("prompt_text", Text, nullable=False),
    Column("typed_text", Text, nullable=True),
    Column("duration_sec", Integer, nullable=False, server_default=text("0")),
    Column("wpm", DECIMAL(6, 2), nullable=False, server_default=text("0")),
    Column("accuracy", DECIMAL(5, 4), nullable=False, server_default=text("0")),
    Column("error_count", Integer, nullable=False, server_default=text("0")),
    Column("total_chars", Integer, nullable=False, server_default=text("0")),
    Column("completed", Boolean, nullable=False, server_default=text("1")),
    Column("result_json", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Index("idx_th_user_created", "user_id", "created_at"),
    Index("idx_th_user_mode", "user_id", "mode"),
)

# v3.6 番茄钟专注会话表
t_focus_sessions = Table(
    "focus_sessions", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False, server_default=text("1")),
    Column("activity", String(32), nullable=False, server_default=text("'other'")),
    Column("planned_sec", Integer, nullable=False, server_default=text("1500")),
    Column("duration_sec", Integer, nullable=False, server_default=text("0")),
    Column("interrupted", Boolean, nullable=False, server_default=text("0")),
    Column("note", Text, nullable=True),
    Column("started_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("ended_at", DateTime, nullable=True),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False,
           server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    Column("sync_status", String(16), nullable=False, server_default=text("'synced'")),
    Index("idx_fs_user_started", "user_id", "started_at"),
    Index("idx_fs_user_activity", "user_id", "activity"),
)

# v3.7 P1 口语对练历史表 (PRD: docs/web-mvp/plans/phase-8-speaking-practice.md §6)
t_speaking_practice_records = Table(
    "speaking_practice_records", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False),
    Column("session_id", String(64), nullable=False),
    Column("part", SmallInteger, nullable=False),
    Column("topic_id", Integer, nullable=True),
    Column("topic_name", String(128), nullable=False, server_default=text("''")),
    Column("question", Text, nullable=False),
    Column("audio_path", String(512), nullable=True),
    Column("audio_duration_sec", Numeric(8, 2), nullable=False, server_default=text("0")),
    Column("audio_mime", String(64), nullable=False, server_default=text("'audio/webm'")),
    Column("transcript", Text, nullable=False, server_default=text("''")),
    Column("transcript_tokens", Text, nullable=True),
    Column("llm_scores", Text, nullable=True),
    Column("llm_word_errors", Text, nullable=True),
    Column("llm_grammar_errors", Text, nullable=True),
    Column("llm_highlights", Text, nullable=True),
    Column("llm_suggestions", Text, nullable=True),
    Column("whisper_model", String(32), nullable=False, server_default=text("'small.en'")),
    Column("used_core_ml", Boolean, nullable=False, server_default=text("1")),
    Column("score_fallback", Boolean, nullable=False, server_default=text("0")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    Column("sync_status", String(16), nullable=False, server_default=text("'synced'")),
    UniqueConstraint("session_id", name="uk_spr_session"),
    Index("idx_spr_user_created", "user_id", "created_at"),
    Index("idx_spr_user_part", "user_id", "part"),
)


# v3.7 P2 真·听力题库:题库表
t_listening_questions = Table(
    "listening_questions", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("section", SmallInteger, nullable=False),
    Column("set_id", Integer, nullable=False),
    Column("qid", Integer, nullable=False),
    Column("scenario", String(128), nullable=False, server_default=text("''")),
    Column("question_type", String(32), nullable=False),
    Column("stem", Text, nullable=False),
    Column("options_json", Text, nullable=True),
    Column("answer", String(256), nullable=False),
    Column("explanation", Text, nullable=False, server_default=text("''")),
    Column("transcript", Text, nullable=False, server_default=text("''")),
    Column("audio_path", String(512), nullable=True),
    Column("audio_generated_at", DateTime, nullable=True),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    Column("sync_status", String(16), nullable=False, server_default=text("'synced'")),
    UniqueConstraint("section", "set_id", "qid", name="uk_lq_section_set_qid"),
    Index("idx_lq_section_set", "section", "set_id"),
)


# v3.7 P2 真·听力题库:答题记录表
t_listening_attempts = Table(
    "listening_attempts", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False),
    Column("question_id", BigInteger, nullable=False),
    Column("user_answer", String(256), nullable=False),
    Column("is_correct", Boolean, nullable=False, server_default=text("0")),
    Column("duration_sec", Numeric(8, 2), nullable=False, server_default=text("0")),
    Column("played_count", Integer, nullable=False, server_default=text("1")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    Column("sync_status", String(16), nullable=False, server_default=text("'synced'")),
    Index("idx_la_user_created", "user_id", "created_at"),
    Index("idx_la_user_q", "user_id", "question_id"),
)

# v3.8 备考资源广场(v3.8 P3.1 新增)
t_prep_resources = Table(
    "prep_resources", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("title", String(256), nullable=False),
    Column("bv_id", String(32), nullable=False),
    Column("url", String(512), nullable=False),
    Column("author_name", String(64), nullable=False),
    Column("author_uid", BigInteger, nullable=True),
    Column("uploader_name", String(64), nullable=False, server_default=text("''")),
    Column("uploader_uid", BigInteger, nullable=True),
    Column("skill", String(16), nullable=False),  # listening | reading | speaking | writing | general
    Column("video_type", String(16), nullable=False),  # methodology | planning | tips | pitfalls | mock | vocab
    Column("level", String(16), nullable=False),  # 0-5 | 5-6 | 6.5-7 | 7+
    Column("method_summary", Text, nullable=False),
    Column("source_status", String(32), nullable=False, server_default=text("'verified_repost'")),
    Column("publish_date", Date, nullable=True),
    Column("duration_sec", Integer, nullable=False, server_default=text("0")),
    Column("outdated_risk", String(16), nullable=False, server_default=text("'low'")),
    Column("format_compatible", String(16), nullable=False, server_default=text("'computer'")),
    Column("computer_delivery_only", Boolean, nullable=False, server_default=text("1")),
    Column("is_featured", Boolean, nullable=False, server_default=text("0")),
    Column("recommend_score", Numeric(4, 2), nullable=False, server_default=text("0.0")),
    Column("sort_order", Integer, nullable=False, server_default=text("100")),
    Column("related_action_url", String(256), nullable=True),
    Column("related_action_label", String(64), nullable=True),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    Column("sync_status", String(16), nullable=False, server_default=text("'synced'")),
    UniqueConstraint("bv_id", name="uk_pr_bv_id"),
    Index("idx_pr_skill", "skill"),
    Index("idx_pr_score", "recommend_score"),
    Index("idx_pr_author", "author_name"),
)

# v3.8 Reading 真题题库(v3.8 P3.2 新增)
t_reading_passages = Table(
    "reading_passages", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("section", String(16), nullable=False),  # easy | medium | hard | academic
    Column("set_id", Integer, nullable=False),
    Column("qid", Integer, nullable=False),
    Column("passage_number", SmallInteger, nullable=False),
    Column("title", String(256), nullable=False),
    Column("topic", String(128), nullable=False, server_default=text("''")),
    Column("question_type", String(32), nullable=False),
    Column("word_count", Integer, nullable=False, server_default=text("0")),
    Column("passage_text", Text, nullable=False),
    Column("stem", Text, nullable=False),
    Column("options_json", Text, nullable=True),
    Column("answer", String(256), nullable=False),
    Column("explanation", Text, nullable=False, server_default=text("''")),
    Column("source_line", Integer, nullable=True),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    Column("sync_status", String(16), nullable=False, server_default=text("'synced'")),
    UniqueConstraint("section", "set_id", "qid", name="uk_rp_section_set_qid"),
    Index("idx_rp_section_set", "section", "set_id"),
)

t_reading_attempts = Table(
    "reading_attempts", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", BigInteger, nullable=False),
    Column("question_id", BigInteger, nullable=False),
    Column("user_answer", String(256), nullable=False),
    Column("is_correct", Boolean, nullable=False, server_default=text("0")),
    Column("duration_sec", Numeric(8, 2), nullable=False, server_default=text("0")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
    Column("sync_status", String(16), nullable=False, server_default=text("'synced'")),
    Index("idx_rat_user_created", "user_id", "created_at"),
)

t_vocab_cache = Table(
    "vocab_cache", metadata,
    Column("word", String(128), primary_key=True),
    Column("band", Integer, nullable=False),
    Column("topic", String(64), nullable=False),
    Column("payload_json", Text, nullable=False),
    Index("idx_vc_band", "band"),
    Index("idx_vc_topic", "topic"),
)

t_cache_meta = Table(
    "cache_meta", metadata,
    Column("key_name", String(64), primary_key=True),
    Column("value", String(256), nullable=False),
    Column("updated_at", DateTime, nullable=False,
           server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")),
)


# =============================================================
# 工具函数
# =============================================================

# 艾宾浩斯复习间隔（与 SQLite 一致）
REVIEW_INTERVALS = [0, 1, 2, 4, 7, 15, 30]


def _next_review_date(today_str: str, level: int) -> str:
    today = date.fromisoformat(today_str)
    interval = REVIEW_INTERVALS[min(level, len(REVIEW_INTERVALS) - 1)]
    return (today + timedelta(days=interval)).isoformat()


def _row_to_learning_record(row: Any) -> LearningRecord:
    m = row._mapping
    return LearningRecord(
        id=m["id"],
        user_id=m["user_id"],
        word_id=m["id"],  # 与 SQLite 端保持兼容（word_id == id）
        memory_level=m["memory_level"],
        next_review=m["next_review"].isoformat() if m["next_review"] else None,
        learn_count=m["learn_count"],
        correct_count=m["correct_count"],
        wrong_count=m["wrong_count"],
        first_learned=m["first_learned"].isoformat() if m["first_learned"] else None,
        last_reviewed=m["last_reviewed"].isoformat() if m["last_reviewed"] else None,
        is_starred=bool(m["is_starred"]),
        is_difficult=bool(m["is_difficult"]),
    )


def _row_to_personal_word(row: Any) -> PersonalWord:
    m = row._mapping
    return PersonalWord(
        id=m["id"],
        user_id=m["user_id"],
        word=m["word"],
        phonetic=m["phonetic"] or "",
        meaning=m["meaning"] or "",
        pos=m["pos"] or "",
        band=m["band"] or 5,
        topic=m["topic"] or "",
        example=m["example"] or "",
        example_cn=m["example_cn"] or "",
        note=m["note"] or "",
        source=m["source"],
        created_at=m["created_at"].isoformat() if m["created_at"] else None,
        updated_at=m["updated_at"].isoformat() if m["updated_at"] else None,
    )


def _row_to_vocab_category(row: Any) -> VocabCategory:
    m = row._mapping
    return VocabCategory(
        id=m["id"],
        user_id=m["user_id"],
        name=m["name"],
        description=m["description"] or "",
        is_system=bool(m["is_system"]),
        word_count=m["word_count"] or 0,
        created_at=m["created_at"].isoformat() if m["created_at"] else None,
    )


# =============================================================
# 1. MySQLLearningRepository
# =============================================================


class MySQLLearningRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_record(self, user_id: int, word: str) -> Optional[LearningRecord]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_learning_records).where(
                    (t_learning_records.c.user_id == user_id)
                    & (t_learning_records.c.word == word)
                )
            ).first()
            return _row_to_learning_record(row) if row else None

    def upsert_record(
        self,
        user_id: int,
        word: Word,
        correct: bool,
        source: str = "builtin",
    ) -> LearningRecord:
        now = datetime.now()
        today_str = date.today().isoformat()
        word_data = word.model_dump_json()

        with self._engine.begin() as conn:
            row = conn.execute(
                select(t_learning_records).where(
                    (t_learning_records.c.user_id == user_id)
                    & (t_learning_records.c.word == word.word)
                )
            ).first()

            if row is None:
                level = 1 if correct else 0
                next_review = _next_review_date(today_str, level)
                conn.execute(insert(t_learning_records).values(
                    user_id=user_id,
                    word=word.word,
                    word_data=word_data,
                    memory_level=level,
                    next_review=next_review,
                    learn_count=1,
                    correct_count=1 if correct else 0,
                    wrong_count=0 if correct else 1,
                    first_learned=now,
                    last_reviewed=now,
                    source=source,
                ))
            else:
                current_level = row._mapping["memory_level"]
                if correct:
                    new_level = min(current_level + 1, len(REVIEW_INTERVALS) - 1)
                else:
                    new_level = max(current_level - 1, 0)
                next_review = _next_review_date(today_str, new_level)
                conn.execute(
                    update(t_learning_records)
                    .where(
                        (t_learning_records.c.user_id == user_id)
                        & (t_learning_records.c.word == word.word)
                    )
                    .values(
                        memory_level=new_level,
                        next_review=next_review,
                        learn_count=t_learning_records.c.learn_count + 1,
                        correct_count=t_learning_records.c.correct_count + (1 if correct else 0),
                        wrong_count=t_learning_records.c.wrong_count + (0 if correct else 1),
                        last_reviewed=now,
                    )
                )

        # 回读
        return self.get_record(user_id, word.word)  # type: ignore[return-value]

    def toggle_star(self, user_id: int, word: str) -> bool:
        with self._engine.begin() as conn:
            row = conn.execute(
                select(t_learning_records.c.is_starred).where(
                    (t_learning_records.c.user_id == user_id)
                    & (t_learning_records.c.word == word)
                )
            ).first()
            if row is None:
                raise ValueError(f"未找到单词 '{word}' 的学习记录")
            new_state = not bool(row._mapping["is_starred"])
            conn.execute(
                update(t_learning_records)
                .where(
                    (t_learning_records.c.user_id == user_id)
                    & (t_learning_records.c.word == word)
                )
                .values(is_starred=new_state)
            )
            return new_state

    def toggle_difficult(self, user_id: int, word: str) -> bool:
        with self._engine.begin() as conn:
            row = conn.execute(
                select(t_learning_records.c.is_difficult).where(
                    (t_learning_records.c.user_id == user_id)
                    & (t_learning_records.c.word == word)
                )
            ).first()
            if row is None:
                raise ValueError(f"未找到单词 '{word}' 的学习记录")
            new_state = not bool(row._mapping["is_difficult"])
            conn.execute(
                update(t_learning_records)
                .where(
                    (t_learning_records.c.user_id == user_id)
                    & (t_learning_records.c.word == word)
                )
                .values(is_difficult=new_state)
            )
            return new_state

    def get_due_words(self, user_id: int, limit: int = 20) -> list[dict]:
        today_str = date.today().isoformat()
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_learning_records)
                .where(
                    (t_learning_records.c.user_id == user_id)
                    & (t_learning_records.c.next_review <= today_str)
                )
                .order_by(t_learning_records.c.memory_level.asc(), t_learning_records.c.next_review.asc())
                .limit(limit)
            ).fetchall()
        results = []
        for row in rows:
            word_data = Word(**json.loads(row._mapping["word_data"]))
            record = _row_to_learning_record(row)
            results.append({
                "word": row._mapping["word"],
                "word_data": word_data,
                "record": record,
            })
        return results

    def get_due_count(self, user_id: int) -> int:
        today_str = date.today().isoformat()
        with self._engine.connect() as conn:
            row = conn.execute(
                select(text("COUNT(*)")).select_from(t_learning_records).where(
                    (t_learning_records.c.user_id == user_id)
                    & (t_learning_records.c.next_review <= today_str)
                )
            ).first()
            return int(row[0]) if row else 0

    def get_history(self, user_id: int, days: int = 30) -> list[dict]:
        today = date.today()
        start = today - timedelta(days=days - 1)
        start_dt = datetime.combine(start, datetime.min.time())

        with self._engine.connect() as conn:
            new_rows = conn.execute(text("""
                SELECT DATE(first_learned) AS learn_date, COUNT(*) AS cnt
                FROM learning_records
                WHERE user_id = :uid AND first_learned >= :start
                GROUP BY DATE(first_learned)
            """), {"uid": user_id, "start": start_dt}).fetchall()

            review_rows = conn.execute(text("""
                SELECT DATE(last_reviewed) AS review_date, COUNT(*) AS cnt
                FROM learning_records
                WHERE user_id = :uid AND last_reviewed >= :start
                GROUP BY DATE(last_reviewed)
            """), {"uid": user_id, "start": start_dt}).fetchall()

        new_counts = {str(r[0]): r[1] for r in new_rows}
        review_counts = {str(r[0]): r[1] for r in review_rows}

        result = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            result.append({
                "date": d,
                "new_words": new_counts.get(d, 0),
                "reviewed_words": review_counts.get(d, 0),
            })
        return result

    def get_all_records(self, user_id: int) -> list[LearningRecord]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_learning_records)
                .where(t_learning_records.c.user_id == user_id)
                .order_by(t_learning_records.c.last_reviewed.desc())
            ).fetchall()
        return [_row_to_learning_record(r) for r in rows]

    def get_learned_count(self, user_id: int) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(text("COUNT(*)")).select_from(t_learning_records).where(
                    t_learning_records.c.user_id == user_id
                )
            ).first()
            return int(row[0]) if row else 0

    def get_learned_words_today(self, user_id: int) -> list[str]:
        today_dt = datetime.combine(date.today(), datetime.min.time())
        with self._engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT word FROM learning_records
                WHERE user_id = :uid AND DATE(first_learned) = :today
            """), {"uid": user_id, "today": today_dt}).fetchall()
        return [r[0] for r in rows]

    # ---- 错词本 (v3.6 新增) ----
    def get_wrong_words(
        self,
        user_id: int,
        min_wrong: int = 1,
        days: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """按 wrong_count DESC 返回错词列表(dict,含 word/word_data)。"""
        stmt = select(t_learning_records).where(
            t_learning_records.c.user_id == user_id,
            t_learning_records.c.wrong_count >= min_wrong,
        )
        if days is not None:
            since = (date.today() - timedelta(days=days - 1))
            stmt = stmt.where(t_learning_records.c.last_reviewed >= since)
        stmt = stmt.order_by(
            t_learning_records.c.wrong_count.desc(),
            t_learning_records.c.last_reviewed.desc(),
        ).limit(limit)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        # _mapping 拿 dict(row) 等价物,含所有列
        return [dict(r._mapping) for r in rows]

    def reset_mistake(self, user_id: int, word: str) -> bool:
        """重置错词状态:wrong_count=0, memory_level=6(标记已掌握)。"""
        now_dt = datetime.now()
        stmt = (
            update(t_learning_records)
            .where(
                t_learning_records.c.user_id == user_id,
                t_learning_records.c.word == word,
            )
            .values(wrong_count=0, memory_level=6, last_reviewed=now_dt)
        )
        with self._engine.connect() as conn:
            result = conn.execute(stmt)
            conn.commit()
        return result.rowcount > 0

    def get_mistake_stats(self, user_id: int) -> dict:
        """错词本聚合统计（MySQL 版）。"""
        try:
            with self._engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT
                        SUM(CASE WHEN wrong_count > 0 THEN 1 ELSE 0 END) AS distinct_words,
                        COALESCE(SUM(wrong_count), 0) AS total_wrong_count
                    FROM learning_records WHERE user_id = :uid
                """), {"uid": user_id}).first()
                since_7d = date.today() - timedelta(days=6)
                row7 = conn.execute(text("""
                    SELECT COUNT(*) AS cnt
                    FROM learning_records
                    WHERE user_id = :uid
                      AND wrong_count > 0
                      AND DATE(last_reviewed) >= :since
                """), {"uid": user_id, "since": since_7d}).first()
                top_rows = conn.execute(text("""
                    SELECT word, wrong_count, last_reviewed
                    FROM learning_records
                    WHERE user_id = :uid AND wrong_count > 0
                    ORDER BY wrong_count DESC, last_reviewed DESC
                    LIMIT 5
                """), {"uid": user_id}).fetchall()
            return {
                "distinct_words": int((row[0] if row else 0) or 0),
                "total_wrong_count": int((row[1] if row else 0) or 0),
                "last_7d_wrong": int((row7[0] if row7 else 0) or 0),
                "top_offenders": [
                    {
                        "word": r[0],
                        "wrong_count": int(r[1] or 0),
                        "last_reviewed": r[2].isoformat() if r[2] else "",
                    }
                    for r in top_rows
                ],
            }
        except Exception:
            print("[mysql] get_mistake_stats failed")
            return {
                "distinct_words": 0,
                "total_wrong_count": 0,
                "last_7d_wrong": 0,
                "top_offenders": [],
            }

    def get_learned_words(self, user_id: int) -> list[str]:
        """返回用户学过的所有词（任意时间）。"""
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT word FROM learning_records WHERE user_id = :uid"
            ), {"uid": user_id}).fetchall()
        return [r[0] for r in rows]

    # ---- 口语对练错词回收 (v3.7 P1) ----
    def record_speaking_error(
        self,
        user_id: int,
        word: str,
        source: str = "speaking",
    ) -> bool:
        """对 learning_records 做口语错词信号。
        与 upsert_record 不一样：不推进 memory_level，仅 wrong_count +1；
        若词不存在则新建 (wrong_count=1, correct_count=0, memory_level=0)。
        """
        word_clean = (word or "").strip().lower()
        if not word_clean:
            return False
        now_dt = datetime.now()
        placeholder_data = json.dumps(
            {"word": word_clean, "meaning": "", "band": 5},
            ensure_ascii=False,
        )
        try:
            with self._engine.begin() as conn:
                existing = conn.execute(
                    text("SELECT id FROM learning_records "
                         "WHERE user_id = :uid AND word = :w"),
                    {"uid": user_id, "w": word_clean},
                ).fetchone()
                if existing is None:
                    conn.execute(text("""
                        INSERT INTO learning_records
                        (user_id, word, word_data, memory_level, next_review,
                         learn_count, correct_count, wrong_count,
                         first_learned, last_reviewed, source)
                        VALUES (:uid, :w, :wd, 0, :nr, 0, 0, 1, :fr, :lr, :src)
                    """), {
                        "uid": user_id, "w": word_clean,
                        "wd": placeholder_data,
                        "nr": date.today().isoformat(),
                        "fr": now_dt.isoformat(timespec="seconds"),
                        "lr": now_dt.isoformat(timespec="seconds"),
                        "src": source,
                    })
                else:
                    conn.execute(text("""
                        UPDATE learning_records
                           SET wrong_count = wrong_count + 1,
                               last_reviewed = :lr
                         WHERE user_id = :uid AND word = :w
                    """), {
                        "uid": user_id, "w": word_clean,
                        "lr": now_dt.isoformat(timespec="seconds"),
                    })
            return True
        except IntegrityError as exc:
            print(f"[mysql] record_speaking_error conflict: {exc}", file=__import__("sys").stderr)
            return False
        except Exception as exc:
            print(f"[mysql] record_speaking_error failed: {exc}", file=__import__("sys").stderr)
            return False


# =============================================================
# 1b. MySQLSpeakingPracticeRepository (v3.7 P1 新增)
# =============================================================


class MySQLSpeakingPracticeRepository:
    """MySQL 实现的 SpeakingPracticeRepository."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        with self._engine.begin() as conn:
            result = conn.execute(insert(t_speaking_practice_records).values(
                user_id=user_id,
                session_id=session_id,
                part=int(part),
                topic_id=topic_id,
                topic_name=topic_name or "",
                question=question,
                audio_path=audio_path,
                audio_duration_sec=float(audio_duration_sec),
                audio_mime=audio_mime,
            ))
            return int(result.inserted_primary_key[0])

    def update_practice_transcript(
        self,
        user_id: int,
        session_id: str,
        transcript: str,
        transcript_tokens: Optional[list[dict]] = None,
        whisper_model: str = "small.en",
        used_core_ml: bool = True,
    ) -> bool:
        tokens_json = json.dumps(transcript_tokens or [], ensure_ascii=False)
        with self._engine.begin() as conn:
            result = conn.execute(
                update(t_speaking_practice_records)
                .where(t_speaking_practice_records.c.user_id == user_id,
                       t_speaking_practice_records.c.session_id == session_id)
                .values(
                    transcript=transcript,
                    transcript_tokens=tokens_json,
                    whisper_model=whisper_model,
                    used_core_ml=1 if used_core_ml else 0,
                )
            )
            return result.rowcount > 0

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
        with self._engine.begin() as conn:
            result = conn.execute(
                update(t_speaking_practice_records)
                .where(t_speaking_practice_records.c.user_id == user_id,
                       t_speaking_practice_records.c.session_id == session_id)
                .values(
                    llm_scores=json.dumps(scores, ensure_ascii=False),
                    llm_word_errors=json.dumps(word_errors, ensure_ascii=False),
                    llm_grammar_errors=json.dumps(grammar_errors, ensure_ascii=False),
                    llm_highlights=json.dumps(highlights, ensure_ascii=False),
                    llm_suggestions=json.dumps(suggestions, ensure_ascii=False),
                    score_fallback=1 if score_fallback else 0,
                )
            )
            return result.rowcount > 0

    # ---- 读取 ----
    def get_practice_record(
        self,
        user_id: int,
        record_id: int,
    ) -> Optional[dict]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_speaking_practice_records).where(
                    t_speaking_practice_records.c.user_id == user_id,
                    t_speaking_practice_records.c.id == record_id,
                )
            ).fetchone()
            return dict(row._mapping) if row else None

    def get_practice_by_session(
        self,
        user_id: int,
        session_id: str,
    ) -> Optional[dict]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_speaking_practice_records).where(
                    t_speaking_practice_records.c.user_id == user_id,
                    t_speaking_practice_records.c.session_id == session_id,
                )
            ).fetchone()
            return dict(row._mapping) if row else None

    def list_practice_history(
        self,
        user_id: int,
        part: Optional[int] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict], int]:
        with self._engine.connect() as conn:
            if part is not None:
                total = conn.execute(
                    text("SELECT COUNT(*) FROM speaking_practice_records "
                         "WHERE user_id = :uid AND part = :p"),
                    {"uid": user_id, "p": part},
                ).scalar() or 0
                rows = conn.execute(
                    select(t_speaking_practice_records)
                    .where(t_speaking_practice_records.c.user_id == user_id,
                           t_speaking_practice_records.c.part == part)
                    .order_by(t_speaking_practice_records.c.created_at.desc())
                    .limit(size).offset((page - 1) * size)
                ).fetchall()
            else:
                total = conn.execute(
                    text("SELECT COUNT(*) FROM speaking_practice_records "
                         "WHERE user_id = :uid"),
                    {"uid": user_id},
                ).scalar() or 0
                rows = conn.execute(
                    select(t_speaking_practice_records)
                    .where(t_speaking_practice_records.c.user_id == user_id)
                    .order_by(t_speaking_practice_records.c.created_at.desc())
                    .limit(size).offset((page - 1) * size)
                ).fetchall()
        return [dict(r._mapping) for r in rows], int(total)

    # ---- 清理 ----
    def set_audio_null(self, user_id: int, session_id: str) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                update(t_speaking_practice_records)
                .where(t_speaking_practice_records.c.user_id == user_id,
                       t_speaking_practice_records.c.session_id == session_id)
                .values(audio_path=None)
            )
            return result.rowcount > 0

    def list_expired_audio_paths(
        self,
        retention_days: int,
    ) -> list[tuple[int, str, str]]:
        """返回所有 retention_days 天前的录音记录 (user_id, session_id, audio_path)。"""
        cutoff = datetime.now() - timedelta(days=retention_days)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(
                    t_speaking_practice_records.c.user_id,
                    t_speaking_practice_records.c.session_id,
                    t_speaking_practice_records.c.audio_path,
                )
                .where(t_speaking_practice_records.c.audio_path.isnot(None),
                       t_speaking_practice_records.c.created_at < cutoff)
            ).fetchall()
        return [(int(r.user_id), r.session_id, r.audio_path) for r in rows]

    def delete_old_records_keeping_audio_path(
        self,
        cutoff_days: int,
    ) -> int:
        cutoff = date.today() - timedelta(days=cutoff_days)
        with self._engine.begin() as conn:
            result = conn.execute(
                delete(t_speaking_practice_records)
                .where(t_speaking_practice_records.c.audio_path.is_(None),
                       t_speaking_practice_records.c.created_at < cutoff)
            )
            return result.rowcount


# =============================================================
# 1b. MySQLListeningPracticeRepository (v3.7 P2 新增)
# =============================================================


class MySQLListeningPracticeRepository:
    """MySQL 实现的 ListeningPracticeRepository。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        opts_json = json.dumps(options, ensure_ascii=False) if options else None
        gen_at = (
            datetime.fromisoformat(audio_generated_at)
            if audio_generated_at else None
        )
        with self._engine.begin() as conn:
            try:
                result = conn.execute(
                    insert(t_listening_questions).values(
                        section=section, set_id=set_id, qid=qid,
                        scenario=scenario, question_type=question_type,
                        stem=stem, options_json=opts_json, answer=answer,
                        explanation=explanation, transcript=transcript,
                        audio_path=audio_path, audio_generated_at=gen_at,
                    )
                )
                return int(result.inserted_primary_key[0])
            except IntegrityError:
                # upsert
                conn.execute(
                    update(t_listening_questions)
                    .where(t_listening_questions.c.section == section,
                           t_listening_questions.c.set_id == set_id,
                           t_listening_questions.c.qid == qid)
                    .values(
                        scenario=scenario, question_type=question_type,
                        stem=stem, options_json=opts_json, answer=answer,
                        explanation=explanation, transcript=transcript,
                    )
                )
                row = conn.execute(
                    select(t_listening_questions.c.id)
                    .where(t_listening_questions.c.section == section,
                           t_listening_questions.c.set_id == set_id,
                           t_listening_questions.c.qid == qid)
                ).fetchone()
                return int(row.id) if row else -1

    def get_question(self, question_id: int) -> Optional[dict]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_listening_questions)
                .where(t_listening_questions.c.id == question_id)
            ).fetchone()
        if row is None:
            return None
        d = dict(row._mapping)
        if d.get("options_json"):
            try:
                d["options"] = json.loads(d["options_json"])
            except Exception:
                d["options"] = []
        else:
            d["options"] = None
        return d

    def list_sections_with_counts(self) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT section, "
                    "COUNT(DISTINCT set_id) AS total_sets, "
                    "COUNT(*) AS total_questions "
                    "FROM listening_questions "
                    "GROUP BY section ORDER BY section"
                )
            ).fetchall()
        return [
            {
                "section": int(r.section),
                "total_sets": int(r.total_sets),
                "total_questions": int(r.total_questions),
            }
            for r in rows
        ]

    def list_sets_by_section(self, section: int) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT set_id, scenario, COUNT(*) AS question_count, "
                    "MIN(stem) AS first_stem "
                    "FROM listening_questions "
                    "WHERE section = :section "
                    "GROUP BY set_id, scenario ORDER BY set_id"
                ),
                {"section": section},
            ).fetchall()
        return [
            {
                "set_id": int(r.set_id),
                "section": section,
                "scenario": r.scenario or "",
                "question_count": int(r.question_count),
                "first_stem": r.first_stem or "",
            }
            for r in rows
        ]

    def list_questions_by_set(
        self, section: int, set_id: int
    ) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_listening_questions)
                .where(t_listening_questions.c.section == section,
                       t_listening_questions.c.set_id == set_id)
                .order_by(t_listening_questions.c.qid)
            ).fetchall()
        items = []
        for row in rows:
            d = dict(row._mapping)
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
        gen_at = (
            datetime.fromisoformat(audio_generated_at)
            if audio_generated_at else None
        )
        with self._engine.begin() as conn:
            conn.execute(
                update(t_listening_questions)
                .where(t_listening_questions.c.id == question_id)
                .values(audio_path=audio_path, audio_generated_at=gen_at)
            )

    def count_questions(self) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT COUNT(*) AS c FROM listening_questions")
            ).fetchone()
        return int(row.c)

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
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(t_listening_attempts).values(
                    user_id=user_id, question_id=question_id,
                    user_answer=user_answer, is_correct=bool(is_correct),
                    duration_sec=duration_sec, played_count=played_count,
                )
            )
            return int(result.inserted_primary_key[0])

    def list_user_attempts(
        self,
        user_id: int,
        page: int = 1,
        size: int = 20,
        section: Optional[int] = None,
    ) -> tuple[list[dict], int]:
        where_parts = ["a.user_id = :uid"]
        params: dict[str, Any] = {
            "uid": user_id, "limit": size, "offset": (page - 1) * size,
        }
        if section is not None:
            where_parts.append("q.section = :section")
            params["section"] = section
        where = " AND ".join(where_parts)
        with self._engine.connect() as conn:
            total_row = conn.execute(
                text(
                    f"SELECT COUNT(*) AS c FROM listening_attempts a "
                    f"LEFT JOIN listening_questions q ON a.question_id = q.id "
                    f"WHERE {where}"
                ),
                params,
            ).fetchone()
            total = int(total_row.c)
            rows = conn.execute(
                text(
                    f"SELECT a.*, q.section, q.set_id, q.qid, q.scenario, "
                    f"q.stem, q.transcript, q.answer AS correct_answer, q.audio_path "
                    f"FROM listening_attempts a "
                    f"LEFT JOIN listening_questions q ON a.question_id = q.id "
                    f"WHERE {where} "
                    f"ORDER BY a.created_at DESC, a.id DESC "
                    f"LIMIT :limit OFFSET :offset"
                ),
                params,
            ).fetchall()
        return [dict(r._mapping) for r in rows], total

    def get_user_stats(self, user_id: int) -> dict:
        with self._engine.connect() as conn:
            total_row = conn.execute(
                text(
                    "SELECT COUNT(*) AS total_attempts, "
                    "COALESCE(SUM(is_correct), 0) AS correct_count "
                    "FROM listening_attempts WHERE user_id = :uid"
                ),
                {"uid": user_id},
            ).fetchone()
            by_section_rows = conn.execute(
                text(
                    "SELECT q.section, COUNT(*) AS attempts, "
                    "COALESCE(SUM(a.is_correct), 0) AS correct "
                    "FROM listening_attempts a "
                    "LEFT JOIN listening_questions q ON a.question_id = q.id "
                    "WHERE a.user_id = :uid AND q.section IS NOT NULL "
                    "GROUP BY q.section ORDER BY q.section"
                ),
                {"uid": user_id},
            ).fetchall()

        total = int(total_row.total_attempts)
        correct = int(total_row.correct_count)
        by_section = {
            int(r.section): {
                "attempts": int(r.attempts),
                "correct": int(r.correct),
                "accuracy": (
                    round(int(r.correct) / int(r.attempts) * 100, 1)
                    if int(r.attempts) > 0 else 0.0
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
        cutoff = datetime.now() - timedelta(days=retention_days)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(
                    t_listening_questions.c.id,
                    t_listening_questions.c.audio_path,
                )
                .where(t_listening_questions.c.audio_path.isnot(None),
                       t_listening_questions.c.audio_generated_at.isnot(None),
                       t_listening_questions.c.audio_generated_at < cutoff)
            ).fetchall()
        return [(int(r.id), r.audio_path) for r in rows]


# =============================================================
# 2. MySQLPersonalVocabRepository
# =============================================================


class MySQLPersonalVocabRepository:
    SYSTEM_CATEGORY_NAMES = ("favorites", "mistakes")

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _ensure_system_categories(self, user_id: int) -> None:
        """如果当前用户没有系统分类，从 user_id=0 模板复制（首登触发）"""
        with self._engine.begin() as conn:
            existing = conn.execute(
                select(t_vocab_categories.c.name).where(t_vocab_categories.c.user_id == user_id)
            ).fetchall()
            existing_names = {r[0] for r in existing}
            for name in self.SYSTEM_CATEGORY_NAMES:
                if name in existing_names:
                    continue
                # 从 user_id=0 复制
                tmpl = conn.execute(
                    select(t_vocab_categories).where(
                        (t_vocab_categories.c.user_id == 0)
                        & (t_vocab_categories.c.name == name)
                    )
                ).first()
                if tmpl is None:
                    # 模板缺失（不应该发生），手动插
                    conn.execute(insert(t_vocab_categories).values(
                        user_id=user_id, name=name,
                        description={"favorites": "收藏夹", "mistakes": "错词本"}.get(name, ""),
                        is_system=True, word_count=0,
                    ))
                else:
                    m = tmpl._mapping
                    conn.execute(insert(t_vocab_categories).values(
                        user_id=user_id, name=name, description=m["description"] or "",
                        is_system=True, word_count=0,
                    ))

    # ---- 单词 CRUD ----

    def add_word(self, user_id: int, pw: Word | PersonalWord) -> int:
        """添加单词到个人词库。兼容 Word 与 PersonalWord（与 add_mistake 一致）。"""
        self._ensure_system_categories(user_id)
        with self._engine.begin() as conn:
            try:
                result = conn.execute(insert(t_personal_vocab).values(
                    user_id=user_id,
                    word=pw.word,
                    phonetic=getattr(pw, "phonetic", "") or "",
                    meaning=pw.meaning,
                    pos=getattr(pw, "pos", "") or "",
                    band=pw.band,
                    topic=getattr(pw, "topic", "") or "",
                    example=getattr(pw, "example", "") or "",
                    example_cn=getattr(pw, "example_cn", "") or "",
                    note=getattr(pw, "note", "") or "",
                    source=getattr(pw, "source", "manual") or "manual",
                ))
                return int(result.inserted_primary_key[0])
            except IntegrityError:
                raise ValueError(f"单词 '{pw.word}' 已存在于个人词库中")

    def edit_word(self, user_id: int, word_name: str, **kwargs: Any) -> PersonalWord:
        existing = self.get_word(user_id, word_name)
        if existing is None:
            raise ValueError(f"单词 '{word_name}' 不在个人词库中")

        allowed = {"phonetic", "meaning", "pos", "band", "topic", "example", "example_cn", "note"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return existing

        with self._engine.begin() as conn:
            conn.execute(
                update(t_personal_vocab)
                .where(
                    (t_personal_vocab.c.user_id == user_id)
                    & (t_personal_vocab.c.word == word_name)
                )
                .values(**updates)
            )
        return self.get_word(user_id, word_name)  # type: ignore[return-value]

    def delete_word(self, user_id: int, word_name: str) -> bool:
        with self._engine.begin() as conn:
            word_row = conn.execute(
                select(t_personal_vocab.c.id).where(
                    (t_personal_vocab.c.user_id == user_id)
                    & (t_personal_vocab.c.word == word_name)
                )
            ).first()
            if word_row is None:
                return False
            conn.execute(
                delete(t_vocab_category_words).where(
                    (t_vocab_category_words.c.user_id == user_id)
                    & (t_vocab_category_words.c.word == word_name)
                )
            )
            result = conn.execute(
                delete(t_personal_vocab).where(
                    (t_personal_vocab.c.user_id == user_id)
                    & (t_personal_vocab.c.word == word_name)
                )
            )
            return result.rowcount > 0

    def get_word(self, user_id: int, word_name: str) -> Optional[PersonalWord]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_personal_vocab).where(
                    (t_personal_vocab.c.user_id == user_id)
                    & (t_personal_vocab.c.word == word_name)
                )
            ).first()
            return _row_to_personal_word(row) if row else None

    def list_words(
        self,
        user_id: int,
        category: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[PersonalWord], int]:
        with self._engine.connect() as conn:
            if category:
                cat_row = conn.execute(
                    select(t_vocab_categories.c.id).where(
                        (t_vocab_categories.c.user_id == user_id)
                        & (t_vocab_categories.c.name == category)
                    )
                ).first()
                if cat_row is None:
                    return [], 0
                cat_id = cat_row[0]

                total_row = conn.execute(
                    select(text("COUNT(*)")).select_from(t_personal_vocab).where(
                        (t_personal_vocab.c.user_id == user_id)
                        & (
                            select(t_vocab_category_words.c.word).where(
                                (t_vocab_category_words.c.user_id == user_id)
                                & (t_vocab_category_words.c.category_id == cat_id)
                            ).exists()
                        )
                    )
                ).first()
                total = int(total_row[0]) if total_row else 0

                offset = (page - 1) * per_page
                rows = conn.execute(text("""
                    SELECT p.* FROM personal_vocab p
                    JOIN vocab_category_words cw ON cw.word = p.word
                    WHERE p.user_id = :uid AND cw.user_id = :uid AND cw.category_id = :cat_id
                    ORDER BY p.created_at DESC
                    LIMIT :limit OFFSET :offset
                """), {"uid": user_id, "cat_id": cat_id, "limit": per_page, "offset": offset}).fetchall()
            else:
                total_row = conn.execute(
                    select(text("COUNT(*)")).select_from(t_personal_vocab).where(
                        t_personal_vocab.c.user_id == user_id
                    )
                ).first()
                total = int(total_row[0]) if total_row else 0

                offset = (page - 1) * per_page
                rows = conn.execute(
                    select(t_personal_vocab)
                    .where(t_personal_vocab.c.user_id == user_id)
                    .order_by(t_personal_vocab.c.created_at.desc())
                    .limit(per_page).offset(offset)
                ).fetchall()

        return [_row_to_personal_word(r) for r in rows], total

    def get_word_count(self, user_id: int) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(text("COUNT(*)")).select_from(t_personal_vocab).where(
                    t_personal_vocab.c.user_id == user_id
                )
            ).first()
            return int(row[0]) if row else 0

    # ---- 分类管理 ----

    def create_category(self, user_id: int, name: str, description: str = "") -> VocabCategory:
        self._ensure_system_categories(user_id)
        with self._engine.begin() as conn:
            try:
                conn.execute(insert(t_vocab_categories).values(
                    user_id=user_id, name=name, description=description, is_system=False, word_count=0,
                ))
            except IntegrityError:
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
        with self._engine.begin() as conn:
            # 先清掉关联
            conn.execute(
                delete(t_vocab_category_words).where(
                    (t_vocab_category_words.c.user_id == user_id)
                    & (t_vocab_category_words.c.category_id == cat.id)
                )
            )
            conn.execute(
                delete(t_vocab_categories).where(
                    (t_vocab_categories.c.user_id == user_id)
                    & (t_vocab_categories.c.name == name)
                )
            )
        return True

    def list_categories(self, user_id: int) -> list[VocabCategory]:
        self._ensure_system_categories(user_id)
        with self._engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT c.*, COUNT(cw.id) AS word_count
                FROM vocab_categories c
                LEFT JOIN vocab_category_words cw
                  ON cw.category_id = c.id AND cw.user_id = c.user_id
                WHERE c.user_id = :uid
                GROUP BY c.id
                ORDER BY c.is_system DESC, c.name ASC
            """), {"uid": user_id}).fetchall()
        # 重建行对象以便 _row_to_vocab_category 处理
        result = []
        for r in rows:
            # 把 word_count 注入到 mapping
            class _RowProxy:
                def __init__(self, mapping):
                    self._mapping = mapping
            mapping = dict(r._mapping)
            mapping["word_count"] = r.word_count
            result.append(_row_to_vocab_category(_RowProxy(mapping)))
        return result

    def add_to_category(self, user_id: int, word: str, category: str) -> bool:
        word_row = self.get_word(user_id, word)
        if word_row is None:
            raise ValueError(f"单词 '{word}' 不在个人词库中")
        cat = self._get_category_by_name(user_id, category)
        if cat is None:
            raise ValueError(f"分类 '{category}' 不存在")
        with self._engine.begin() as conn:
            try:
                conn.execute(insert(t_vocab_category_words).values(
                    user_id=user_id, category_id=cat.id, word=word,
                ))
            except IntegrityError:
                return False
        return True

    def remove_from_category(self, user_id: int, word: str, category: str) -> bool:
        cat = self._get_category_by_name(user_id, category)
        if cat is None:
            raise ValueError(f"分类 '{category}' 不存在")
        with self._engine.begin() as conn:
            result = conn.execute(
                delete(t_vocab_category_words).where(
                    (t_vocab_category_words.c.user_id == user_id)
                    & (t_vocab_category_words.c.category_id == cat.id)
                    & (t_vocab_category_words.c.word == word)
                )
            )
            return result.rowcount > 0

    def get_word_categories(self, user_id: int, word: str) -> list[VocabCategory]:
        with self._engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT c.* FROM vocab_categories c
                JOIN vocab_category_words cw ON cw.category_id = c.id
                WHERE cw.user_id = :uid AND c.user_id = :uid AND cw.word = :word
                ORDER BY c.name
            """), {"uid": user_id, "word": word}).fetchall()
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
            word=word, example=context, example_cn=suggestion, note=comment, source="grading",
        )
        self.add_word(user_id, pw)
        return self.get_word(user_id, word)  # type: ignore[return-value]

    # ---- 统计 ----

    def get_source_distribution(self, user_id: int) -> dict[str, int]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_personal_vocab.c.source, text("COUNT(*) AS cnt"))
                .where(t_personal_vocab.c.user_id == user_id)
                .group_by(t_personal_vocab.c.source)
                .order_by(text("cnt DESC"))
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_band_distribution(self, user_id: int) -> dict[int, int]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_personal_vocab.c.band, text("COUNT(*) AS cnt"))
                .where(t_personal_vocab.c.user_id == user_id)
                .group_by(t_personal_vocab.c.band)
                .order_by(t_personal_vocab.c.band)
            ).fetchall()
        return {int(r[0]): int(r[1]) for r in rows}

    # ---- 导入导出（纯逻辑，与 SQLite 端独立） ----

    def import_words(
        self,
        user_id: int,
        file_path: Any,
        vocab_service: Any = None,
    ) -> dict[str, int]:
        import csv as _csv
        import io as _io

        suffix = str(file_path).lower()
        if suffix.endswith(".json"):
            content = open(file_path, encoding="utf-8").read().strip()
        else:
            content = open(file_path, encoding="utf-8").read().strip()
        if not content:
            return {"imported": 0, "skipped": 0, "failed": 0}

        words: list[PersonalWord] = []
        if suffix.endswith(".json"):
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
                        source="import",
                    ))
                except Exception:
                    continue
        elif suffix.endswith(".csv"):
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
                        word=row["word"].strip(), meaning=row.get("meaning", "").strip(),
                        band=band, source="import",
                    ))
                except Exception:
                    continue
        else:
            for line in content.splitlines():
                w = line.strip()
                if not w:
                    continue
                if vocab_service:
                    builtin = vocab_service.get_word(w)
                    if builtin:
                        words.append(PersonalWord(
                            word=builtin.word, meaning=builtin.meaning,
                            band=builtin.band, source="import",
                        ))
                        continue
                words.append(PersonalWord(word=w, source="import"))

        imported = skipped = failed = 0
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
        import csv as _csv
        import io as _io

        words, _ = self.list_words(user_id, category=category, page=1, per_page=999_999)
        if not words:
            return "[]" if fmt == "json" else ""

        if fmt == "csv":
            output = _io.StringIO()
            writer = _csv.DictWriter(output, fieldnames=[
                "word", "phonetic", "meaning", "pos", "band", "topic",
                "example", "example_cn", "note",
            ])
            writer.writeheader()
            for w in words:
                writer.writerow({
                    "word": w.word, "phonetic": w.phonetic, "meaning": w.meaning,
                    "pos": w.pos, "band": w.band, "topic": w.topic,
                    "example": w.example, "example_cn": w.example_cn, "note": w.note,
                })
            return output.getvalue()

        data = [{
            "word": w.word, "phonetic": w.phonetic, "meaning": w.meaning,
            "pos": w.pos, "band": w.band, "topic": w.topic,
        } for w in words]
        return json.dumps(data, ensure_ascii=False, indent=2)

    # ---- 内部 ----

    def _get_category_by_name(
        self, user_id: int, name: str
    ) -> Optional[VocabCategory]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_vocab_categories).where(
                    (t_vocab_categories.c.user_id == user_id)
                    & (t_vocab_categories.c.name == name)
                )
            ).first()
            return _row_to_vocab_category(row) if row else None


# =============================================================
# 3. MySQLExamRepository
# =============================================================


class MySQLExamRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_exam(
        self,
        user_id: int,
        band: int,
        count: int,
        time_limit: int = 20,
    ) -> ExamSession:
        """W3 阶段：create_exam 只生成 session 对象（题目由 Service 层注入）。

        Service 层在生成题目后会调 ``save_exam_session`` 显式落库。
        """
        return ExamSession(
            id=self._gen_session_id(),
            user_id=user_id,
            time_limit=time_limit,
            started_at=datetime.now().isoformat(timespec="seconds"),
            band_filter=band,
        )

    @staticmethod
    def _gen_session_id() -> str:
        import uuid
        return uuid.uuid4().hex[:12]

    def save_exam_session(self, user_id: int, session: ExamSession) -> None:
        """显式落库考试 session（被 Service 层调用）"""
        questions_json = json.dumps(
            [q.model_dump() for q in session.questions], ensure_ascii=False
        )
        with self._engine.begin() as conn:
            conn.execute(insert(t_exam_sessions).values(
                user_id=user_id, session_id=session.id,
                questions_json=questions_json, time_limit=session.time_limit,
                started_at=session.started_at, band_filter=session.band_filter,
            ))

    def submit_answer(
        self,
        user_id: int,
        session_id: str,
        q_index: int,
        answer: str,
    ) -> dict:
        with self._engine.begin() as conn:
            row = conn.execute(
                select(t_exam_sessions.c.questions_json).where(
                    (t_exam_sessions.c.user_id == user_id)
                    & (t_exam_sessions.c.session_id == session_id)
                )
            ).first()
            if row is None:
                raise ValueError(f"考试 {session_id} 不存在")
            questions = json.loads(row[0])
            if q_index < 0 or q_index >= len(questions):
                raise IndexError(f"题号 {q_index} 超出范围")
            q = questions[q_index]

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

            conn.execute(
                update(t_exam_sessions)
                .where(
                    (t_exam_sessions.c.user_id == user_id)
                    & (t_exam_sessions.c.session_id == session_id)
                )
                .values(questions_json=json.dumps(questions, ensure_ascii=False))
            )
            return {"correct": is_correct, "answer": q["answer"]}

    def finish_exam(self, user_id: int, session_id: str) -> ExamReport:
        with self._engine.begin() as conn:
            row = conn.execute(
                select(t_exam_sessions).where(
                    (t_exam_sessions.c.user_id == user_id)
                    & (t_exam_sessions.c.session_id == session_id)
                )
            ).first()
            if row is None:
                raise ValueError(f"考试 {session_id} 不存在")
            questions = json.loads(row._mapping["questions_json"])
            finished_at = datetime.now()

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
            started = row._mapping["started_at"]
            duration = int((finished_at - started).total_seconds())

            report = ExamReport(
                session_id=session_id,
                user_id=user_id,
                score=correct_count,
                total=total,
                accuracy=accuracy,
                band_breakdown=band_breakdown,
                weak_words=weak_words,
                duration=duration,
                finished_at=finished_at.isoformat(timespec="seconds"),
            )

            # 保存 report 数据（score/total/accuracy/finished_at）
            conn.execute(
                update(t_exam_sessions)
                .where(
                    (t_exam_sessions.c.user_id == user_id)
                    & (t_exam_sessions.c.session_id == session_id)
                )
                .values(
                    finished_at=finished_at,
                    score=correct_count, total=total, accuracy=accuracy,
                )
            )
        return report

    def get_exam_history(self, user_id: int, limit: int = 20) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_exam_sessions)
                .where(
                    (t_exam_sessions.c.user_id == user_id)
                    & (t_exam_sessions.c.finished_at.isnot(None))
                )
                .order_by(t_exam_sessions.c.finished_at.desc())
                .limit(limit)
            ).fetchall()
        results = []
        for row in rows:
            m = row._mapping
            questions = json.loads(m["questions_json"]) if m["questions_json"] else []
            weak_words = [q["word"] for q in questions if not q.get("is_correct")]
            band_breakdown: dict[int, dict[str, int]] = {}
            for q in questions:
                if q.get("is_correct") is None:
                    continue
                b = q.get("band", 5)
                if b not in band_breakdown:
                    band_breakdown[b] = {"correct": 0, "wrong": 0}
                if q.get("is_correct"):
                    band_breakdown[b]["correct"] += 1
                else:
                    band_breakdown[b]["wrong"] += 1
            results.append({
                "session_id": m["session_id"],
                "score": int(m["score"]) if m["score"] is not None else 0,
                "total": int(m["total"]) if m["total"] is not None else 0,
                "accuracy": float(m["accuracy"]) if m["accuracy"] is not None else 0.0,
                "band_breakdown": band_breakdown,
                "weak_words": weak_words,
                "duration": 0,
                "finished_at": m["finished_at"].isoformat() if m["finished_at"] else "",
            })
        return results

    def get_exam_session(self, user_id: int, session_id: str) -> Optional[ExamSession]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_exam_sessions).where(
                    (t_exam_sessions.c.user_id == user_id)
                    & (t_exam_sessions.c.session_id == session_id)
                )
            ).first()
            if row is None:
                return None
            from ielts_buddy.core.models import ExamQuestion

            m = row._mapping
            questions_data = json.loads(m["questions_json"]) if m["questions_json"] else []
            questions = [ExamQuestion(**q) for q in questions_data]
            return ExamSession(
                id=m["session_id"],
                user_id=m["user_id"],
                questions=questions,
                time_limit=m["time_limit"],
                started_at=m["started_at"].isoformat(timespec="seconds") if m["started_at"] else "",
                finished_at=m["finished_at"].isoformat(timespec="seconds") if m["finished_at"] else None,
                band_filter=m["band_filter"],
            )


# =============================================================
# 4. MySQLGradeRepository
# =============================================================


class MySQLGradeRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save_result(self, user_id: int, result: GradeResult) -> int:
        with self._engine.begin() as conn:
            row = conn.execute(insert(t_grade_history).values(
                user_id=user_id,
                overall_score=result.overall_score,
                task_type=result.task_type,
                topic=result.topic,
                essay_text=result.essay_text,
                result_json=result.model_dump_json(),
                graded_at=result.graded_at or datetime.now().isoformat(timespec="seconds"),
            ))
            return int(row.inserted_primary_key[0])

    def get_history(
        self,
        user_id: int,
        limit: int = 20,
        task_type: Optional[str] = None,
    ) -> list[GradeResult]:
        with self._engine.connect() as conn:
            stmt = select(t_grade_history.c.result_json).where(
                t_grade_history.c.user_id == user_id
            )
            if task_type:
                stmt = stmt.where(t_grade_history.c.task_type == task_type)
            stmt = stmt.order_by(t_grade_history.c.id.desc()).limit(limit)
            rows = conn.execute(stmt).fetchall()
        results = []
        for row in rows:
            try:
                data = json.loads(row[0])
                results.append(GradeResult(**data))
            except Exception:
                continue
        return results

    def get_average_score(self, user_id: int) -> float:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(text("AVG(overall_score)")).select_from(t_grade_history).where(
                    t_grade_history.c.user_id == user_id
                )
            ).first()
            if row is None or row[0] is None:
                return 0.0
            return float(row[0])

    def get_error_trend(self, user_id: int, limit: int = 10) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_grade_history.c.graded_at,
                      t_grade_history.c.overall_score,
                      t_grade_history.c.result_json)
                .where(t_grade_history.c.user_id == user_id)
                .order_by(t_grade_history.c.id.desc())
                .limit(limit)
            ).fetchall()
        result = []
        for row in reversed(rows):
            try:
                data = json.loads(row[2])
                summary = data.get("error_summary", {})
            except (json.JSONDecodeError, TypeError):
                summary = {}
            result.append({
                "graded_at": row[0].isoformat() if row[0] else "",
                "overall_score": float(row[1]) if row[1] is not None else 0.0,
                "error_summary": summary,
            })
        return result


# =============================================================
# 4b. MySQLTypingRepository
# =============================================================


class MySQLTypingRepository:
    """MySQL 实现的 TypingRepository。

    持久化机考打字练习的成绩（与 SQLite 版同 schema 同接口）。
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save_record(self, user_id: int, record: TypingRecord) -> int:
        with self._engine.begin() as conn:
            row = conn.execute(insert(t_typing_history).values(
                user_id=user_id,
                mode=record.mode,
                prompt_text=record.prompt_text,
                typed_text=record.typed_text,
                duration_sec=record.duration_sec,
                wpm=float(record.wpm),
                accuracy=float(record.accuracy),
                error_count=record.error_count,
                total_chars=record.total_chars,
                completed=1 if record.completed else 0,
                result_json=record.model_dump_json(),
            ))
            return int(row.inserted_primary_key[0])

    def get_history(
        self,
        user_id: int,
        limit: int = 20,
        mode: Optional[str] = None,
    ) -> list[TypingRecord]:
        with self._engine.connect() as conn:
            stmt = select(t_typing_history.c.result_json).where(
                t_typing_history.c.user_id == user_id
            )
            if mode:
                stmt = stmt.where(t_typing_history.c.mode == mode)
            stmt = stmt.order_by(t_typing_history.c.id.desc()).limit(limit)
            rows = conn.execute(stmt).fetchall()
        results: list[TypingRecord] = []
        for r in rows:
            try:
                data = json.loads(r[0])
                results.append(TypingRecord(**data))
            except Exception:
                continue
        return results

    def get_history_count(self, user_id: int, mode: Optional[str] = None) -> int:
        with self._engine.connect() as conn:
            stmt = select(text("COUNT(*)")).select_from(t_typing_history).where(
                t_typing_history.c.user_id == user_id
            )
            if mode:
                stmt = stmt.where(t_typing_history.c.mode == mode)
            row = conn.execute(stmt).first()
            if row is None or row[0] is None:
                return 0
            return int(row[0])

    def get_average_wpm(self, user_id: int, mode: Optional[str] = None) -> float:
        with self._engine.connect() as conn:
            stmt = select(text("AVG(wpm)")).select_from(t_typing_history).where(
                t_typing_history.c.user_id == user_id
            )
            if mode:
                stmt = stmt.where(t_typing_history.c.mode == mode)
            row = conn.execute(stmt).first()
            if row is None or row[0] is None:
                return 0.0
            return float(row[0])

    def get_average_accuracy(self, user_id: int, mode: Optional[str] = None) -> float:
        with self._engine.connect() as conn:
            stmt = select(text("AVG(accuracy)")).select_from(t_typing_history).where(
                t_typing_history.c.user_id == user_id
            )
            if mode:
                stmt = stmt.where(t_typing_history.c.mode == mode)
            row = conn.execute(stmt).first()
            if row is None or row[0] is None:
                return 0.0
            return float(row[0])

    def get_max_wpm(self, user_id: int, mode: Optional[str] = None) -> float:
        with self._engine.connect() as conn:
            stmt = select(text("MAX(wpm)")).select_from(t_typing_history).where(
                t_typing_history.c.user_id == user_id
            )
            if mode:
                stmt = stmt.where(t_typing_history.c.mode == mode)
            row = conn.execute(stmt).first()
            if row is None or row[0] is None:
                return 0.0
            return float(row[0])


# =============================================================
# 4b. MySQLFocusSessionRepository (v3.6 番茄钟)
# =============================================================


class MySQLFocusSessionRepository:
    """MySQL 实现的 FocusSession 仓库（v3.6 番茄钟新增）。

    与 SQLite 版同 schema 同接口；push 路径由 SyncWorker 调用 complete_session
    之前的 save_record 不需要 —— push 阶段 SyncWorker 直接走 SQL 写 MySQL，
    本仓库主要供 service 层直接使用与 pull 后的回读。
    """

    VALID_ACTIVITIES = ("vocab", "writing", "exam", "typing", "reading", "other")

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def _normalize_activity(cls, activity: str) -> str:
        return activity if activity in cls.VALID_ACTIVITIES else "other"

    def start_session(self, user_id: int, session: FocusSession) -> int:
        """INSERT 一行,duration_sec=0,interrupted=0。"""
        from datetime import datetime as _dt
        now = session.started_at or _dt.now().isoformat(timespec="seconds")
        with self._engine.begin() as conn:
            row = conn.execute(insert(t_focus_sessions).values(
                user_id=user_id,
                activity=self._normalize_activity(session.activity),
                planned_sec=int(session.planned_sec),
                duration_sec=0,
                interrupted=False,
                note=session.note or "",
                started_at=now,
                ended_at=None,
                created_at=now,
                sync_status="synced",
            ))
            return int(row.inserted_primary_key[0])

    def complete_session(
        self,
        user_id: int,
        session_id: int,
        duration_sec: int,
        interrupted: bool,
        note: Optional[str],
    ) -> bool:
        """UPDATE 实际专注时长 + 结束标记。"""
        from datetime import datetime as _dt
        now = _dt.now().isoformat(timespec="seconds")
        with self._engine.begin() as conn:
            result = conn.execute(
                update(t_focus_sessions)
                .where(t_focus_sessions.c.id == session_id)
                .where(t_focus_sessions.c.user_id == user_id)
                .values(
                    duration_sec=max(0, int(duration_sec)),
                    interrupted=bool(interrupted),
                    note=note or "",
                    ended_at=now,
                    updated_at=now,
                    sync_status="synced",
                )
            )
            return result.rowcount > 0

    def get_history(
        self, user_id: int, limit: int = 20
    ) -> list[FocusSession]:
        """按 started_at DESC 取最近 N 条。"""
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_focus_sessions).where(
                    t_focus_sessions.c.user_id == user_id
                ).order_by(t_focus_sessions.c.started_at.desc()).limit(limit)
            ).fetchall()
        results: list[FocusSession] = []
        for r in rows:
            results.append(FocusSession(
                id=int(r.id),
                user_id=int(r.user_id),
                activity=r.activity or "other",
                planned_sec=int(r.planned_sec or 0),
                duration_sec=int(r.duration_sec or 0),
                interrupted=bool(r.interrupted),
                note=r.note or "",
                started_at=str(r.started_at) if r.started_at else "",
                ended_at=str(r.ended_at) if r.ended_at else "",
                created_at=str(r.created_at) if r.created_at else "",
            ))
        return results

    def get_today_summary(self, user_id: int) -> dict[str, Any]:
        """今日累计: 番茄数 + 总专注秒数 + 完成数 + 放弃数。"""
        from datetime import datetime as _dt
        today = _dt.now().date().isoformat()
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "       COALESCE(SUM(duration_sec), 0) AS total_sec, "
                    "       SUM(CASE WHEN interrupted = 0 "
                    "                     AND duration_sec >= planned_sec * 0.8 "
                    "                THEN 1 ELSE 0 END) AS completed, "
                    "       SUM(CASE WHEN interrupted = 1 THEN 1 ELSE 0 END) AS abandoned "
                    "FROM focus_sessions "
                    "WHERE user_id = :uid "
                    "  AND DATE(started_at) = :today"
                ),
                {"uid": user_id, "today": today},
            ).first()
        return {
            "date": today,
            "total": int(row[0] or 0) if row else 0,
            "total_sec": int(row[1] or 0) if row else 0,
            "completed": int(row[2] or 0) if row else 0,
            "abandoned": int(row[3] or 0) if row else 0,
        }

    def get_total_count(self, user_id: int) -> int:
        """用户累计番茄数。"""
        with self._engine.connect() as conn:
            row = conn.execute(
                select(text("COUNT(*)")).select_from(t_focus_sessions).where(
                    t_focus_sessions.c.user_id == user_id
                )
            ).first()
        return int(row[0]) if row and row[0] is not None else 0


# =============================================================
# 5. MySQLVocabCacheRepository
# =============================================================


class MySQLVocabCacheRepository:
    """vocab_cache 是跨用户共享的缓存，不带 user_id。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_cached(self, word: str) -> Optional[dict]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_vocab_cache).where(t_vocab_cache.c.word == word)
            ).first()
            if row is None:
                return None
            m = row._mapping
            payload = json.loads(m["payload_json"])
            return {
                "word": m["word"],
                "band": m["band"],
                "topic": m["topic"],
                **payload,
            }

    def put_cached(self, word: str, band: int, topic: str, payload: dict) -> None:
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._engine.begin() as conn:
            conn.execute(insert(t_vocab_cache).values(
                word=word, band=band, topic=topic, payload_json=payload_json,
            ))

    def get_mtime(self, key: str) -> str:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_cache_meta.c.value).where(t_cache_meta.c.key_name == key)
            ).first()
            return row[0] if row else ""

    def set_mtime(self, key: str, value: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(t_cache_meta).values(key_name=key, value=value))

    def clear_cache(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(t_vocab_cache))


# =============================================================
# 6. MySQLUserRepository
# =============================================================


class MySQLUserRepository:
    """联网模式 UserRepository。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_or_create(self, username: str) -> int:
        with self._engine.begin() as conn:
            row = conn.execute(
                select(t_users.c.id).where(t_users.c.username == username)
            ).first()
            if row is not None:
                user_id = int(row[0])
            else:
                result = conn.execute(insert(t_users).values(username=username))
                user_id = int(result.inserted_primary_key[0])

            # 更新 last_login_at
            conn.execute(
                update(t_users)
                .where(t_users.c.id == user_id)
                .values(last_login_at=datetime.now())
            )
            return user_id

    def get_by_id(self, user_id: int) -> Optional[dict]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_users).where(t_users.c.id == user_id)
            ).first()
            if row is None:
                return None
            m = row._mapping
            return {
                "id": m["id"],
                "username": m["username"],
                "created_at": m["created_at"].isoformat() if m["created_at"] else None,
                "last_login_at": m["last_login_at"].isoformat() if m["last_login_at"] else None,
            }

    def update_last_login(self, user_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(t_users)
                .where(t_users.c.id == user_id)
                .values(last_login_at=datetime.now())
            )

    def list_users(self) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_users).order_by(t_users.c.created_at.desc())
            ).fetchall()
        return [
            {
                "id": r._mapping["id"],
                "username": r._mapping["username"],
                "created_at": r._mapping["created_at"].isoformat() if r._mapping["created_at"] else None,
                "last_login_at": r._mapping["last_login_at"].isoformat() if r._mapping["last_login_at"] else None,
            }
            for r in rows
        ]

    def ensure_system_categories(self, user_id: int) -> None:
        """首登时调用：把 user_id=0 模板复制给当前用户"""
        pv = MySQLPersonalVocabRepository(self._engine)
        pv._ensure_system_categories(user_id)


# =============================================================
# 默认 MySQL 连接参数（与 init_mysql.sql 保持一致）
# =============================================================
DEFAULT_MYSQL_HOST = "118.190.148.121"
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MYSQL_USER = "remote_user"
DEFAULT_MYSQL_PASSWORD = "Pass@666"  # noqa: S105
DEFAULT_MYSQL_DATABASE = "ietls_learn_online"
DEFAULT_MYSQL_CHARSET = "utf8mb4"


def _build_mysql_url(
    host: str = DEFAULT_MYSQL_HOST,
    port: int = DEFAULT_MYSQL_PORT,
    user: str = DEFAULT_MYSQL_USER,
    password: str = DEFAULT_MYSQL_PASSWORD,
    database: str = DEFAULT_MYSQL_DATABASE,
    charset: str = DEFAULT_MYSQL_CHARSET,
) -> str:
    """拼出 SQLAlchemy 用的 MySQL URL，密码中的 @ 需要 percent-encode。"""
    from urllib.parse import quote_plus
    pwd = quote_plus(password)
    return (
        f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{database}"
        f"?charset={charset}"
    )


class MySQLPrepResourceRepository:
    """MySQL 实现的 PrepResourceRepository(v3.8 新增)。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        now = datetime.now()
        with self._engine.begin() as conn:
            try:
                res = conn.execute(
                    insert(t_prep_resources).values(
                        title=title, bv_id=bv_id, url=url,
                        author_name=author_name, author_uid=author_uid,
                        uploader_name=uploader_name or "", uploader_uid=uploader_uid,
                        skill=skill, video_type=video_type, level=level,
                        method_summary=method_summary,
                        source_status=source_status,
                        publish_date=publish_date,
                        duration_sec=duration_sec,
                        outdated_risk=outdated_risk,
                        format_compatible=format_compatible,
                        computer_delivery_only=1 if computer_delivery_only else 0,
                        is_featured=1 if is_featured else 0,
                        recommend_score=float(recommend_score),
                        sort_order=int(sort_order),
                        related_action_url=related_action_url,
                        related_action_label=related_action_label,
                        created_at=now, updated_at=now,
                    )
                )
                return int(res.inserted_primary_key[0])
            except IntegrityError:
                conn.execute(
                    update(t_prep_resources)
                    .where(t_prep_resources.c.bv_id == bv_id)
                    .values(
                        title=title, url=url,
                        author_name=author_name, author_uid=author_uid,
                        uploader_name=uploader_name or "", uploader_uid=uploader_uid,
                        skill=skill, video_type=video_type, level=level,
                        method_summary=method_summary,
                        source_status=source_status,
                        publish_date=publish_date,
                        duration_sec=duration_sec,
                        outdated_risk=outdated_risk,
                        format_compatible=format_compatible,
                        computer_delivery_only=1 if computer_delivery_only else 0,
                        is_featured=1 if is_featured else 0,
                        recommend_score=float(recommend_score),
                        sort_order=int(sort_order),
                        related_action_url=related_action_url,
                        related_action_label=related_action_label,
                        updated_at=now,
                    )
                )
                row = conn.execute(
                    select(t_prep_resources.c.id)
                    .where(t_prep_resources.c.bv_id == bv_id)
                ).fetchone()
                return int(row[0]) if row else -1

    def get_resource(self, resource_id: int) -> Optional[dict]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_prep_resources)
                .where(t_prep_resources.c.id == int(resource_id))
            ).fetchone()
        return dict(row._mapping) if row else None

    def get_resource_by_bv(self, bv_id: str) -> Optional[dict]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_prep_resources)
                .where(t_prep_resources.c.bv_id == bv_id)
            ).fetchone()
        return dict(row._mapping) if row else None

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
        params: dict[str, Any] = {}
        if skill:
            where.append("skill = :skill")
            params["skill"] = skill
        if level:
            where.append("level = :level")
            params["level"] = level
        if source_status:
            where.append("source_status = :ss")
            params["ss"] = source_status
        if is_featured is not None:
            where.append("is_featured = :feat")
            params["feat"] = 1 if is_featured else 0
        order_map = {
            "recommend_score": "recommend_score DESC, sort_order ASC",
            "sort_order": "sort_order ASC, recommend_score DESC",
            "publish_date": "publish_date DESC NULLS LAST, recommend_score DESC",
        }
        order = order_map.get(sort_by, order_map["recommend_score"])
        sql = (
            "SELECT * FROM prep_resources WHERE "
            + " AND ".join(where)
            + f" ORDER BY {order} LIMIT :limit OFFSET :offset"
        )
        params["limit"] = int(limit)
        params["offset"] = int(offset)
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
        return [dict(r._mapping) for r in rows]

    def list_featured(self, skill: Optional[str] = None, limit: int = 5) -> list[dict]:
        return self.list_resources(
            skill=skill, is_featured=True, sort_by="recommend_score",
            limit=limit, offset=0,
        )

    def list_by_up(self, author_name: str, limit: int = 20) -> list[dict]:
        sql = (
            "SELECT * FROM prep_resources WHERE author_name = :author "
            "ORDER BY recommend_score DESC, sort_order ASC LIMIT :limit"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(sql),
                {"author": author_name, "limit": int(limit)},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def count_resources(self, skill: Optional[str] = None) -> int:
        with self._engine.connect() as conn:
            if skill:
                row = conn.execute(
                    text("SELECT COUNT(*) AS c FROM prep_resources WHERE skill = :s"),
                    {"s": skill},
                ).fetchone()
            else:
                row = conn.execute(
                    text("SELECT COUNT(*) AS c FROM prep_resources")
                ).fetchone()
        return int(row[0])

    def update_resource(self, resource_id: int, **kwargs: Any) -> bool:
        if not kwargs:
            return False
        allowed = {
            "title", "url", "method_summary", "source_status", "publish_date",
            "duration_sec", "outdated_risk", "is_featured",
            "recommend_score", "sort_order",
            "related_action_url", "related_action_label",
        }
        sets = []
        params: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                sets.append(f"{k} = :{k}")
                params[k] = v
        if not sets:
            return False
        sets.append("updated_at = :upd")
        params["upd"] = datetime.now()
        params["rid"] = int(resource_id)
        sql = f"UPDATE prep_resources SET {', '.join(sets)} WHERE id = :rid"
        with self._engine.begin() as conn:
            res = conn.execute(text(sql), params)
        return res.rowcount > 0

    def delete_resource(self, resource_id: int) -> bool:
        with self._engine.begin() as conn:
            res = conn.execute(
                text("DELETE FROM prep_resources WHERE id = :rid"),
                {"rid": int(resource_id)},
            )
        return res.rowcount > 0

    def list_distinct_ups(self) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT author_name, COUNT(*) AS cnt FROM prep_resources "
                "GROUP BY author_name ORDER BY cnt DESC, author_name ASC"
            )).fetchall()
        return [{"author_name": r[0], "count": int(r[1])} for r in rows]


class MySQLReadingPracticeRepository:
    """MySQL 实现的 ReadingPracticeRepository(v3.8 新增)。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        now = datetime.now()
        opts_json = json.dumps(options, ensure_ascii=False) if options else None
        with self._engine.begin() as conn:
            try:
                res = conn.execute(insert(t_reading_passages).values(
                    section=section, set_id=set_id, qid=qid,
                    passage_number=passage_number, title=title, topic=topic,
                    question_type=question_type, word_count=word_count,
                    passage_text=passage_text, stem=stem,
                    options_json=opts_json, answer=answer,
                    explanation=explanation, source_line=source_line,
                    created_at=now, updated_at=now,
                ))
                return int(res.inserted_primary_key[0])
            except IntegrityError:
                conn.execute(
                    update(t_reading_passages)
                    .where(
                        t_reading_passages.c.section == section,
                        t_reading_passages.c.set_id == set_id,
                        t_reading_passages.c.qid == qid,
                    )
                    .values(
                        passage_number=passage_number, title=title, topic=topic,
                        question_type=question_type, word_count=word_count,
                        passage_text=passage_text, stem=stem,
                        options_json=opts_json, answer=answer,
                        explanation=explanation, source_line=source_line,
                        updated_at=now,
                    )
                )
                row = conn.execute(
                    select(t_reading_passages.c.id)
                    .where(
                        t_reading_passages.c.section == section,
                        t_reading_passages.c.set_id == set_id,
                        t_reading_passages.c.qid == qid,
                    )
                ).fetchone()
                return int(row[0]) if row else -1

    def get_passage(self, question_id: int) -> Optional[dict]:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t_reading_passages)
                .where(t_reading_passages.c.id == int(question_id))
            ).fetchone()
        if row is None:
            return None
        d = dict(row._mapping)
        if d.get("options_json"):
            try:
                d["options"] = json.loads(d["options_json"])
            except Exception:
                d["options"] = []
        else:
            d["options"] = None
        return d

    def list_sections_with_counts(self) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT section, COUNT(DISTINCT set_id) AS total_sets, "
                "COUNT(*) AS total_passages FROM reading_passages "
                "GROUP BY section ORDER BY section"
            )).fetchall()
        return [
            {
                "section": r[0],
                "total_sets": int(r[1]),
                "total_passages": int(r[2]),
            }
            for r in rows
        ]

    def list_sets_by_section(self, section: str) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT set_id, MIN(passage_number) AS first_passage, "
                "COUNT(*) AS question_count, MIN(title) AS first_title, "
                "MIN(topic) AS first_topic "
                "FROM reading_passages WHERE section = :sec "
                "GROUP BY set_id ORDER BY set_id"
            ), {"sec": section}).fetchall()
        return [
            {
                "set_id": int(r[0]),
                "section": section,
                "first_passage": int(r[1] or 1),
                "question_count": int(r[2]),
                "title": r[3] or "",
                "topic": r[4] or "",
            }
            for r in rows
        ]

    def list_passages_by_set(self, section: str, set_id: int) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(t_reading_passages)
                .where(
                    t_reading_passages.c.section == section,
                    t_reading_passages.c.set_id == set_id,
                )
                .order_by(t_reading_passages.c.qid)
            ).fetchall()
        items = []
        for row in rows:
            d = dict(row._mapping)
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
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT COUNT(*) FROM reading_passages")
            ).fetchone()
        return int(row[0])

    def record_attempt(
        self,
        user_id: int,
        question_id: int,
        user_answer: str,
        is_correct: bool,
        duration_sec: float = 0.0,
    ) -> int:
        with self._engine.begin() as conn:
            res = conn.execute(insert(t_reading_attempts).values(
                user_id=user_id, question_id=question_id,
                user_answer=user_answer,
                is_correct=1 if is_correct else 0,
                duration_sec=duration_sec,
                created_at=datetime.now(),
            ))
        return int(res.inserted_primary_key[0])

    def list_user_attempts(
        self,
        user_id: int,
        page: int = 1,
        size: int = 20,
        section: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        where = ["a.user_id = :uid"]
        params: dict[str, Any] = {"uid": user_id}
        if section is not None:
            where.append("p.section = :sec")
            params["sec"] = section
        where_sql = " AND ".join(where)
        with self._engine.connect() as conn:
            total = conn.execute(text(
                f"SELECT COUNT(*) FROM reading_attempts a "
                f"LEFT JOIN reading_passages p ON a.question_id = p.id "
                f"WHERE {where_sql}"
            ), params).scalar() or 0
            rows = conn.execute(text(
                f"""SELECT a.id, a.user_id, a.question_id, a.user_answer,
                          a.is_correct, a.duration_sec, a.created_at,
                          p.section AS section, p.set_id, p.qid,
                          p.title, p.question_type
                   FROM reading_attempts a
                   LEFT JOIN reading_passages p ON a.question_id = p.id
                   WHERE {where_sql}
                   ORDER BY a.created_at DESC
                   LIMIT :limit OFFSET :offset"""
            ), {**params, "limit": int(size),
                "offset": max(0, (page - 1) * size)}).fetchall()
        return [dict(r._mapping) for r in rows], int(total)

    def get_user_stats(self, user_id: int) -> dict:
        with self._engine.connect() as conn:
            total_row = conn.execute(text(
                "SELECT COUNT(*) AS total, SUM(is_correct) AS correct "
                "FROM reading_attempts WHERE user_id = :uid"
            ), {"uid": user_id}).fetchone()
            total = int(total_row[0] or 0)
            correct = int(total_row[1] or 0)
            by_rows = conn.execute(text(
                "SELECT p.section, COUNT(*) AS attempts, "
                "SUM(a.is_correct) AS correct "
                "FROM reading_attempts a "
                "LEFT JOIN reading_passages p ON a.question_id = p.id "
                "WHERE a.user_id = :uid AND p.section IS NOT NULL "
                "GROUP BY p.section ORDER BY p.section"
            ), {"uid": user_id}).fetchall()
        by_section = {}
        for r in by_rows:
            sec = r[0]
            attempts = int(r[1])
            c = int(r[2] or 0)
            by_section[sec] = {
                "attempts": attempts,
                "correct": c,
                "accuracy": round(c / attempts * 100, 1) if attempts > 0 else 0.0,
            }
        return {
            "total_attempts": total,
            "correct_count": correct,
            "accuracy": round(correct / total * 100, 1) if total > 0 else 0.0,
            "by_section": by_section,
        }


class MySQLRepositoryContainer:
    """10 个 MySQL Repository 的容器(v3.8 新增 2 个)。

    与 SQLite 容器相比，MySQL 容器只持有一个 SQLAlchemy Engine：
    - 业务表（learning_records / personal_vocab / ...）和共享缓存表
      （vocab_cache / cache_meta / users）都在同一库 ietls_learn_online 里
    - 容器负责 Engine 的生命周期（构造时创建、close() 时释放）
    - Service 层拿到 container 后，对 learning / personal_vocab / ... 的调用方式
      与 SQLite 端完全一致，只是背后换成 SQLAlchemy Core
    """

    def __init__(self, connection_url: Optional[str] = None) -> None:
        from sqlalchemy import create_engine
        if connection_url is None:
            connection_url = _build_mysql_url()
        self._engine: Engine = create_engine(
            connection_url,
            pool_pre_ping=True,   # 防止长连接被 MySQL 主动断开
            pool_recycle=3600,    # 1 小时回收一次
            future=True,
        )

        self.learning = MySQLLearningRepository(self._engine)
        self.personal_vocab = MySQLPersonalVocabRepository(self._engine)
        self.exam = MySQLExamRepository(self._engine)
        self.grade = MySQLGradeRepository(self._engine)
        self.typing = MySQLTypingRepository(self._engine)
        self.focus_sessions = MySQLFocusSessionRepository(self._engine)
        self.user = MySQLUserRepository(self._engine)
        self.vocab_cache = MySQLVocabCacheRepository(self._engine)
        # v3.7 P1 口语对练历史仓储
        self.speaking_practice = MySQLSpeakingPracticeRepository(self._engine)
        # v3.7 P2 真·听力题库仓储
        self.listening_practice = MySQLListeningPracticeRepository(self._engine)
        # v3.8 P3.1 备考资源广场
        self.prep_resource = MySQLPrepResourceRepository(self._engine)
        # v3.8 P3.2 Reading 真题题库
        self.reading_practice = MySQLReadingPracticeRepository(self._engine)

    def close(self) -> None:
        self._engine.dispose()


def create_mysql_repositories(connection_url: Optional[str] = None) -> MySQLRepositoryContainer:
    """创建 MySQLRepositoryContainer（W3 阶段便捷函数）。

    Args:
        connection_url: 完整的 SQLAlchemy MySQL URL，例如
            ``mysql+pymysql://user:pwd@host:3306/db?charset=utf8mb4``。
            传 None 时使用默认生产配置（见 ``_build_mysql_url``）。
    """
    return MySQLRepositoryContainer(connection_url=connection_url)


__all__ = [
    "MySQLLearningRepository",
    "MySQLPersonalVocabRepository",
    "MySQLExamRepository",
    "MySQLGradeRepository",
    "MySQLVocabCacheRepository",
    "MySQLUserRepository",
    "MySQLSpeakingPracticeRepository",
    "MySQLListeningPracticeRepository",
    "MySQLPrepResourceRepository",
    "MySQLReadingPracticeRepository",
    "MySQLRepositoryContainer",
    "create_mysql_repositories",
    "REVIEW_INTERVALS",
    "DEFAULT_MYSQL_HOST",
    "DEFAULT_MYSQL_PORT",
    "DEFAULT_MYSQL_USER",
    "DEFAULT_MYSQL_PASSWORD",
    "DEFAULT_MYSQL_DATABASE",
    "DEFAULT_MYSQL_CHARSET",
]
