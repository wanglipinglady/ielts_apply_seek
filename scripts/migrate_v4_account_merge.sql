-- ============================================================
-- v4 schema migration: 主动合并 + 跨端登录
-- 日期：2026-10-16
-- 背景：V1 方案：双轨制 + 用户主动合并占位账号到老账号
-- 影响表：users (新增字段) + 新表 user_merge_log
-- 回滚：见文件末尾的回滚 SQL
-- ============================================================

-- 1. users 表加字段（已存在的字段不动）
--    - pc_logged_in_at: PC 端首次登录时间，NULL = 未登录过 PC 端
--    - email_verified: 邮箱是否已验证（合并时需要校验）
ALTER TABLE users
  ADD COLUMN pc_logged_in_at DATETIME NULL COMMENT 'PC端首次登录时间，NULL=未登录过PC端'
    AFTER last_login_at,
  ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 0 COMMENT '邮箱是否已验证（合并老账号时为1）'
    AFTER pc_logged_in_at,
  ADD INDEX idx_users_pc_login (pc_logged_in_at);

-- 2. 创建合并审计表（防误操作 + 留痕）
CREATE TABLE IF NOT EXISTS user_merge_log (
  id INT PRIMARY KEY AUTO_INCREMENT,
  from_user_id INT NOT NULL COMMENT '被合并的占位账号 id（合并后已删除）',
  to_user_id INT NOT NULL COMMENT '合并到的老账号 id',
  merged_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  merge_type VARCHAR(32) NOT NULL DEFAULT 'wechat_to_email' COMMENT '合并类型，预留扩展',
  from_data_backup JSON NULL COMMENT '占位账号的原始数据快照（防误操作回滚）',
  from_user_vocab_count INT NULL COMMENT '迁移前占位账号的单词数',
  to_user_vocab_count INT NULL COMMENT '迁移前老账号的单词数',
  INDEX idx_merge_log_from (from_user_id),
  INDEX idx_merge_log_to (to_user_id),
  INDEX idx_merge_log_merged_at (merged_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='账号合并审计日志';

-- 3. wechat_openid 字段在之前已经存在并加过唯一索引
--    这里做一次幂等性检查（如果已存在则不报错）
SET @sql = (
  SELECT IF(
    EXISTS(
      SELECT 1 FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'users'
        AND INDEX_NAME = 'ux_users_wechat_openid'
    ),
    'SELECT 1',
    'ALTER TABLE users ADD UNIQUE INDEX ux_users_wechat_openid (wechat_openid)'
  )
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ============================================================
-- 回滚 SQL（如果需要回滚）
-- ============================================================
-- DROP TABLE IF EXISTS user_merge_log;
-- ALTER TABLE users DROP INDEX idx_users_pc_login;
-- ALTER TABLE users DROP COLUMN pc_logged_in_at;
-- ALTER TABLE users DROP COLUMN email_verified;
