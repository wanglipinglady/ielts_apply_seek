#!/usr/bin/env python3
"""IELTS Buddy · MySQL v3 Schema 迁移脚本

背景：
  Phase 2 把 SQLite 业务表加上 updated_at / sync_status 字段以支持增量同步；
  但 MySQL 这边的 schema 还是 v2.2 时的版本，列名不一致、缺列、没有 articles 表。
  本脚本把 MySQL 端 schema 升级到与 SQLite 对齐，让 SyncWorker 能正确 push/pull。

差异清单（迁移前 vs 迁移后）：
  ┌──────────────────┬────────────────────────┬──────────────────────────┐
  │ 表               │ 旧（缺/错）             │ 新（与 SQLite 对齐）      │
  ├──────────────────┼────────────────────────┼──────────────────────────┤
  │ learning_records │ 缺 updated_at/sync_status│ +updated_at +sync_status│
  │ vocab_categories │ 缺 updated_at/sync_status│ +updated_at +sync_status│
  │ exam_sessions    │ session_id, questions_json│ id=session_id, questions │
  │                  │ answers_json            │ answers, +updated_at     │
  │                  │ score(total/accuracy OK) │ +sync_status             │
  │ grade_history    │ 仅 overall_score        │ +task_response_score     │
  │                  │                        │ +coherence_score         │
  │                  │                        │ +lexical_score           │
  │                  │                        │ +grammar_score           │
  │                  │                        │ +error_summary_json      │
  │                  │                        │ +updated_at +sync_status│
  │ articles         │ 表不存在                │ 新建                     │
  │ typing_history   │ 表不存在（v3.6 新增）     │ 新建                     │
  │ focus_sessions   │ 表不存在（v3.6 新增）     │ 新建                     │
  │ listening_questions/listening_attempts│ 表不存在(v3.7 P2 新增)│ 新建│
  └──────────────────┴────────────────────────┴──────────────────────────┘

注意：
  - exam_sessions 重命名 session_id → id 时，MySQL 已经有自增 id 列；这里
    改为把 session_id 改名为 id 不可能（id 已存在）。所以采用：
        新增列 `id_str` 作为同步 key，保留 auto_increment id 作物理主键；
        questions_json → questions (TEXT), answers_json → answers (TEXT)
    SyncWorker 端按 user_id + id_str 作为 conflict_key（运行时再做映射）

  - 同理 grade_history 已经用自增 id，task_type/topic 列已存在。
    缺的是细项分项 + updated_at + sync_status + error_summary_json。

幂等性：
  - 所有 ALTER 都先查 INFORMATION_SCHEMA 再决定是否执行
  - CREATE TABLE IF NOT EXISTS
  - 重复运行不会破坏数据

用法：
  python scripts/migrate_v3_mysql_schema.py
  python scripts/migrate_v3_mysql_schema.py --check-only  # 只检查，不执行
  python scripts/migrate_v3_mysql_schema.py --rollback    # 回滚（实验用，慎用）
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any

try:
    import pymysql
except ImportError:
    print("缺少 pymysql，请先：pip install pymysql cryptography", file=sys.stderr)
    sys.exit(2)


# ---- 默认连接信息 ----
DEFAULT_HOST = "118.190.148.121"
DEFAULT_PORT = 3306
DEFAULT_USER = "remote_user"
DEFAULT_DB = "ietls_learn_online"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="IELTS Buddy MySQL v3 Schema 迁移")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--password",
                   default=os.environ.get("MYSQL_PASSWORD"),
                   help="密码（推荐走环境变量 MYSQL_PASSWORD）")
    p.add_argument("--database", default=DEFAULT_DB)
    p.add_argument("--check-only", action="store_true", help="只检查现状，不执行")
    p.add_argument("--rollback", action="store_true", help="回滚（实验用）")
    return p.parse_args()


# =============================================================
# 工具函数
# =============================================================


def get_conn(args) -> pymysql.Connection:
    return pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
        charset="utf8mb4",
        connect_timeout=5,
        autocommit=False,
    )


def has_column(cur, table: str, column: str) -> bool:
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = DATABASE()
             AND table_name = %s AND column_name = %s""",
        (table, column),
    )
    return cur.fetchone()[0] > 0


