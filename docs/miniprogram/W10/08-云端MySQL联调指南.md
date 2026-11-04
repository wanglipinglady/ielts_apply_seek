# 云端 MySQL 联调指南（v3.9 / 2026-09-21）

> **场景**：MySQL 已在阿里云部署（118.190.148.121:3306/ietls_learn_online），从 Mac 本地直接远程连。
> **不是**：备案未通过期间的临时方案，**生产就用这个**。

---

## 1. 当前环境清单

| 项 | 值 |
|---|---|
| 数据库地址 | `118.190.148.121:3306` |
| 数据库名 | `ietls_learn_online` |
| 用户名 | `remote_user`（默认，可改专用账户） |
| 密码 | `Pass@666`（**生产必须改**） |
| MySQL 版本 | 8.0.46（已在云端初始化 schema） |
| 表数量 | 19（已建好，schema 用 `scripts/init_mysql.sql`） |

✅ **已验证连通**：从 Mac 直连 `118.190.148.121:3306` 成功，pymysql 能正常查询。

---

## 2. 启动 Web 端（连云端 MySQL）

### 2.1 命令

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek

# === 数据库 ===
export IELTS_BUDDY_WEB_DB_MODE=online
export IELTS_BUDDY_WEB_DB_URL="mysql+pymysql://remote_user:Pass@666@118.190.148.121:3306/ietls_learn_online?charset=utf8mb4"

# === LLM ===
export IELTS_BUDDY_LLM_API_KEY="sk-cp-<在此填入你的 MiniMax key>"
export IELTS_BUDDY_LLM_BASE_URL="https://api.minimaxi.com/v1"
export IELTS_BUDDY_LLM_MODEL="MiniMax-M2.7-highspeed"

# === 启动 ===
PYTHONPATH=src uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000
```

### 2.2 验证（健康检查）

```bash
curl http://127.0.0.1:8000/healthz | python3 -m json.tool
```

期望输出：
```json
{
  "status": "ok",
  "app": "ielts-buddy-web",
  "version": "0.1.0",
  "prefer_mode": "online",
  "db_mode": "online",                  ← 关键
  "mysql_reachable": true,              ← 关键
  "sync": { ... },
  ...
}
```

如果 `db_mode: fallback_sqlite` → **fallback 了**，检查 `WEB_DB_URL` 是否正确。

---

## 3. 切换到云端 MySQL 之前需要的设置

### 3.1 修改项目根 .env（持久化）

修改 `.env`，把 MySQL URL 写进去（以后启动就不用 export 了）：

```bash
# .env
IELTS_BUDDY_WEB_DB_MODE=online
IELTS_BUDDY_WEB_DB_URL=mysql+pymysql://remote_user:Pass@666@118.190.148.121:3306/ietls_learn_online?charset=utf8mb4
```

⚠️ **注意**：
- `.env` 不提交到 git（在 `.gitignore` 里）
- 但**密码不要 commit**（就算 .gitignore 也要小心）
- 推荐用 `Pass@666` 占位，**生产前改专用密码**

### 3.2 让 start_web.sh 自动加载（可选）

`start_web.sh` 已经会自动 `source .env`（line 96-105），所以你只需要：
- 把 MySQL URL 填到 `.env`
- 启动命令变成：`./start_web.sh --host 0.0.0.0`

不需要每次手动 export。

### 3.3 关于 `remote_user:Pass@666`

⚠️ **生产环境强烈建议改密码**：

```sql
-- 在阿里云 MySQL 上执行（用 root 或 super user）
ALTER USER 'remote_user'@'%' IDENTIFIED BY '<new_strong_password>';
FLUSH PRIVILEGES;
```

或者创建专用账户（推荐）：

```sql
CREATE USER 'ielts_app'@'%' IDENTIFIED BY '<strong_password>';
GRANT ALL PRIVILEGES ON ietls_learn_online.* TO 'ielts_app'@'%';
FLUSH PRIVILEGES;
```

然后 URL 改为：
```
mysql+pymysql://ielts_app:<password>@118.190.148.121:3306/ietls_learn_online?charset=utf8mb4
```

---

## 4. 真机调试（小程序）

小程序端用 LAN IP 即可，**备案前不影响真机调试**：

```javascript
// miniprogram/app.js
apiBaseUrl: 'http://<Mac LAN IP>:8000'  // 例: 'http://172.20.10.2:8000'
```

微信开发者工具：
1. **真机调试** → 自动预览 → 扫码
2. 手机端：登录 → 学习 → 复习 → 口语录音 → 评分
3. 数据写入**云端 MySQL**（不是本地 SQLite！）

**关键配置**：
- ✅ 微信开发者工具「不校验合法域名」勾选（开发期必勾）
- ✅ 手机系统给微信麦克风权限
- ✅ Mac 与手机同 WiFi

---

## 5. 验证 MySQL 数据写入

开发一段时间后，去云端 MySQL 查数据：

### 5.1 命令行方式

```bash
# 从 Mac 连
mysql -h 118.190.148.121 -u remote_user -p ietls_learn_online

