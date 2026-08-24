-- scripts/auto/migration_add_wechat_openid.sql
-- v3.9 (2026-08-24) 加 wechat_openid 列（alembic 失败时的回退 SQL）
-- MySQL 8.0+

ALTER TABLE users
  ADD COLUMN wechat_openid VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
  ADD UNIQUE KEY uk_users_wechat_openid (wechat_openid);

-- 验证
SHOW COLUMNS FROM users LIKE 'wechat_openid%';