def has_table(cur, table: str) -> bool:
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.tables
           WHERE table_schema = DATABASE() AND table_name = %s""",
        (table,),
    )
    return cur.fetchone()[0] > 0


def safe_alter(cur, sql: str, desc: str) -> bool:
    """执行 ALTER，失败也不抛出，返回 True=成功 False=失败"""
    try:
        cur.execute(sql)
        print(f"  ✓ {desc}")
        return True
    except pymysql.MySQLError as e:
        print(f"  ✗ {desc}: {e}")
        return False


# =============================================================
# 现状审计
# =============================================================


def audit(cur) -> dict[str, Any]:
    """返回每张表需要补的列 / 缺失的表的清单。"""
    report: dict[str, Any] = {"tables_missing": [], "columns_missing": {}}

    # articles 必须存在
    if not has_table(cur, "articles"):
        report["tables_missing"].append("articles")

    # typing_history 必须存在（v3.6 加入 SYNC_TABLES）
    if not has_table(cur, "typing_history"):
        report["tables_missing"].append("typing_history")

    # focus_sessions 必须存在（v3.6 加入 SYNC_TABLES,番茄钟）
    if not has_table(cur, "focus_sessions"):
        report["tables_missing"].append("focus_sessions")

    # speaking_practice_records 必须存在（v3.7 P1 口语对练加入 SYNC_TABLES）
    if not has_table(cur, "speaking_practice_records"):
        report["tables_missing"].append("speaking_practice_records")
    # listening_questions / listening_attempts（v3.7 P2 真·听力题库）
    if not has_table(cur, "listening_questions"):
        report["tables_missing"].append("listening_questions")
    if not has_table(cur, "listening_attempts"):
        report["tables_missing"].append("listening_attempts")

    # 各表的必填列
    expected_columns = {
        "personal_vocab": ["updated_at", "sync_status"],
        "learning_records": ["updated_at", "sync_status"],
        "vocab_categories": ["updated_at", "sync_status"],
        "grade_history": [
            "task_response_score", "coherence_score",
            "lexical_score", "grammar_score", "error_summary_json",
            "updated_at", "sync_status",
        ],
        # exam_sessions 比较特殊，列名要重命名 / 新增
        "exam_sessions": [
            "questions", "answers", "updated_at", "sync_status",
            # 注：duration / weak_words / band_breakdown 是 SQLite 独有，
            # sync 时按列名匹配，多余列在 sync 端会被忽略
        ],
    }

    for table, cols in expected_columns.items():
        missing = [c for c in cols if not has_column(cur, table, c)]
        if missing:
            report["columns_missing"][table] = missing

    return report


# =============================================================
# DDL 变更
# =============================================================


def add_articles_table(cur) -> None:
    print("== 创建 articles 表 ==")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id                  BIGINT          NOT NULL AUTO_INCREMENT,
            user_id             BIGINT          NOT NULL DEFAULT 1,
            title               VARCHAR(512)    NULL,
            source_text         MEDIUMTEXT      NOT NULL,
            translation         MEDIUMTEXT      NULL,
            word_count          INT             NOT NULL DEFAULT 0,
            diff_words_json     MEDIUMTEXT      NULL,
            translation_source  VARCHAR(32)     NOT NULL DEFAULT 'llm',
            analysis_source     VARCHAR(32)     NOT NULL DEFAULT 'fallback',
            created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME        NOT NULL
                                DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
            sync_status         VARCHAR(16)     NOT NULL DEFAULT 'synced',
            PRIMARY KEY (id),
            KEY idx_articles_user_created (user_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COMMENT='文章翻译记录'
        """
    )
    print("  ✓ articles 已创建")