# 查用户数
SELECT COUNT(*) FROM web_user;

# 查最近创建的用户
SELECT id, email, created_at, last_login_at
FROM web_user
ORDER BY id DESC LIMIT 5;

# 查学习记录
SELECT user_id, COUNT(*) as records
FROM learning_records
GROUP BY user_id
ORDER BY records DESC LIMIT 5;

# 查口语练习
SELECT id, user_id, session_id, part, topic_name, created_at
FROM speaking_practice_records
ORDER BY id DESC LIMIT 5;

# 查错词本
SELECT user_id, word, wrong_count, source
FROM mistakes
ORDER BY wrong_count DESC LIMIT 10;
```

### 5.2 图形化方式

推荐用 **Navicat**、**DBeaver**（免费）、**MySQL Workbench** 连：

```
Host: 118.190.148.121
Port: 3306
User: remote_user
Password: Pass@666
Database: ietls_learn_online
```

### 5.3 Python 脚本方式

```python
import pymysql
conn = pymysql.connect(
    host='118.190.148.121', port=3306,
    user='remote_user', password='Pass@666',
    database='ietls_learn_online'
)
with conn.cursor() as cur:
    cur.execute("SHOW TABLES")
    for (t,) in cur.fetchall():
        print(t)
conn.close()
```

---

## 6. 故障排查

### 6.1 `mysql_reachable: false`

按这个顺序排查：

| 步骤 | 检查 | 命令 |
|---|---|---|
| 1 | 网络通吗 | `nc -zv 118.190.148.121 3306` |
| 2 | 用户能登录吗 | `mysql -h 118.190.148.121 -u remote_user -p` |
| 3 | 数据库存在吗 | `SHOW DATABASES;` |
| 4 | URL 格式对吗 | 必须是 `mysql+pymysql://...` |
| 5 | 密码转义 | 特殊字符用 `quote_plus` |

### 6.2 表不存在

如果 schema 没初始化过：

```bash
# 方法 1：Python 脚本
python scripts/init_mysql.py \
  --host 118.190.148.121 \
  --user remote_user \
  --password 'Pass@666' \
  --database ietls_learn_online

# 方法 2：手动
mysql -h 118.190.148.121 -u remote_user -p ietls_learn_online < scripts/init_mysql.sql
```

### 6.3 密码认证失败

MySQL 8 默认 `caching_sha2_password`，需要 `cryptography` 包：

```bash
# 检查
pip show cryptography

# 装
pip install cryptography
```

### 6.4 时区问题

跨时区服务器（如 UTC vs +08:00）可能影响 timestamp：

```sql
-- 检查当前时区
SELECT @@global.time_zone, @@session.time_zone;

-- 设置会话时区（也加到 .env）
SET time_zone = '+08:00';
```

uvicorn 启动时加：
```bash
export TZ='Asia/Shanghai'
PYTHONPATH=src uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000
```

### 6.5 sync 报错（healthz 里 last_error 不为 null）

```bash
# 看完整错误
curl http://127.0.0.1:8000/healthz | python3 -m json.tool
# 看 sync.last_error 字段

# 看本地 sync_errors.log
tail -50 ~/.ielts-buddy/sync_errors.log

# 重新触发同步（重启 uvicorn 即可）
```

---

## 7. 推荐的开发工作流

### 备案前（现在）

