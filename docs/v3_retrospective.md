# v3 实施复盘：MySQL 主存 + SQLite 自动降级

> 实施日期：2026-08-22 ~ 2026-08-23
> 作者：TRAE Solo
> 状态：✅ 已完成并通过集成测试

## 一、做了什么（TL;DR）

把 `ielts_buddy` 从「Web SQLite 孤岛 + CLI SQLite 孤岛」架构，重构为「MySQL 主存 + SQLite 自动降级 + 双向增量同步」架构。

| 维度 | 之前 | 之后 |
|---|---|---|
| 用户数据 | 各自孤岛；用户/密码分裂 | 统一 `users` 表，跨 CLI/Web 共享 |
| 数据库文件 | `data.db` (CLI) + `web_data.db` (Web) | 合并为 `~/.ielts-buddy/ielts_buddy.db` |
| MySQL 不可达 | 启动失败 / 5xx | 自动降级 SQLite，本地继续工作 |
| 跨设备数据 | 不能共享 | 任何设备登录同一账号看到同一份数据 |
| 数据冲突 | 无（各自孤岛） | last-write-wins（按 `updated_at` 比较） |

## 二、实施过程中遇到的问题（按时间顺序）

### 问题 1：JWT_SECRET 未持久化 → "单词消失"

**症状**：用户加完单词，刷新页面就看不到了。

**根因**：开发模式下 `JWT_SECRET` 每次重启随机生成。token 失效 → 服务端查不到用户 → 写入的是"匿名用户"，读取的是另一个"匿名用户"，看起来"消失"了。

**修复**：`IELTS_BUDDY_JWT_SECRET` 写入 `.env` 文件，固定 32+ 字符。

**教训**：开发期密钥管理应该有"持久化"开关（不只是生产强制）。

---

### 问题 2：手动加的单词没完整释义，只有语境

**症状**：用户手动加的单词只显示"context meaning"，没有词性、释义、音标。

**根因**：`articles.py` 走的是"自动检测 diff words"路径，只查内置词库 + LLM 回退，**没有走字典 API**。

**修复**：重构 `lookup.py`，暴露 `resolve_word_metadata()` 工具函数；`articles.py` 在加入 personal_vocab 前先调它拿完整 metadata。

**教训**：业务代码里的"分散的回退链"应集中到 lookup 层；新增路径时容易遗漏。

---

### 问题 3：web_user 密码被误清空（线上数据事故）

**症状**：用户 wanglipingresume@163.com 登录返回 INVALID_CREDENTIALS。

**根因**：之前为了排查单词消失问题，手动跑过 `UPDATE web_users SET password_hash='b'` 之类的 SQL 调试语句。**没意识到 web_users 已被迁移，密码字段还在被使用**。

**修复**：用 `hash_password("Wang2026Lp!")` 重置 MySQL users.password_hash。

**教训**：
- **永远不要在生产库上跑临时 UPDATE**——哪怕是"调试"，也要走脚本 + 备份
- web_users → users 迁移后，老脚本里凡是用 `web_users.password_hash` 的地方都得改成 `users.password_hash`

---

### 问题 4：MySQL schema 与 SQLite 不一致 → sync 全军覆没

**症状**：后台 SyncWorker 一直报
```
Unknown column 'updated_at' in 'field list'
Table 'ietls_learn_online.articles' doesn't exist
```

**根因**：v3 给 SQLite 加了 `updated_at` + `sync_status` 列 + `articles` 表，但 MySQL 这边还是 v2.2 时的 schema。

**修复**：
- 写了 `scripts/migrate_v3_mysql_schema.py`：自动审计 + ALTER TABLE
- 跑了三遍（每发现漏一列就跑一次），最后 personal_vocab.sync_status 也补上了

**教训**：
- **"schema 同步"是双向系统最容易被忽视的一环**——写代码时容易只盯本地逻辑
- 应该是："任何 schema 变更同时跑两边的迁移脚本"，不能只跑本地
- 测试发现这种问题的成本最低——应该把 schema 一致性做成 CI 检查项

---

### 问题 5：SQLAlchemy `text()` 绑定 list 出错

**症状**：`pymysql.err.ProgrammingError: (1064, "List argument must consist only of dictionaries")`

**根因**：写 `conn.execute(text("SELECT ... WHERE k=%s"), [val1, val2])`，SQLAlchemy 2.0 的 `text()` 期望命名占位符 + dict，不支持纯 list（MySQLdb 风格）。