def add_typing_history_table(cur) -> None:
    """v3.6 新增：机考打字练习记录表。

    跨设备同步 v3.6 修复后，typing_history 已被加入 SYNC_TABLES，
    但生产 MySQL 上从来没有这张表 —— pull 直接报 1146 "Table doesn't exist"。
    本函数幂等建表，schema 与 SQLite / mysql_repo.t_typing_history 对齐。
    """
    print("== 创建 typing_history 表 ==")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS typing_history (
            id              BIGINT          NOT NULL AUTO_INCREMENT,
            user_id         BIGINT          NOT NULL DEFAULT 1,
            mode            VARCHAR(16)     NOT NULL DEFAULT 'words',
            prompt_text     MEDIUMTEXT      NOT NULL,
            typed_text      MEDIUMTEXT      NULL,
            duration_sec    INT             NOT NULL DEFAULT 0,
            wpm             DECIMAL(6,2)    NOT NULL DEFAULT 0,
            accuracy        DECIMAL(5,4)    NOT NULL DEFAULT 0,
            error_count     INT             NOT NULL DEFAULT 0,
            total_chars     INT             NOT NULL DEFAULT 0,
            completed       TINYINT(1)      NOT NULL DEFAULT 1,
            result_json     MEDIUMTEXT      NOT NULL,
            created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME        NOT NULL
                                DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
            sync_status     VARCHAR(16)     NOT NULL DEFAULT 'synced',
            PRIMARY KEY (id),
            KEY idx_th_user_created (user_id, created_at),
            KEY idx_th_user_mode (user_id, mode)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COMMENT='机考打字练习记录'
        """
    )
    print("  ✓ typing_history 已创建")


def add_focus_sessions_table(cur) -> None:
    """v3.6 新增：番茄钟专注会话表。

    与 typing_history 同样问题：focus_sessions 被加进 SYNC_TABLES 后，
    生产 MySQL 没建表 → pull 直接 1146。本函数幂等建表。
    """
    print("== 创建 focus_sessions 表 ==")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS focus_sessions (
            id              BIGINT          NOT NULL AUTO_INCREMENT,
            user_id         BIGINT          NOT NULL DEFAULT 1,
            activity        VARCHAR(32)     NOT NULL DEFAULT 'other',
            planned_sec     INT             NOT NULL DEFAULT 1500,
            duration_sec    INT             NOT NULL DEFAULT 0,
            interrupted     TINYINT(1)      NOT NULL DEFAULT 0,
            note            MEDIUMTEXT      NULL,
            started_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ended_at        DATETIME        NULL,
            created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME        NOT NULL
                                DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
            sync_status     VARCHAR(16)     NOT NULL DEFAULT 'synced',
            PRIMARY KEY (id),
            KEY idx_fs_user_started (user_id, started_at),
            KEY idx_fs_user_activity (user_id, activity)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COMMENT='番茄钟专注会话'
        """
    )
    print("  ✓ focus_sessions 已创建")


def add_speaking_practice_records_table(cur) -> None:
    """v3.7 P1 新增：口语对练历史表。

    与 focus_sessions 同问题：speaking_practice_records 加入 SYNC_TABLES 后，
    生产 MySQL 没建表 → pull 直接 1146。本函数幂等建表。
    """
    print("== 创建 speaking_practice_records 表 ==")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS speaking_practice_records (
            id                  BIGINT          NOT NULL AUTO_INCREMENT,
            user_id             BIGINT          NOT NULL,
            session_id          VARCHAR(64)     NOT NULL,
            part                TINYINT         NOT NULL,
            topic_id            INT             NULL,
            topic_name          VARCHAR(128)    NOT NULL DEFAULT '',
            question            TEXT            NOT NULL,
            audio_path          VARCHAR(512)    NULL,
            audio_duration_sec  DECIMAL(8,2)    NOT NULL DEFAULT 0,
            audio_mime          VARCHAR(64)     NOT NULL DEFAULT 'audio/webm',
            transcript          MEDIUMTEXT      NOT NULL,
            transcript_tokens   MEDIUMTEXT      NULL,
            llm_scores          MEDIUMTEXT      NULL,
            llm_word_errors     MEDIUMTEXT      NULL,
            llm_grammar_errors  MEDIUMTEXT      NULL,
            llm_highlights      MEDIUMTEXT      NULL,
            llm_suggestions     MEDIUMTEXT      NULL,
            whisper_model       VARCHAR(32)     NOT NULL DEFAULT 'small.en',
            used_core_ml        TINYINT(1)      NOT NULL DEFAULT 1,
            score_fallback      TINYINT(1)      NOT NULL DEFAULT 0,
            created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME        NOT NULL
                                    DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP,
            sync_status         VARCHAR(16)     NOT NULL DEFAULT 'synced',
            PRIMARY KEY (id),
            UNIQUE KEY uk_spr_session (session_id),
            KEY idx_spr_user_created (user_id, created_at),
            KEY idx_spr_user_part (user_id, part)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COMMENT='口语对练历史（v3.7 P1）'
        """
    )
    print("  ✓ speaking_practice_records 已创建")


def add_listening_questions_table(cur) -> None:
    """v3.7 P2 新增:真·听力题库题库表。

    跨用户共享,不需要 SYNC_TABLES。
    """
    print("== 创建 listening_questions 表 ==")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS listening_questions (
            id                    BIGINT          NOT NULL AUTO_INCREMENT,
            section               TINYINT         NOT NULL,
            set_id                INT             NOT NULL,
            qid                   INT             NOT NULL,
            scenario              VARCHAR(128)    NOT NULL DEFAULT '',
            question_type         VARCHAR(32)     NOT NULL,
            stem                  TEXT            NOT NULL,
            options_json          MEDIUMTEXT      NULL,
            answer                VARCHAR(256)    NOT NULL,
            explanation           MEDIUMTEXT      NOT NULL,
            transcript            MEDIUMTEXT      NOT NULL,
            audio_path            VARCHAR(512)    NULL,
            audio_generated_at    DATETIME        NULL,
            created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                  ON UPDATE CURRENT_TIMESTAMP,
            sync_status           VARCHAR(16)     NOT NULL DEFAULT 'synced',
            PRIMARY KEY (id),
            UNIQUE KEY uk_lq_section_set_qid (section, set_id, qid),
            KEY idx_lq_section_set (section, set_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COMMENT='真·听力题库题库（v3.7 P2）'
        """
    )
    print("  ✓ listening_questions 已创建")