```bash
# 1. 一次性：修改 .env 让 uvicorn 默认连云端 MySQL
#    (或者每次手动 export，下面会列)

# 2. 每次启动：在 Mac Terminal 跑
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
PYTHONPATH=src uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000

# 3. 真机调试：
#    - app.js: apiBaseUrl = 'http://172.20.x.x:8000'
#    - 微信开发者工具 → 真机调试 → 扫码

# 4. 数据验证：
#    mysql -h 118.190.148.121 -u remote_user -p
#    SELECT * FROM web_user;
```

### 备案后（切到正式域名）

不用改代码，只改：
1. `.env` 不变（依然连云端 MySQL）
2. `app.js` 的 `apiBaseUrl` 改为 `https://ielts.example.com`（备案域名）
3. 阿里云服务器部署 uvicorn（与 MySQL 同服务器或不同服务器都行）
4. Nginx 反向代理 + HTTPS 证书
5. 微信公众平台配置服务器域名

详见 `09-备案后部署指南.md`（即将写）。

---

## 8. 安全提示

⚠️ **当前默认配置不适合生产**：

| 风险 | 现状 | 建议 |
|---|---|---|
| 数据库密码 | `Pass@666`（弱） | 改强密码 + 用专用账户 |
| root 远程访问 | 默认开启（如果开了） | 关掉，用专用账户 |
| MySQL 公网暴露 | 3306 公开 | 加白名单（只允许阿里云 ECS IP） |
| SSL/TLS | 默认无加密 | MySQL 8 支持 native TLS，启用 |
| `WEB_DB_URL` 含密码 | 写到 .env | OK（.env 不提交），但生产用 secret manager |

### 8.1 推荐的安全配置（生产）

```bash
# 阿里云安全组规则：
#   MySQL 3306 只允许 ECS 内网 IP 段（如 172.16.0.0/12 或具体 ECS IP）
#   不要 0.0.0.0/0

# MySQL 用户权限：
#   不用 root，用专用账户 'ielts_app'
#   只授权 'ietls_learn_online' 库

# Web 端到 MySQL 用 SSL（如果同服务器，走 Unix socket 也行）
```

---

## 9. 常见问题

### Q1: Mac 远程连 MySQL 慢？

- 跨网络（家用宽带 → 阿里云）有 50-200ms 延迟，正常
- 如果太慢，把 MySQL 部署到 ECS 上（同内网）

### Q2: `init_mysql.sql` 是否会重复执行？

看 sql 文件头部：
> 幂等性：本脚本所有 CREATE/INSERT 使用 IF NOT EXISTS / IGNORE，
> 重复执行不会破坏现有数据。

可以放心多次跑（之前已经建过 19 张表，再跑不会破坏）。

### Q3: uvicorn 启动后 healthz 还是 `fallback_sqlite`？

- 检查 `.env` 里 `IELTS_BUDDY_WEB_DB_MODE=online`
- 检查 `IELTS_BUDDY_WEB_DB_URL` 是否正确
- 检查 uvicorn 启动日志，看 lifespan 里有没有 `mysql_reachable: false`

### Q4: 真机调试时 apiBaseUrl 是什么？

**LAN IP**：`http://172.20.10.2:8000`（Mac 的局域网 IP）
**不要用**：
- 127.0.0.1（手机连不上）
- 118.190.148.121（公网 MySQL 不是 Web API，手机也连不上 web）
- https://域名（备案未通过 + 强制 HTTPS 才要求）

### Q5: 数据有冲突吗？本地 SQLite 还有数据怎么办？

- 现在你的本地 SQLite `~/.ielts-buddy/ielts_buddy.db` 是**测试数据**
- 切到云端 MySQL 后，**所有新数据写云端**
- 旧 SQLite 数据**不会**自动同步到 MySQL（除非手动跑迁移脚本）
- 建议：用云端 MySQL 后，本地 SQLite 备份一下即可，不影响开发

---

## 10. 相关文档

- [07-MySQL模式启动指南.md](./07-MySQL模式启动指南.md) — 总览（3 种模式对比）
- [09-备案后部署指南.md](./09-备案后部署指南.md) — 待写（备案后部署到阿里云）
- [README.md](./README.md) — 项目入口
<!-- 2026-09-21 v1 -->
