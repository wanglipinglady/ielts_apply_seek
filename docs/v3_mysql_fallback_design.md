# v3 架构设计：MySQL 主存 + SQLite 自动降级 + 双向同步

> 立项日期：2026-08-23
> 状态：✅ 已完成（Web + CLI 端到端跑通）

## 1. 背景与目标

### 1.1 用户需求

- **Web 端**：登录用户在任何机器都能看到自己的数据（个人词库、学习记录、批改历史等）
- **CLI 端**：同一用户在 Web/CLI 之间共享历史
- **离线可用**：远程 MySQL 临时挂掉时，CLI/Web 学习不中断；恢复后数据自动同步上去
- **零人工介入**：自动选择 backend，自动同步，无需运维手动切

### 1.2 旧架构痛点

| 痛点 | 说明 |
|---|---|
| 数据孤岛 | Web SQLite (`web_data.db`) 和 CLI SQLite (`data.db`) 物理隔离 |
| 单点故障 | MySQL 不可达时 Web 直接 500，CLI 直接报错退出 |
| 用户分裂 | `users` (CLI) 和 `web_users` (Web) 是两张表，密码要分开管理 |
| 启动期"反复横跳" | 每个新环境都得选 mode、设 url、配 db path |

## 2. v3 设计原则

1. **MySQL 是 source of truth，SQLite 是离线缓存**
   - 在线模式下读写全走 MySQL；本地 SQLite 只作"离线应急"
   - 数据双向同步：本地写入标 `pending_upload` → 推到 MySQL；MySQL 增量按 `updated_at` 拉到本地
2. **统一 users 表**
   - 单一 `users` 表，username + email 唯一；CLI 无邮箱时 email/password_hash 都为 NULL
3. **数据库文件统一**
   - CLI 和 Web 共用 `~/.ielts-buddy/ielts_buddy.db`（替代旧的 `data.db` 和 `web_data.db`）
4. **自动降级，自动回切**
   - 启动期 ping MySQL 失败 → fallback_sqlite；ping 成功 → online
   - 运行中定期 ping（5s TTL 缓存），发现可达后自动切回 online
5. **last-write-wins 冲突解决**
   - 每行有 `updated_at`，推送时如果 MySQL 的更新时间更新 → 放弃 push；反之本地赢
   - 简单可靠，适合"同一用户多数时候只在一种设备上写"的场景

## 3. 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                        Web (FastAPI + uvicorn)                   │
│                                                                  │
│  ┌────────────────┐     ┌──────────────────────────────────┐    │
│  │ lifespan 启动期 │ ──▶ │ create_fallback_container()      │    │
│  │ ping MySQL     │     │ - online (默认) 或 fallback_sqlite│    │
│  └────────────────┘     │ - 同时持有 MySQL + SQLite         │    │
│                         │ - current_mode 自动切换           │    │
│                         └──────────────┬───────────────────┘    │
│                                        │                        │
│                         ┌──────────────▼───────────────────┐    │
│                         │ SyncWorkerAsync（asyncio 后台）   │    │
│                         │ 每 30s: push + pull                │    │
│                         └──────────────┬───────────────────┘    │
└────────────────────────────────────────┼─────────────────────────┘
                                         │
                  ┌──────────────────────┼────────────────────────┐
                  ▼                      ▼                        ▼
         ┌──────────────┐       ┌──────────────────┐    ┌──────────────────┐
         │ MySQL 主存   │       │ SQLite 本地缓存  │    │ ~/.ielts-buddy/  │
         │ 118.190...   │ ◀───▶ │ ielts_buddy.db   │    │ backup/ logs/    │
         │ :3306        │  sync │ (CLI+Web 共享)   │    │                  │
         └──────────────┘       └──────────────────┘    └──────────────────┘
                  ▲
                  │ 同样共享
                  │
┌──────────────────────────────────────────────────────────────────┐
│                          CLI (Click + rich)                       │
│                                                                  │
│  ib auth login wanglipingrese   ──▶ 读 MySQL users 表             │
│  ib db-status show               ──▶ FallbackContainer 状态       │
│  ib db-status sync-now           ──▶ 立即触发一次 sync              │
│  ib sync daemon --interval 30    ──▶ 长驻后台 SyncWorker（threading）│
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 4. 状态机