def add_listening_attempts_table(cur) -> None:
    """v3.7 P2 新增:真·听力答题记录表。

    纳入 SYNC_TABLES(每个用户有独立答题记录)。
    """
    print("== 创建 listening_attempts 表 ==")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS listening_attempts (
            id                    BIGINT          NOT NULL AUTO_INCREMENT,
            user_id               BIGINT          NOT NULL,
            question_id           BIGINT          NOT NULL,
            user_answer           VARCHAR(256)    NOT NULL,
            is_correct            TINYINT(1)      NOT NULL DEFAULT 0,
            duration_sec          DECIMAL(8,2)    NOT NULL DEFAULT 0,
            played_count          INT             NOT NULL DEFAULT 1,
            created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                  ON UPDATE CURRENT_TIMESTAMP,
            sync_status           VARCHAR(16)     NOT NULL DEFAULT 'synced',
            PRIMARY KEY (id),
            KEY idx_la_user_created (user_id, created_at),
            KEY idx_la_user_q (user_id, question_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COMMENT='真·听力答题记录（v3.7 P2）'
        """
    )
    print("  ✓ listening_attempts 已创建")


def add_prep_resources_table(cur) -> None:
    """v3.8 P3.1 新增:备考资源广场表。

    跨用户共享元数据;不进 SYNC_TABLES。
    """
    print("== 创建 prep_resources 表 ==")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prep_resources (
            id                    BIGINT          NOT NULL AUTO_INCREMENT,
            title                 VARCHAR(256)    NOT NULL,
            bv_id                 VARCHAR(32)     NOT NULL,
            url                   VARCHAR(512)    NOT NULL,
            author_name           VARCHAR(64)     NOT NULL,
            author_uid            BIGINT          NULL,
            uploader_name         VARCHAR(64)     NOT NULL DEFAULT '',
            uploader_uid          BIGINT          NULL,
            skill                 VARCHAR(16)     NOT NULL,
            video_type            VARCHAR(16)     NOT NULL,
            level                 VARCHAR(16)     NOT NULL,
            method_summary        TEXT            NOT NULL,
            source_status         VARCHAR(32)     NOT NULL DEFAULT 'verified_repost',
            publish_date          DATE            NULL,
            duration_sec          INT             NOT NULL DEFAULT 0,
            outdated_risk         VARCHAR(16)     NOT NULL DEFAULT 'low',
            format_compatible     VARCHAR(16)     NOT NULL DEFAULT 'computer',
            computer_delivery_only TINYINT(1)     NOT NULL DEFAULT 1,
            is_featured           TINYINT(1)      NOT NULL DEFAULT 0,
            recommend_score       DECIMAL(4,2)    NOT NULL DEFAULT 0.0,
            sort_order            INT             NOT NULL DEFAULT 100,
            related_action_url    VARCHAR(256)    NULL,
            related_action_label  VARCHAR(64)     NULL,
            created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                  ON UPDATE CURRENT_TIMESTAMP,
            sync_status           VARCHAR(16)     NOT NULL DEFAULT 'synced',
            PRIMARY KEY (id),
            UNIQUE KEY uk_pr_bv_id (bv_id),
            KEY idx_pr_skill (skill),
            KEY idx_pr_score (recommend_score),
            KEY idx_pr_author (author_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COMMENT='备考资源广场（v3.8 P3.1）'
        """
    )
    print("  ✓ prep_resources 已创建")


def add_reading_passages_table(cur) -> None:
    """v3.8 P3.2 新增:Reading 真题题库表。

    LLM 出题;跨用户共享题库,不进 SYNC_TABLES。
    """
    print("== 创建 reading_passages 表 ==")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reading_passages (
            id                    BIGINT          NOT NULL AUTO_INCREMENT,
            section               VARCHAR(16)     NOT NULL,
            set_id                INT             NOT NULL,
            qid                   INT             NOT NULL,
            passage_number        SMALLINT        NOT NULL,
            title                 VARCHAR(256)    NOT NULL,
            topic                 VARCHAR(128)    NOT NULL DEFAULT '',
            question_type         VARCHAR(32)     NOT NULL,
            word_count            INT             NOT NULL DEFAULT 0,
            passage_text          TEXT            NOT NULL,
            stem                  TEXT            NOT NULL,
            options_json          TEXT            NULL,
            answer                VARCHAR(256)    NOT NULL,
            explanation           TEXT            NOT NULL DEFAULT '',
            source_line           INT             NULL,
            created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                  ON UPDATE CURRENT_TIMESTAMP,
            sync_status           VARCHAR(16)     NOT NULL DEFAULT 'synced',
            PRIMARY KEY (id),
            UNIQUE KEY uk_rp_section_set_qid (section, set_id, qid),
            KEY idx_rp_section_set (section, set_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COMMENT='Reading 真题题库（v3.8 P3.2）'
        """
    )
    print("  ✓ reading_passages 已创建")


def add_reading_attempts_table(cur) -> None:
    """v3.8 P3.2 新增:Reading 答题记录表。

    纳入 SYNC_TABLES(每个用户有独立答题记录)。
    """
    print("== 创建 reading_attempts 表 ==")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reading_attempts (
            id                    BIGINT          NOT NULL AUTO_INCREMENT,
            user_id               BIGINT          NOT NULL,
            question_id           BIGINT          NOT NULL,
            user_answer           VARCHAR(256)    NOT NULL,
            is_correct            TINYINT(1)      NOT NULL DEFAULT 0,
            duration_sec          DECIMAL(8,2)    NOT NULL DEFAULT 0,
            created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                                  ON UPDATE CURRENT_TIMESTAMP,
            sync_status           VARCHAR(16)     NOT NULL DEFAULT 'synced',
            PRIMARY KEY (id),
            KEY idx_rat_user_created (user_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COMMENT='Reading 答题记录（v3.8 P3.2）'
        """
    )
    print("  ✓ reading_attempts 已创建")


def upgrade_personal_vocab(cur) -> None:
    print("== 升级 personal_vocab ==")
    # personal_vocab.updated_at 已存在（DEFAULT ON UPDATE）
    # 仅缺 sync_status
    if not has_column(cur, "personal_vocab", "sync_status"):
        safe_alter(
            cur,
            "ALTER TABLE personal_vocab ADD COLUMN sync_status VARCHAR(16) "
            "NOT NULL DEFAULT 'synced'",
            "ADD COLUMN sync_status",
        )
    else:
        print("  · sync_status 已存在，跳过")
    safe_alter(
        cur,
        "CREATE INDEX idx_pv_user_updated ON personal_vocab(user_id, updated_at)",
        "CREATE INDEX idx_pv_user_updated",
    )


def upgrade_learning_records(cur) -> None:
    print("== 升级 learning_records ==")
    if not has_column(cur, "learning_records", "updated_at"):
        safe_alter(
            cur,
            "ALTER TABLE learning_records ADD COLUMN updated_at DATETIME "
            "NOT NULL DEFAULT CURRENT_TIMESTAMP "
            "ON UPDATE CURRENT_TIMESTAMP",
            "ADD COLUMN updated_at",
        )
    else:
        print("  · updated_at 已存在，跳过")
    if not has_column(cur, "learning_records", "sync_status"):
        safe_alter(
            cur,
            "ALTER TABLE learning_records ADD COLUMN sync_status VARCHAR(16) "
            "NOT NULL DEFAULT 'synced'",
            "ADD COLUMN sync_status",
        )
    else:
        print("  · sync_status 已存在，跳过")
    # 加索引
    safe_alter(
        cur,
        "CREATE INDEX idx_lr_user_updated ON learning_records(user_id, updated_at)",
        "CREATE INDEX idx_lr_user_updated",
    )


def upgrade_vocab_categories(cur) -> None:
    print("== 升级 vocab_categories ==")
    if not has_column(cur, "vocab_categories", "updated_at"):
        safe_alter(
            cur,
            "ALTER TABLE vocab_categories ADD COLUMN updated_at DATETIME "
            "NOT NULL DEFAULT CURRENT_TIMESTAMP "
            "ON UPDATE CURRENT_TIMESTAMP",
            "ADD COLUMN updated_at",
        )
    else:
        print("  · updated_at 已存在，跳过")
    if not has_column(cur, "vocab_categories", "sync_status"):
        safe_alter(
            cur,
            "ALTER TABLE vocab_categories ADD COLUMN sync_status VARCHAR(16) "
            "NOT NULL DEFAULT 'synced'",
            "ADD COLUMN sync_status",
        )
    else:
        print("  · sync_status 已存在，跳过")
    safe_alter(
        cur,
        "CREATE INDEX idx_vc_user_updated ON vocab_categories(user_id, updated_at)",
        "CREATE INDEX idx_vc_user_updated",
    )


def upgrade_exam_sessions(cur) -> None:
    """exam_sessions 的列名需要和 SQLite 对齐：
       questions_json → questions
       answers_json   → answers
       score (DECIMAL) 和 SQLite 的 INTEGER score 类型有差异，运行时再 cast
    """
    print("== 升级 exam_sessions ==")

    # 加新列
    if not has_column(cur, "exam_sessions", "questions"):
        safe_alter(
            cur,
            "ALTER TABLE exam_sessions ADD COLUMN questions MEDIUMTEXT NULL",
            "ADD COLUMN questions",
        )
    else:
        print("  · questions 已存在，跳过")

    if not has_column(cur, "exam_sessions", "answers"):
        safe_alter(
            cur,
            "ALTER TABLE exam_sessions ADD COLUMN answers MEDIUMTEXT NULL",
            "ADD COLUMN answers",
        )
    else:
        print("  · answers 已存在，跳过")

    if not has_column(cur, "exam_sessions", "updated_at"):
        safe_alter(
            cur,
            "ALTER TABLE exam_sessions ADD COLUMN updated_at DATETIME "
            "NOT NULL DEFAULT CURRENT_TIMESTAMP "
            "ON UPDATE CURRENT_TIMESTAMP",
            "ADD COLUMN updated_at",
        )
    else:
        print("  · updated_at 已存在，跳过")

    if not has_column(cur, "exam_sessions", "sync_status"):
        safe_alter(
            cur,
            "ALTER TABLE exam_sessions ADD COLUMN sync_status VARCHAR(16) "
            "NOT NULL DEFAULT 'synced'",
            "ADD COLUMN sync_status",
        )
    else:
        print("  · sync_status 已存在，跳过")

    # 数据迁移：questions_json → questions；answers_json → answers
    cur.execute(
        "UPDATE exam_sessions SET questions = questions_json "
        "WHERE questions IS NULL AND questions_json IS NOT NULL"
    )
    print(f"  · questions_json → questions 影响 {cur.rowcount} 行")
    cur.execute(
        "UPDATE exam_sessions SET answers = answers_json "
        "WHERE answers IS NULL AND answers_json IS NOT NULL"
    )
    print(f"  · answers_json → answers 影响 {cur.rowcount} 行")

    # 加索引
    safe_alter(
        cur,
        "CREATE INDEX idx_es_user_updated ON exam_sessions(user_id, updated_at)",
        "CREATE INDEX idx_es_user_updated",
    )


def upgrade_grade_history(cur) -> None:
    print("== 升级 grade_history ==")
    additions = [
        ("task_response_score", "DECIMAL(3,1) NULL"),
        ("coherence_score", "DECIMAL(3,1) NULL"),
        ("lexical_score", "DECIMAL(3,1) NULL"),
        ("grammar_score", "DECIMAL(3,1) NULL"),
        ("error_summary_json", "MEDIUMTEXT NULL"),
        ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
                       "ON UPDATE CURRENT_TIMESTAMP"),
        ("sync_status", "VARCHAR(16) NOT NULL DEFAULT 'synced'"),
    ]
    for col, typedef in additions:
        if not has_column(cur, "grade_history", col):
            safe_alter(
                cur,
                f"ALTER TABLE grade_history ADD COLUMN {col} {typedef}",
                f"ADD COLUMN {col}",
            )
        else:
            print(f"  · {col} 已存在，跳过")
    safe_alter(
        cur,
        "CREATE INDEX idx_gh_user_updated ON grade_history(user_id, updated_at)",
        "CREATE INDEX idx_gh_user_updated",
    )


# =============================================================
# 回滚（实验用）
# =============================================================


def rollback(args) -> None:
    print("⚠️  回滚模式：删除 articles 表 + 移除新增列")
    conn = get_conn(args)
    cur = conn.cursor()

    if has_table(cur, "articles"):
        cur.execute("DROP TABLE articles")
        print("  ✓ DROP TABLE articles")

    for table, cols in [
        ("personal_vocab", ["sync_status"]),
        ("learning_records", ["updated_at", "sync_status"]),
        ("vocab_categories", ["updated_at", "sync_status"]),
        ("exam_sessions", ["questions", "answers", "updated_at", "sync_status"]),
        ("grade_history", [
            "task_response_score", "coherence_score", "lexical_score",
            "grammar_score", "error_summary_json", "updated_at", "sync_status",
        ]),
    ]:
        for col in cols:
            if has_column(cur, table, col):
                cur.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
                print(f"  ✓ DROP COLUMN {table}.{col}")

    conn.commit()
    conn.close()
    print("✓ 回滚完成")


# =============================================================
# 主流程
# =============================================================


def main() -> int:
    args = parse_args()
    if not args.password:
        print("需要 MySQL 密码：--password xxx 或环境变量 MYSQL_PASSWORD",
              file=sys.stderr)
        return 2

    print(f"=== MySQL v3 Schema 迁移 ===")
    print(f"→ 连接 {args.user}@{args.host}:{args.port}/{args.database}")
    conn = get_conn(args)
    cur = conn.cursor()
    print("✓ 连接成功\n")

    if args.rollback:
        rollback(args)
        return 0

    print("【现状审计】")
    report = audit(cur)
    print(f"  缺失表：{report['tables_missing'] or '无'}")
    print(f"  缺失列：")
    for t, cols in report["columns_missing"].items():
        print(f"    {t}: {cols}")
    if not report["tables_missing"] and not report["columns_missing"]:
        print("  ✓ Schema 已对齐，无需迁移")
        conn.close()
        return 0

    if args.check_only:
        print("\n(check-only 模式：未执行迁移)")
        conn.close()
        return 0

    print("\n【开始迁移】")
    try:
        if "articles" in report["tables_missing"]:
            add_articles_table(cur)
        if "typing_history" in report["tables_missing"]:
            add_typing_history_table(cur)
        if "focus_sessions" in report["tables_missing"]:
            add_focus_sessions_table(cur)
        if "speaking_practice_records" in report["tables_missing"]:
            add_speaking_practice_records_table(cur)
        if "listening_questions" in report["tables_missing"]:
            add_listening_questions_table(cur)
        if "listening_attempts" in report["tables_missing"]:
            add_listening_attempts_table(cur)
        if "prep_resources" in report["tables_missing"]:
            add_prep_resources_table(cur)
        if "reading_passages" in report["tables_missing"]:
            add_reading_passages_table(cur)
        if "reading_attempts" in report["tables_missing"]:
            add_reading_attempts_table(cur)
        if "personal_vocab" in report["columns_missing"]:
            upgrade_personal_vocab(cur)
        if "learning_records" in report["columns_missing"]:
            upgrade_learning_records(cur)
        if "vocab_categories" in report["columns_missing"]:
            upgrade_vocab_categories(cur)
        if "exam_sessions" in report["columns_missing"]:
            upgrade_exam_sessions(cur)
        if "grade_history" in report["columns_missing"]:
            upgrade_grade_history(cur)

        conn.commit()
        print("\n✓ 迁移已提交")
    except Exception as e:
        conn.rollback()
        print(f"\n✗ 迁移失败，已回滚：{e}", file=sys.stderr)
        conn.close()
        return 1

    print("\n【迁移后再审计】")
    report2 = audit(cur)
    if report2["tables_missing"] or report2["columns_missing"]:
        print(f"  ⚠️  仍存在缺失项：{report2}")
        conn.close()
        return 1
    print("  ✓ 所有差异已修复")

    conn.close()
    print("\n=== 完成 ===")
    print(f"迁移时间：{datetime.now().isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
