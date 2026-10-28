-- ============================================================
-- v4.0 schema migration: speaking_practice_records.transcript 默认值
-- 日期：2026-10-28
--
-- 背景：
--   代码里 MySQL ORM 声明的是
--     Column("transcript", Text, nullable=False, server_default=text("''"))
--   但生产库的表是更早建的（DESC 显示 `transcript mediumtext NOT NULL`，
--   **没有 DEFAULT**）→ create_practice_record() 先 INSERT 基础字段
--   （不包含 transcript）→ MySQL 报
--     Field 'transcript' doesn't have a default value
--   → 口语对练提交录音直接 500。
--
-- 为什么改类型而不是加 DEFAULT：
--   MySQL 不允许 TEXT/BLOB/JSON 列带默认值：
--     ERROR 1101 (42000): BLOB, TEXT, GEOMETRY or JSON column 'transcript'
--     can't have a default value
--   所以把 MEDIUMTEXT 改成 VARCHAR(16000) —— utf8mb4 下 VARCHAR 的
--   最大字节数是 16383（VARCHAR(65535) 会报
--   "Column length too big for column 'transcript' (max = 16383)"），
--   16000 字符足够放一段口语转写文本，且支持 DEFAULT ''。
--
-- 影响表：speaking_practice_records / listening_questions
-- 回滚：见文件末尾
-- ============================================================

-- 1. speaking_practice_records.transcript：MEDIUMTEXT → VARCHAR(65535) + DEFAULT ''
ALTER TABLE speaking_practice_records
  MODIFY COLUMN transcript VARCHAR(16000) NOT NULL DEFAULT '';

-- 2. listening_questions.transcript：同上
ALTER TABLE listening_questions
  MODIFY COLUMN transcript VARCHAR(16000) NOT NULL DEFAULT '';

-- ============================================================
-- 回滚 SQL（如果需要回滚）
-- ============================================================
-- ALTER TABLE speaking_practice_records
--   MODIFY COLUMN transcript MEDIUMTEXT NOT NULL;
-- ALTER TABLE listening_questions
--   MODIFY COLUMN transcript MEDIUMTEXT NOT NULL;
