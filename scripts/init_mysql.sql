-- =============================================================
-- IELTS Buddy · MySQL 初始化脚本（v2.2 方案落地）
-- 数据库:   ietls_learn_online
-- 字符集:   utf8mb4
-- 引擎:     InnoDB
-- 目标主机: 118.190.148.121:3306
-- 目标账号: remote_user
-- -------------------------------------------------------------
-- 执行方式（任选其一）：
--
--   (1) 命令行
--       mysql -h 118.190.148.121 -P 3306 -u remote_user -p \
--             ietls_learn_online < init_mysql.sql
--
--   (2) 图形化工具（Navicat / DBeaver / MySQL Workbench）
--       连接到 118.190.148.121:3306 → 选库 ietls_learn_online
--       → 打开本文件 → 全选执行
--
-- -------------------------------------------------------------
-- 幂等性：本脚本所有 CREATE/INSERT 使用 IF NOT EXISTS / IGNORE，
--         重复执行不会破坏现有数据。失败请用 DROP DATABASE 重建。
-- =============================================================

SET NAMES utf8mb4;
SET time_zone = '+08:00';
SET FOREIGN_KEY_CHECKS = 0;

-- =============================================================
-- 1. users（统一用户表 — CLI 与 Web 共享同一身份）
-- =============================================================
-- v3 改造：
--   - CLI 与 Web 共用一张 users 表，通过 username 唯一标识一个人
--   - email/password_hash 仅 Web 注册时填写（CLI 登录为 NULL）
--   - 保留原 id 不变以兼容老外键引用
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT          NOT NULL AUTO_INCREMENT,
    username        VARCHAR(64)     NOT NULL,
    email           VARCHAR(255)    NULL,
    password_hash   VARCHAR(255)    NULL,
    display_name    VARCHAR(64)     NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at   DATETIME        NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_users_username (username),
    UNIQUE KEY uk_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='统一用户表（CLI + Web 共用）';

-- 老 users 表无 email/password_hash 列 → 补齐（幂等）
-- 使用存储过程式条件判断的简化版：MySQL 8.0 接受 IF NOT EXISTS 风格需通过 INFORMATION_SCHEMA
-- 这里手工检测：若列不存在则 ALTER（脚本手动跑过一次的标记）
-- 由于 SQL 脚本无控制流，下面由 Python 迁移脚本负责 ALTER。