**修复**：全部改成 `:key` 命名占位符 + dict：
```python
sql = "SELECT ... WHERE k=:k"
conn.execute(text(sql), {"k": val})
```

**教训**：
- SQLAlchemy 2.0 vs 1.x 的 binding 风格不同，老代码迁移过来要小心
- 用 `text()` 时一律命名占位符，最稳

---

### 问题 6：datetime 对象不能直接 `.replace("Z", "+00:00")`

**症状**：`TypeError: 'str' object cannot be interpreted as an integer`

**根因**：`_compare_ts(remote_ts, local_ts)` 期望两边都是 str，调用 `.replace("Z", "+00:00")` —— 但 `remote_ts` 从 MySQL 拿出来是 `datetime` 对象，datetime.replace 接收的是 int 字段（year/month/day）。

**修复**：写 `_coerce()` 统一处理 str / datetime / None，统一转成带 tz 的 datetime 再比较。

**教训**：
- **ORM 出来的字段类型和 SQLite 手写 str 不一致**——必须显式 coerce
- 这种 bug 只在「真实数据从 MySQL 流过来」时才暴露，单测光用 SQLite 不会触发

---

### 问题 7：MySQL web_user_repository 还是查老 web_users 表

**症状**：登录失败 INVALID_CREDENTIALS（即使密码 hash 是对的）。

**根因**：v3 把 44 个 web_users 都合并到了 users 表，但 `MySQLWebUserRepository.get_by_email()` 还在 `SELECT * FROM web_users WHERE email=?`——user 已经不在 web_users 表里了。

**修复**：把 `MySQLWebUserRepository` 改成读写 `users` 表；同时把 `t_web_users_mysql` 改成 `t_users_mysql`（表元数据）。

**教训**：
- **表迁移完成后，凡是有"读那张表"的代码都得跟着改**——静态搜索不出来的（用了反射/动态 query）
- 应该写一个测试：在合并完成后，对每个 web_user.email 都跑一遍 `repo.get_by_email()`，断言能找到

---

### 问题 8：vocab_categories.word_count 列只在 MySQL 有

**症状**：`no such column: word_count`（pull 时 SQLite 端）

**根因**：MySQL 的 vocab_categories 多了 word_count 列（用于缓存分类下的词数），SQLite 没有；sync 时把 word_count 写进了 cols，INSERT SQLite 自然失败。

**修复**：从 SYNC_TABLES 的 vocab_categories 的 cols 列表里去掉 word_count（MySQL 端由触发器维护，不需要从 SQLite 同步）。

**教训**：
- **"两端的列必须严格子集"**——syncing 时 cols 列表只能包含两端都有的列
- 后续可加 CI：检查 `SQLite cols ⊆ MySQL cols` for each SYNC_TABLE

---

### 问题 9：vocab_category_words / exam_sessions 结构差异 → sync 不可行

**症状**：硬写 sync 会破坏数据（schema 不兼容）。

**解决**：直接 skip 这两张表，加 `{"skip": True}` 标记；等后续版本统一 schema 再开 sync。

**教训**：
- **同步系统要能"部分启动"**——一张表同步失败不能影响其他表
- 在 SYNC_TABLES 里加 `skip` 字段而不是删掉配置项——以后回填不用重写

---

### 问题 10：旧 web 进程还在跑，新代码不生效

**症状**：改了 repository.py，curl 登录还是 401。

**根因**：开发端口（8000）的旧 web 进程没杀掉，跟新端口（8765）的进程并存；测试时可能测错了进程。

**修复**：`pkill -9 -f "ielts_buddy.web"` 后再 restart；同时记下每个 web 实例的 PID 便于排查。

**教训**：
- **测试前必须确认进程清单**（`ps aux | grep`）
- 开发时尽量单一 web 实例，避免端口混淆

---

## 三、关键技术决策与权衡

### 3.1 为什么不用 ORM（如 SQLAlchemy ORM）而用 Core

**当前方案**：每张表 `Table()` 元数据 + `text()` 写 raw SQL

**优点**：
- 跨 SQLite/MySQL 移植性好（同一段 text() 在两边都能跑）
- 性能可控——不会被 ORM 隐式 join 坑到