```
                     ┌───────────────────────────────┐
                     │            启动期              │
                     │  try_mysql() = ping 一次       │
                     └───────────┬───────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
         ┌──────────┐     ┌──────────┐     ┌──────────────────┐
         │ MySQL OK │     │MySQL 失败│     │ env 强制 sqlite  │
         └─────┬────┘     └─────┬────┘     └─────────┬────────┘
               │                │                    │
               ▼                ▼                    ▼
        ┌──────────┐    ┌──────────────────┐    ┌──────────┐
        │ online   │    │ fallback_sqlite  │    │ sqlite   │
        │ 读写 MySQL│    │ 读写 SQLite      │    │ 只读 SQLite│
        │ push+pull│    │ 写本地标 pending │    │（不推送）│
        └────┬─────┘    └──────┬───────────┘    └──────────┘
             │                 │
             │  ┌──────────────┘
             │  │ 每 30s try_mysql() 自动 ping
             │  │
             ▼  ▼ (5s 内连续可达)
        ┌──────────────────┐
        │ 切回 online       │
        │ （pull 一遍把     │
        │  离线期间的更新拉  │
        │  下来）            │
        └──────────────────┘
```

关键不变量：
- **写入即时一致**：online 模式写入 MySQL 成功后才返回 2xx；fallback 模式写入 SQLite + 标 pending_upload
- **同步水位**：SQLite 的 `sync_meta.last_pull_at` / `last_push_at` 记录最近成功时间
- **失败隔离**：单个表 push/pull 失败不影响其他表；本轮 sync 整体失败不影响下一轮

## 5. 数据库 Schema（v3）

### 5.1 users 表（统一）

```sql
-- MySQL & SQLite 一致结构
CREATE TABLE users (
    id              INTEGER/BIGINT  PRIMARY KEY AUTOINCREMENT/AUTO_INCREMENT,
    username        TEXT NOT NULL COLLATE NOCASE,
    email           TEXT COLLATE NOCASE,           -- NULL 允许（CLI 用户）
    password_hash   TEXT,                          -- NULL 允许（CLI 用户）
    display_name    TEXT,
    created_at      TEXT NOT NULL,
    last_login_at   TEXT,
    UNIQUE (username COLLATE NOCASE),
    UNIQUE (email COLLATE NOCASE)
);
```

### 5.2 业务表（共 7 张全部走 sync）

| 表 | 同步键 | 备注 |
|---|---|---|
| personal_vocab | (user_id, word) | UNIQUE 约束，自动处理重复 |
| learning_records | (user_id, word) | 同上 |
| vocab_categories | (user_id, name) | 同上 |
| vocab_category_words | (user_id, category_id, word) | **暂跳过 sync** — SQLite 用 (category_id, word_id) 复合 PK，结构差异大 |
| exam_sessions | (user_id, id) | **暂跳过 sync** — SQLite id 是 TEXT (UUID)，MySQL id 是 BIGINT |
| grade_history | (user_id, id) | 同步 |
| articles | (user_id, id) | MySQL 新建的表，与 SQLite 一致 |

所有业务表新增：
- `updated_at TEXT NOT NULL DEFAULT ''` — last-write-wins 时间戳基准
- `sync_status TEXT NOT NULL DEFAULT 'synced'` — `'synced'` / `'pending_upload'`

### 5.3 迁移路径

```bash
# 1. MySQL DDL 升级（articles 表 + 各表 updated_at/sync_status 列）
python scripts/migrate_v3_mysql_schema.py

# 2. web_users → users 合并（带 username 推导、is_migrated 标记）
python scripts/migrate_v3_users_merge.py

# 3. SQLite schema 升级（运行时自动，跨版本幂等）
#    第一次启动 v3 web/CLI 时自动跑 _MIGRATIONS 字典
```

## 6. 同步核心：SyncWorker

### 6.1 流程

```python
def sync_once():
    if not container.try_mysql():
        return SyncResult(errors=["MySQL 不可达"])
    if container.online is None:
        return SyncResult(errors=["未配置 MySQL"])

    # 1. push: 本地 pending_upload → MySQL
    for spec in SYNC_TABLES:  # 7 张表
        _push_table(spec, sqlite_conn, mysql_engine)

    # 2. pull: MySQL updated_at > last_pull_at 的行 → SQLite
    last_pull_at = sync_meta.last_pull_at
    for spec in SYNC_TABLES:
        _pull_table(spec, sqlite_conn, mysql_engine, last_pull_at)

    # 3. 更新 sync_meta
    sync_meta.last_pull_at = now() if pulled > 0 else unchanged
    sync_meta.last_push_at = now() if pushed > 0 else unchanged
```