-- =============================================================
-- 2. learning_records（艾宾浩斯复习核心表）
-- =============================================================
CREATE TABLE IF NOT EXISTS learning_records (
    id              BIGINT          NOT NULL AUTO_INCREMENT,
    user_id         BIGINT          NOT NULL DEFAULT 1,
    word            VARCHAR(128)    NOT NULL,
    word_data       MEDIUMTEXT      NOT NULL,
    memory_level    INT             NOT NULL DEFAULT 0,
    next_review     DATE            NULL,
    learn_count     INT             NOT NULL DEFAULT 0,
    correct_count   INT             NOT NULL DEFAULT 0,
    wrong_count     INT             NOT NULL DEFAULT 0,
    first_learned   DATETIME        NULL,
    last_reviewed   DATETIME        NULL,
    is_starred      TINYINT(1)      NOT NULL DEFAULT 0,
    is_difficult    TINYINT(1)      NOT NULL DEFAULT 0,
    source          VARCHAR(32)     NOT NULL DEFAULT 'builtin',
    PRIMARY KEY (id),
    UNIQUE KEY uk_lr_user_word (user_id, word),
    KEY idx_lr_user_review (user_id, next_review),
    KEY idx_lr_user_level (user_id, memory_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学习记录 + 艾宾浩斯复习';

-- =============================================================
-- 3. personal_vocab（个人词库）
-- =============================================================
CREATE TABLE IF NOT EXISTS personal_vocab (
    id              BIGINT          NOT NULL AUTO_INCREMENT,
    user_id         BIGINT          NOT NULL DEFAULT 1,
    word            VARCHAR(128)    NOT NULL,
    phonetic        VARCHAR(128)    NULL,
    meaning         VARCHAR(512)    NULL,
    pos             VARCHAR(16)     NULL,
    band            INT             NULL,
    topic           VARCHAR(64)     NULL,
    example         TEXT            NULL,
    example_cn      TEXT            NULL,
    note            TEXT            NULL,
    source          VARCHAR(32)     NOT NULL DEFAULT 'manual',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_pv_user_word (user_id, word),
    KEY idx_pv_user_source (user_id, source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='个人词库';

-- =============================================================
-- 4. vocab_categories（个人词库分类）
-- =============================================================
CREATE TABLE IF NOT EXISTS vocab_categories (
    id              BIGINT          NOT NULL AUTO_INCREMENT,
    user_id         BIGINT          NOT NULL DEFAULT 1,
    name            VARCHAR(64)     NOT NULL,
    description     VARCHAR(512)    NULL,
    is_system       TINYINT(1)      NOT NULL DEFAULT 0,
    word_count      INT             NOT NULL DEFAULT 0,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_vc_user_name (user_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='个人词库分类';

-- =============================================================
-- 5. vocab_category_words（分类-词条关联）
-- =============================================================
CREATE TABLE IF NOT EXISTS vocab_category_words (
    id              BIGINT          NOT NULL AUTO_INCREMENT,
    user_id         BIGINT          NOT NULL DEFAULT 1,
    category_id     BIGINT          NOT NULL,
    word            VARCHAR(128)    NOT NULL,
    added_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_vcw_user_cat_word (user_id, category_id, word),
    KEY idx_vcw_user_word (user_id, word)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分类-词条关联';

-- =============================================================
-- 6. exam_sessions（模拟考试会话）
-- =============================================================
CREATE TABLE IF NOT EXISTS exam_sessions (
    id              BIGINT          NOT NULL AUTO_INCREMENT,
    user_id         BIGINT          NOT NULL DEFAULT 1,
    session_id      VARCHAR(32)     NOT NULL,
    questions_json  MEDIUMTEXT      NOT NULL,
    answers_json    MEDIUMTEXT      NULL,
    time_limit      INT             NOT NULL DEFAULT 20,
    started_at      DATETIME        NOT NULL,
    finished_at     DATETIME        NULL,
    band_filter     INT             NULL,
    score           DECIMAL(5,2)    NULL,
    total           INT             NULL,
    accuracy        DECIMAL(5,2)    NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_es_user_session (user_id, session_id),
    KEY idx_es_user_started (user_id, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模拟考试会话';

-- =============================================================
-- 7. grade_history（AI 写作批改历史）
-- =============================================================
CREATE TABLE IF NOT EXISTS grade_history (
    id              BIGINT          NOT NULL AUTO_INCREMENT,
    user_id         BIGINT          NOT NULL DEFAULT 1,
    overall_score   DECIMAL(3,1)    NULL,
    task_type       VARCHAR(32)     NULL,
    topic           VARCHAR(256)    NULL,
    essay_text      MEDIUMTEXT      NULL,
    result_json     MEDIUMTEXT      NOT NULL,
    graded_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_gh_user_graded (user_id, graded_at),
    KEY idx_gh_user_task (user_id, task_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 写作批改历史';

-- =============================================================
-- 8. vocab_cache（大词库缓存）
-- =============================================================
CREATE TABLE IF NOT EXISTS vocab_cache (
    word            VARCHAR(128)    NOT NULL,
    band            INT             NOT NULL,
    topic           VARCHAR(64)     NOT NULL,
    payload_json    MEDIUMTEXT      NOT NULL,
    PRIMARY KEY (word),
    KEY idx_vc_band (band),
    KEY idx_vc_topic (topic)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='大词库缓存';

-- =============================================================
-- 8.5 typing_history（机考打字练习记录；v3.6 新增,纳入 SYNC_TABLES）
-- =============================================================
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
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
    sync_status     VARCHAR(16)     NOT NULL DEFAULT 'synced',
    PRIMARY KEY (id),
    KEY idx_th_user_created (user_id, created_at),
    KEY idx_th_user_mode (user_id, mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='机考打字练习记录';

-- =============================================================
-- 8.6 focus_sessions（番茄钟专注会话；v3.6 新增,纳入 SYNC_TABLES）
-- =============================================================
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
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
    sync_status     VARCHAR(16)     NOT NULL DEFAULT 'synced',
    PRIMARY KEY (id),
    KEY idx_fs_user_started (user_id, started_at),
    KEY idx_fs_user_activity (user_id, activity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='番茄钟专注会话';

-- =============================================================
-- 8.7 speaking_practice_records（口语对练历史;v3.7 新增,纳入 SYNC_TABLES）
-- PRD: docs/web-mvp/plans/phase-8-speaking-practice.md §6
-- 字段注释：所有 LLM 输出为 JSON 字符串（暂不用 MySQL JSON 类型,方便 SQLite 同步对齐）
-- audio_path 7 天清理后会被置 NULL(物理文件删除)
-- =============================================================
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
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                          ON UPDATE CURRENT_TIMESTAMP,
    sync_status         VARCHAR(16)     NOT NULL DEFAULT 'synced',
    PRIMARY KEY (id),
    UNIQUE KEY uk_spr_session (session_id),
    KEY idx_spr_user_created (user_id, created_at),
    KEY idx_spr_user_part (user_id, part)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='口语对练历史（v3.7 P1）';

-- =============================================================
-- 8.8 listening_questions（真·听力题库题库;v3.7 P2 新增）
-- PRD: docs/web-mvp/plans/phase-9-listening-practice.md §6
-- 题库由 LLM 出题 + TTS 合成音频,跨用户共享,不进 SYNC_TABLES。
-- audio_path 30 天清理后会被置 NULL(物理文件删除,下次访问会重新合成)
-- =============================================================
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='真·听力题库题库（v3.7 P2）';

-- =============================================================
-- 8.9 listening_attempts（真·听力答题记录;v3.7 P2 新增,纳入 SYNC_TABLES）
-- PRD: docs/web-mvp/plans/phase-9-listening-practice.md §6
-- =============================================================
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='真·听力答题记录（v3.7 P2）';

-- =============================================================
-- 8.10 prep_resources（备考资源广场;v3.8 P3.1 新增）
-- PRD: docs/web-mvp/plans/phase-10-reading-and-resources.md §5.5
-- 跨用户共享元数据;不进 SYNC_TABLES。
-- =============================================================
CREATE TABLE IF NOT EXISTS prep_resources (
    id                    BIGINT          NOT NULL AUTO_INCREMENT,
    title                 VARCHAR(256)    NOT NULL,
    bv_id                 VARCHAR(32)     NOT NULL,
    url                   VARCHAR(512)    NOT NULL,
    author_name           VARCHAR(64)     NOT NULL,
    author_uid            BIGINT          NULL,
    uploader_name         VARCHAR(64)     NOT NULL DEFAULT '',
    uploader_uid          BIGINT          NULL,
    skill                 VARCHAR(16)     NOT NULL,  -- listening | reading | speaking | writing | general
    video_type            VARCHAR(16)     NOT NULL,  -- methodology | planning | tips | pitfalls | mock | vocab
    level                 VARCHAR(16)     NOT NULL,  -- 0-5 | 5-6 | 6.5-7 | 7+
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='备考资源广场（v3.8 P3.1）';

-- =============================================================
-- 8.11 reading_passages（Reading 真题题库;v3.8 P3.2 新增）
-- PRD: docs/web-mvp/plans/phase-10-reading-and-resources.md §5.1
-- LLM 出题;跨用户共享题库,不进 SYNC_TABLES。
-- =============================================================
CREATE TABLE IF NOT EXISTS reading_passages (
    id                    BIGINT          NOT NULL AUTO_INCREMENT,
    section               VARCHAR(16)     NOT NULL,  -- easy | medium | hard | academic
    set_id                INT             NOT NULL,
    qid                   INT             NOT NULL,
    passage_number        SMALLINT        NOT NULL,
    title                 VARCHAR(256)    NOT NULL,
    topic                 VARCHAR(128)    NOT NULL DEFAULT '',
    question_type         VARCHAR(32)     NOT NULL,  -- tfng | multiple_choice | matching | summary | sentence_completion
    word_count            INT             NOT NULL DEFAULT 0,
    passage_text          TEXT            NOT NULL,
    stem                  TEXT            NOT NULL,
    options_json          TEXT            NULL,
    answer                VARCHAR(256)    NOT NULL,
    -- MySQL 限制：TEXT/BLOB/JSON 列不能有 DEFAULT 值；解释允许为空，故改为 NULL
    explanation           TEXT            NULL,
    source_line           INT             NULL,
    created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                              ON UPDATE CURRENT_TIMESTAMP,
    sync_status           VARCHAR(16)     NOT NULL DEFAULT 'synced',
    PRIMARY KEY (id),
    UNIQUE KEY uk_rp_section_set_qid (section, set_id, qid),
    KEY idx_rp_section_set (section, set_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Reading 真题题库（v3.8 P3.2）';

-- =============================================================
-- 8.12 reading_attempts（Reading 答题记录;v3.8 P3.2 新增,纳入 SYNC_TABLES）
-- =============================================================
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Reading 答题记录（v3.8 P3.2）';

-- =============================================================
-- 9. cache_meta（缓存元数据）
-- =============================================================
CREATE TABLE IF NOT EXISTS cache_meta (
    key_name        VARCHAR(64)     NOT NULL,
    value           VARCHAR(256)    NOT NULL,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (key_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='缓存元数据';

-- =============================================================
-- 11. 初始化数据
-- =============================================================

-- 11.1 系统分类种子（3-A 决策）
-- user_id=0 这一份是"模板"，业务层在用户首登时复制给具体用户
-- UNIQUE KEY (user_id, name) 保证每个用户只有一份同名分类
INSERT IGNORE INTO vocab_categories (user_id, name, description, is_system) VALUES
    (0, 'favorites',  '收藏夹',  1),
    (0, 'mistakes',   '错词本',  1);

-- 10.2 缓存元数据初始值
INSERT IGNORE INTO cache_meta (key_name, value) VALUES
    ('master_json_mtime',  '0'),
    ('curated_json_mtime', '0');

-- =============================================================
-- 12. SYNC_TABLES 同步列表自检（仅作为文档注释）
-- =============================================================
-- 共 14 张业务表:
--   users / learning_records / personal_vocab / vocab_categories
--   vocab_category_words / exam_sessions / grade_history
--   typing_history / focus_sessions / articles / speaking_practice_records
--   listening_attempts / reading_attempts
-- 注：listening_questions / prep_resources / reading_passages 不进 SYNC_TABLES
--   （跨用户共享题库/资源元数据,不需要同步）
-- 详见 docs/online_local_技术详解.md §3.2 SYNC_TABLES

SET FOREIGN_KEY_CHECKS = 1;

-- =============================================================
-- 执行完毕。建议用以下语句验证：
-- =============================================================
-- SHOW TABLES;
--   -- 应看到 11 张业务表 + 2 张种子/元数据行
--
-- SELECT COUNT(*) AS users_count FROM users;
--   -- 期望 0（首登时才会创建）
--
-- SELECT id, user_id, name, is_system FROM vocab_categories;
--   -- 期望两行种子：
--   --   id=1, user_id=0, name=favorites, is_system=1
--   --   id=2, user_id=0, name=mistakes,  is_system=1
--
-- SELECT * FROM cache_meta;
--   -- 期望两行：master_json_mtime=0, curated_json_mtime=0