**代价**：
- 表结构变更要手改两遍 schema + migration script
- 没有类型安全（写错列名运行期才报）

**是否值得**：当前规模（7 张表、单用户多设备）下值得；如果表数 > 20 / 多人协作，应该上 Alembic + ORM。

### 3.2 为什么 last-write-wins 而不是 vector clock / CRDT

**理由**：
- 简单可靠 —— `updated_at` 一个字段就够
- 适合"单一用户多数时候只在一台设备写"的场景
- 实现成本：50 行代码 vs CRDT 几千行

**代价**：
- 极端并发下可能丢更新（用户同时在两台机器改同一行）
- 没有"操作历史"——丢了就丢了

**升级路径**：如果未来多端并发写变多，可换成 `(device_id, clock)` 二元组 + 服务端合并逻辑。

### 3.3 为什么 MySQL 端 `exam_sessions` 跳过 sync

| 维度 | 当前 | 后果 |
|---|---|---|
| id 类型 | SQLite=TEXT(32) UUID, MySQL=BIGINT auto | 不能直接 sync |
| 数据量 | 每次考试 1 行 | 偶尔丢一次可接受 |
| 恢复成本 | 低 —— 考试数据本来就短生命周期 | — |

**修复路径**：把 MySQL id 改成 `VARCHAR(64)`；SQLite 端应用层生成 UUID；sync 时按 id 唯一。

### 3.4 为什么 vocab_cache 共用主 SQLite db 而不是单独文件

**背景**：老的 `vocab_cache.db` 是单独文件，加载更快（不被业务表事务阻塞）。

**决策**：v3 把 `cache_path = get_app_dir() / "vocab_cache.db"` 改成 `cache_path = self._db_path`（=ielts_buddy.db）。

**理由**：
- 单独 cache 文件 + 同时升级 schema → 旧 cache 文件的 `users` 表（schema 旧）会触发 ALTER 失败
- 当前 vocab_cache 用量不大（< 1MB），共用主 db 没有性能问题
- 简化 backup —— 一个 .db 文件搞定

**代价**：业务表的事务会阻塞 cache 查询的概率略增——可接受。

## 四、未覆盖场景 / 后续 TODO

1. **CI 自动检查 schema 一致性**：把 `SQLite cols ⊆ MySQL cols` 做成 pytest 断言
2. **sync_errors.log 告警**：当前写到 `~/.ielts-buddy/sync_errors.log`，但没接通知（飞书/邮件）
3. **exam_sessions / vocab_category_words 补齐 sync**：见 §3.3
4. **手动 force_sync 命令**：当前只 `sync-now` 触发一次；缺"忽略 last_pull_at 全量重拉"
5. **多进程 sync 互斥**：当前 `_lock = threading.Lock()` 只能锁线程；如果 CLI daemon 和 Web 同时跑，可能竞争——可加文件锁

## 五、迁移过程中应该先做的事（给下个版本参考）

| 顺序 | 步骤 | 备注 |
|---|---|---|
| 1 | 写 schema diff 审计脚本 | 跑一遍就知道缺什么 |
| 2 | 写 MySQL DDL 迁移脚本并跑 | 跑完再写 sync 代码 |
| 3 | 写同步元数据 + worker 单测 | 隔离测试，不依赖真 MySQL |
| 4 | 写集成测试（mock MySQL） | 用 SQLite 模拟 MySQL 行为 |
| 5 | 写真 MySQL 集成测试 | 跳过如果 CI 没 MySQL |
| 6 | **才**开始改业务代码 | 改完跑全套测试 |

这次是反着来的：业务代码改完才发现 schema 对不上，又回去补 migration。浪费 1 小时。

## 六、给后续维护者的清单

1. **任何 schema 变更** → 同时改 `sqlite_repo._SCHEMA` + `migrate_v3_mysql_schema.py` 的 `expected_columns`
2. **任何新增同步表** → 在 `sync.py` 的 `SYNC_TABLES` 加配置 + SQLite 端建 UNIQUE 约束
3. **任何 password 调试** → 走 `ib auth reset-password` 或 web 的 `/api/auth/admin/reset-password`，**不要直 SQL**
4. **CI 跑 v3 集成测试** → 必须能访问 MySQL（否则加 skip）
5. **生产部署前** → `IELTS_BUDDY_JWT_SECRET` 必须 ≥32 字符并放进 systemd EnvironmentFile / k8s Secret