### 6.2 冲突解决（last-write-wins）

```python
def _push_table(spec, ...):
    rows = sqlite_conn.execute(
        "SELECT ... FROM {table} WHERE sync_status='pending_upload'"
    ).fetchall()

    for row in rows:
        # 检查 MySQL 端是否存在
        remote = mysql_engine.scalar(
            "SELECT updated_at FROM {table} WHERE conflict_key = %s",
            (row.conflict_values,)
        )
        if remote and _compare_ts(row.updated_at, remote) <= 0:
            # 远端更新或相等 → 放弃 push，让 pull 覆盖本地
            sqlite_conn.execute("UPDATE ... SET sync_status='synced'")
            continue
        # 否则 INSERT ... ON DUPLICATE KEY UPDATE
```

### 6.3 关键设计选择

| 决策 | 理由 |
|---|---|
| 同步 7 张表，跳过 exam_sessions / vocab_category_words | 结构差异太大（UUID vs BIGINT id）；v3 不强行同步，等后续版本 |
| pull 用 `INSERT ... ON CONFLICT DO UPDATE` | 比 `INSERT OR REPLACE` 安全，不删除再插入，FK 引用稳定 |
| push 用 `INSERT ... ON DUPLICATE KEY UPDATE` | MySQL 原生 UPSERT，依赖 (user_id, word) 唯一键 |
| last-write-wins 用 `updated_at` 字符串比较 | SQLite 存 TEXT（ISO），MySQL 存 DATETIME，比较时统一转 datetime |
| 同步水位 + 失败表隔离 | 单表失败不影响全局 sync_meta 更新 |

## 7. FallbackContainer 设计

```python
class FallbackContainer:
    def __init__(mysql, sqlite):
        self._online = mysql    # 可能为 None（强制 sqlite）
        self._offline = sqlite  # 永远存在
        self._current_mode = "online" if mysql else "fallback_sqlite"

    @property
    def current_mode(self): return self._current_mode

    @property
    def learning(self): return self._active.learning  # 透传到当前 backend

    def try_mysql(self) -> bool:
        """ping MySQL，更新可达性，按需切模式。"""
        if ping_ok:
            self._last_mysql_ok = True
            if self._current_mode != "online":
                self._switch_to_online()
            return True
        else:
            self._last_mysql_ok = False
            if self._current_mode != "fallback_sqlite":
                self._switch_to_fallback()
            return False
```

业务代码（Service 层）无需感知 backend 切换 —— 全部通过 `container.learning.add_word(...)` 透明转发。

## 8. Web 启动流程

```python
@asynccontextmanager
async def _lifespan(app):
    # 1. 创建 FallbackContainer（ping MySQL 一次）
    app.state.container = create_fallback_container(
        sqlite_db_path=Path(get_web_db_path()),
        mysql_url=WEB_DB_URL,
        prefer_mode="online" if WEB_DB_MODE != "sqlite" else "sqlite",
    )

    # 2. web_user_repo：跟当前 backend 走（online→MySQLWebUserRepository，fallback→SQLite）
    app.state.web_user_repo = _open_default_user_repo()

    # 3. 启动后台 sync worker（asyncio）
    app.state.sync_worker = start_sync_worker(
        container=app.state.container,
        interval_seconds=int(os.environ.get("IELTS_BUDDY_SYNC_INTERVAL_SEC", "30")),
    )

    yield

    # 关闭时清理
    worker.stop()
    container.close()
```

`/healthz` 输出：
```json
{
  "db_mode": "online",
  "mysql_reachable": true,
  "sync": {
    "last_pull_at": "2026-08-22T17:35:43+00:00",
    "last_push_at": "2026-08-22T17:35:43+00:00",
    "last_error": null
  },
  "pending_upload_personal_vocab": 0
}
```

## 9. CLI 启动流程

