# Web 端数据持久化说明

## 概述

Web 端账号、个人词库、学习记录、模拟考试、批改结果等**全部数据统一持久化**，重启服务不会丢失。

## 存储路径

### 默认模式（SQLite）

| 数据 | 存储位置 |
|------|----------|
| Web 用户（email + password_hash） | `~/.ielts-buddy/web_data.db` 的 `web_users` 表 |
| 业务数据（个人词库 / 学习记录 / 模拟考试等） | `~/.ielts-buddy/web_data.db` 的对应表 |
| 词库缓存 | `~/.ielts-buddy/vocab_cache.db` |

**关键**：Web 用户和业务数据**共存于同一个 SQLite 文件**，避免"账号在 / 数据丢"的分裂问题。

### 生产模式（MySQL）

通过环境变量启用：

```bash
export IELTS_BUDDY_WEB_DB_MODE=online
export IELTS_BUDDY_WEB_DB_URL=mysql+pymysql://user:pass@host:3306/ielts_buddy
python -m ielts_buddy.web.main
```

此时 `web_users` 与业务表都在同一 MySQL 实例下的同一 engine 中。

## 重启账号丢失排查

如发现重启后账号丢失，按下表排查：

| 现象 | 原因 | 修复 |
|------|------|------|
| `web_data.db` 文件被删除 | 测试脚本误删 / 部署清理脚本误删 | 删除 `db_path.unlink()` 调用 |
| `WEB_DB_MODE=online` 但无 MySQL | 默认值问题 | 确认 MySQL 服务可达；或显式设 `WEB_DB_MODE=sqlite` |
| `JWT_SECRET` 变了 | 每次重启随机生成 | 设置环境变量 `IELTS_BUDDY_JWT_SECRET` |
| 同一 db 文件被两个进程打开 | SQLite 文件锁 | 检查端口冲突，关闭多余进程 |

## 关键设计

1. **共享连接**：web_user_repo 与业务仓库**共用一个 SQLite/MySQL 连接**，
   避免账号和数据存储到不同物理实例。
2. **统一 schema**：`web_users` 表已加入 `sqlite_repo._SCHEMA`，
   与业务表在同一文件中创建。
3. **唯一约束**：`web_users.email` 带 `UNIQUE ... COLLATE NOCASE`，
   大小写不敏感且不允许重复。

## 验证

运行 `persistence_test.py` 模拟"注册 → 重启 → 登录"全流程：

```bash
.venv/bin python /Users/wangliping/.trae-cn/work/.../persistence_test.py
```

应输出 `8/8 PASS`。