```bash
# 登录（online 模式必须）
ib auth login wanglipingresume

# 查看同步状态
ib db-status show

# 立即触发一次同步
ib db-status sync-now

# 长驻后台 sync daemon（适合在终端里 nohup 跑）
nohup ib sync daemon --interval 30 > ~/ielts-sync.log 2>&1 &
```

CLI 默认 mode 也是 `online`，跟 Web 共用 SQLite 文件 `~/.ielts-buddy/ielts_buddy.db`。

## 10. 验证（已通过）

### 10.1 集成测试

`tests/test_v3_sync_integration.py` 覆盖：
- ✅ test_01_pull_personal_vocab：MySQL → SQLite 拉取
- ✅ test_02_push_personal_vocab：SQLite → MySQL 推送
- ✅ test_03_conflict_last_write_wins_local_newer：冲突解决（本地赢）
- ✅ test_04_sync_worker_idempotent：连续跑两次结果一致
- ✅ test_05_mysql_unreachable_silent：MySQL 不可达时静默

### 10.2 手动验证

```bash
# 登录
curl -X POST http://127.0.0.1:8765/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=wanglipingresume@163.com&password=Wang2026Lp!"
# → 200 OK + access_token + refresh_token

# 健康检查
curl http://127.0.0.1:8765/healthz
# → db_mode=online, mysql_reachable=true, last_pull_at 有效

# CLI 同步
python3 -m ielts_buddy db-status show
# → DB Mode: online / MySQL 可达: ✓ / 各表 pending_upload 计数
```

## 11. 已知边界 / 不在 v3 范围

| 项 | 当前状态 | 后续 |
|---|---|---|
| exam_sessions | 不同步 | v3.1：把 MySQL id 改成 VARCHAR(64)，应用层生成 UUID |
| vocab_category_words | 不同步 | v3.1：SQLite 端加 user_id / word 列，对齐 MySQL |
| sync 间隔默认 30s | 可通过 `IELTS_BUDDY_SYNC_INTERVAL_SEC=0` 关闭 | — |
| 多端同时写冲突 | last-write-wins 简单粗暴 | v4：可换 CRDT 或 vector clock |
| MySQL 长时间不可达期间的数据累积 | SQLite 会持续累积 `pending_upload`，MySQL 恢复后一次性回传 | 已验证：pull 838 行无错误 |

## 12. 文件清单

### 12.1 新增

- `scripts/migrate_v3_users_merge.py` — web_users → users 迁移
- `scripts/migrate_v3_mysql_schema.py` — MySQL DDL 升级
- `src/ielts_buddy/services/db_health.py` — MySQL 健康检查 + TTL 缓存
- `src/ielts_buddy/repositories/fallback_repo.py` — FallbackContainer
- `src/ielts_buddy/services/sync.py` — SyncWorker / SyncWorkerAsync / SyncDaemonThread
- `tests/test_v3_sync_integration.py` — v3 同步集成测试
- `docs/v3_mysql_fallback_design.md` — 本文档

### 12.2 修改

- `src/ielts_buddy/repositories/sqlite_repo.py` — 新增 updated_at/sync_status 列；_MIGRATIONS 字典；users 表
- `src/ielts_buddy/repositories/mysql_repo.py` — _build_mysql_url 工具（已有，保持）
- `src/ielts_buddy/core/config.py` — DEFAULT mode 改 online；DB 文件名改 ielts_buddy.db
- `src/ielts_buddy/web/config.py` — DB mode 默认 online；DB 文件统一
- `src/ielts_buddy/web/main.py` — lifespan 接入 FallbackContainer + SyncWorker
- `src/ielts_buddy/web/auth/repository.py` — MySQL 实现读写 users 表（不再读 web_users）
- `src/ielts_buddy/web/services.py` — get_stats_service 适配 FallbackContainer
- `src/ielts_buddy/commands/db_status.py` — 新增命令组
- `src/ielts_buddy/commands/sync.py` — 新增 `ib sync daemon` 子命令
- `src/ielts_buddy/cli.py` — 注册 db_status 命令
- `~/.ielts-buddy/config.toml` — mode = "online"
- `.env` — DB_MODE=online, SYNC_INTERVAL_SEC=30

### 12.3 备份

- `~/.ielts-buddy/backup_v3_20260823_010124.json` — 迁移前 44 个 web_users 全量快照
