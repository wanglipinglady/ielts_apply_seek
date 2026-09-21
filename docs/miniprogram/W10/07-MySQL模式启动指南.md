# MySQL 模式启动指南（v3.9 / 2026-09-21）

> **场景**：微信小程序开发告一段落，需切换后端从 SQLite 到 MySQL 模式，测试 Web 端在真实数据库下的行为。
> **当前约束**：等阿里云服务器备案审核通过后才能联调云端 MySQL；**本地 MySQL 可立即开发联调**。
> **本文档**：分 3 种模式给出完整步骤 + 常见坑。

---

## 1. 三种 MySQL 模式速查

| 模式 | 数据存储 | 适用 | 启动难度 |
|---|---|---|---|
| **fallback_sqlite**（默认 online 模式失败） | `~/.ielts-buddy/ielts_buddy.db` | 本地开发调试 | ⭐ 最简单 |
| **本地 MySQL** | Mac 本机 MySQL | 备案前的本地联调 | ⭐⭐ 中等 |
| **云端 MySQL** | 阿里云服务器（备案后） | 生产 / 真机发布 | ⭐⭐⭐ 多配置 |

**当前项目状态**：所有 API（Web / 小程序）已经支持 SQLite 和 MySQL 双实现（`repositories/sqlite_repo.py` + `repositories/mysql_repo.py`），不需要改代码。

---

## 2. 模式 1：fallback_sqlite（当前已经在用）

### 启动命令

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
export IELTS_BUDDY_LLM_API_KEY="sk-cp-..."
export IELTS_BUDDY_LLM_BASE_URL="https://api.minimaxi.com/v1"
export IELTS_BUDDY_LLM_MODEL="MiniMax-M2.7-highspeed"
PYTHONPATH=src uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000
```

### 原理

- 默认 `WEB_DB_MODE=online`，启动时尝试连阿里云 MySQL
- 连不上 → **自动降级** 到 SQLite 模式（`app.state.db_mode="fallback_sqlite"`）
- 所有读写走本地 SQLite

### 验证

```bash
curl http://127.0.0.1:8000/healthz | python3 -m json.tool
# 看 db_mode 字段：
# - "fallback_sqlite"：连不上 MySQL，自动降级（✅ 你看到的）
# - "online"：连上 MySQL（这是备案后要达到的目标）
```

### 何时用

- 当前所有开发 / 真机调试都用这个
- 不需要安装 MySQL server
- 数据存在本地 `~/.ielts-buddy/ielts_buddy.db`

---

## 3. 模式 2：本地 MySQL（备案前的本地联调方案）

> **目的**：在备案审核完成前，本地装一个 MySQL server，验证所有功能在 MySQL 模式下能正常工作（为备案后的云端部署做演练）。

### 3.1 安装 MySQL（macOS）

```bash
# Homebrew 安装（推荐）
brew install mysql

# 启动服务
brew services start mysql
# 或前台跑：
mysql.server start

# 安全初始化（设 root 密码）
mysql_secure_installation
```

### 3.2 建库 + 导入 schema

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek

# 1. 手动建库（脚本不自动 CREATE DATABASE）
mysql -u root -p -e "CREATE DATABASE ietls_learn_online CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
# 或显式：
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS ietls_learn_online CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 2. 跑 init_mysql.py 初始化脚本（推荐 - 自动跑 schema + 种子数据）
python scripts/init_mysql.py \
  --host 127.0.0.1 \
  --user root \
  --password <your_password> \
  --database ietls_learn_online

# 3. 验证
python scripts/init_mysql.py \
  --host 127.0.0.1 \
  --user root \
  --password <your_password> \
  --check-only
```

### 3.3 启动 Web 端（连本地 MySQL）

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek

# 显式提供 MySQL URL（强制走本地 MySQL，不再自动 fallback）
export IELTS_BUDDY_WEB_DB_MODE=online
export IELTS_BUDDY_WEB_DB_URL="mysql+pymysql://root:<your_password>@127.0.0.1:3306/ietls_learn_online?charset=utf8mb4"

# 其他 env（不变）
export IELTS_BUDDY_LLM_API_KEY="sk-cp-..."
export IELTS_BUDDY_LLM_BASE_URL="https://api.minimaxi.com/v1"
export IELTS_BUDDY_LLM_MODEL="MiniMax-M2.7-highspeed"

# 启动（必须用 0.0.0.0，让手机连）
PYTHONPATH=src uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000
```

### 3.4 验证是否真的连上 MySQL

```bash
curl http://127.0.0.1:8000/healthz | python3 -m json.tool
```

期望：
```json
{
  "db_mode": "online",          ← 关键：不是 fallback_sqlite
  "mysql_reachable": true,      ← 关键：true
  "prefer_mode": "online",
  ...
}
```

### 3.5 验证小程序端能正常用

- 微信开发者工具 → 真机调试 → 扫码
- 测试关键流程：登录 → 学习 → 复习 → 口语录音 → 评分
- 在 MySQL 里查数据确认：
  ```bash
  mysql -u root -p ietls_learn_online
  SHOW TABLES;
  SELECT COUNT(*) FROM web_user;
  SELECT COUNT(*) FROM learning_records;
  SELECT COUNT(*) FROM speaking_practice_records;
  ```

---

## 4. 模式 3：云端 MySQL（备案通过后）

### 4.1 前置准备

- [ ] 阿里云服务器 ECS / RDS for MySQL 已购买
- [ ] 备案通过（域名可访问）
- [ ] 服务器安全组规则：放行 3306（仅内网）或公网（看部署模式）
- [ ] MySQL 已创建库 `ietls_learn_online`（utf8mb4）
- [ ] 已执行 `scripts/init_mysql.sql`（建表 + 种子数据）
- [ ] 已创建专用 MySQL 用户（不要用 root），授权对 `ietls_learn_online` 的权限

### 4.2 创建专用 MySQL 用户（推荐）

```sql
-- 在阿里云 MySQL 上执行
CREATE USER 'ielts_app'@'<server_ip>' IDENTIFIED BY '<strong_password>';
GRANT ALL PRIVILEGES ON ietls_learn_online.* TO 'ielts_app'@'<server_ip>';
FLUSH PRIVILEGES;
```

### 4.3 后端环境变量（部署到阿里云时）

```bash
# === 数据库 ===
export IELTS_BUDDY_WEB_DB_MODE=online
export IELTS_BUDDY_WEB_DB_URL="mysql+pymysql://ielts_app:<password>@<阿里云 MySQL host>:3306/ietls_learn_online?charset=utf8mb4"

# === LLM（不变） ===
export IELTS_BUDDY_LLM_API_KEY="sk-cp-..."
export IELTS_BUDDY_LLM_BASE_URL="https://api.minimaxi.com/v1"
export IELTS_BUDDY_LLM_MODEL="MiniMax-M2.7-highspeed"

# === JWT / 安全 ===
export IELTS_BUDDY_ENV=prod                                       # 关键：开启生产模式
export IELTS_BUDDY_JWT_SECRET=$(openssl rand -base64 48)          # 强制设置 JWT 密钥
export IELTS_BUDDY_ADMIN_RESET_TOKEN=$(openssl rand -base64 32)   # 强制设置 admin token

# === 微信小程序 ===
export IELTS_BUDDY_WECHAT_APPID="wx5aac958e916e8199"
export IELTS_BUDDY_WECHAT_SECRET="<微信小程序 AppSecret>"

# === Web ===
export IELTS_BUDDY_WEB_HOST=0.0.0.0
export IELTS_BUDDY_WEB_PORT=8000

# === 启动命令 ===
PYTHONPATH=src uvicorn ielts_buddy.web.main:app \
  --host 0.0.0.0 --port 8000 --workers 4   # 生产建议多 worker
```

### 4.4 小程序端配置（备案后的域名）

```javascript
// miniprogram/app.js
apiBaseUrl: 'https://<你的备案域名>:8000'   // 例: https://ielts.example.com:8000
```

同时需要在微信公众平台 → 开发管理 → 服务器域名 配置：

| 域名类型 | 域名 |
|---|---|
| request 合法域名 | https://ielts.example.com:8000 |
| uploadFile 合法域名 | https://ielts.example.com:8000 |
| downloadFile 合法域名 | https://ielts.example.com:8000 |

> **注意**：微信要求域名是 **https** + **已备案** + **TLS 1.2+**。

### 4.5 反向代理 + HTTPS（强烈推荐）

不要让 uvicorn 直接暴露在公网，建议架构：

```
用户 / 微信小程序
   ↓ HTTPS
Nginx (80/443, TLS 终止)
   ↓ HTTP (内网)
uvicorn (127.0.0.1:8000)
   ↓
MySQL (127.0.0.1:3306)
```

**Nginx 配置示例**（`/etc/nginx/sites-available/ielts`）：

```nginx
server {
    listen 443 ssl;
    server_name ielts.example.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    # 微信小程序要求的 HSTS
    add_header Strict-Transport-Security "max-age=31536000" always;

    client_max_body_size 30M;  # 录音上传大小

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket / 长连接支持
        proxy_http_version 1.1;
        proxy_read_timeout 60s;
    }
}
```

### 4.6 验证生产环境

```bash
# 在阿里云服务器上
curl http://127.0.0.1:8000/healthz
# 期望 db_mode=online, mysql_reachable=true

# 从外部（你的笔记本）
curl https://ielts.example.com:8000/healthz
# 同样期望

# 测试 HTTPS
curl -vI https://ielts.example.com 2>&1 | grep -i "TLS"
```

---

## 5. 三种模式对照表

| 维度 | fallback_sqlite | 本地 MySQL | 云端 MySQL |
|---|---|---|---|
| 是否需要 MySQL server | ❌ | ✅ 本机装 | ✅ 云端服务器 |
| 是否能跨设备同步 | ❌ 仅本机 | ❌ 仅本机 | ✅ |
| 是否要备案域名 | ❌ | ❌ | ✅ |
| 真机调试 | ✅ LAN IP | ✅ LAN IP | ✅ 备案域名 |
| 数据隔离 | 用户本地 | 用户本地 | 云端共享 |
| 何时用 | 当前所有开发 | 备案前本地联调 | 备案后生产 |

---

## 6. 常见问题

### Q1：启动报错 `pymysql.cursors.Cursor` 找不到？

```bash
# 安装依赖
pip install pymysql cryptography

# 如果用 venv
.venv/bin/pip install pymysql cryptography
```

### Q2：`mysql_reachable: false` 但 MySQL 明明在跑？

**排查清单**：
- [ ] MySQL 服务在监听 3306？`lsof -i :3306`
- [ ] 防火墙允许 3306？`sudo ufw status`（Linux）/ macOS 默认允许
- [ ] `IELTS_BUDDY_WEB_DB_URL` 格式正确？必须 `mysql+pymysql://...`
- [ ] 用户名/密码对？MySQL 8.0 默认 caching_sha2 密码，pymysql 需要 `cryptography` 包
- [ ] 数据库 `ietls_learn_online` 存在？`SHOW DATABASES;`

### Q3：连上 MySQL 但表不存在？

**需要跑 init 脚本**：
```bash
python scripts/init_mysql.py \
  --host <host> \
  --user <user> \
  --password <password> \
  --database ietls_learn_online
```

或者手动：
```bash
mysql -h <host> -u <user> -p ietls_learn_online < scripts/init_mysql.sql
```

### Q4：报 `Access denied for user 'root'@'localhost'`？

- MySQL 8.0 默认 root 用 auth_socket（不是密码）
- 改成 mysql_native_password：
  ```sql
  ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'your_password';
  FLUSH PRIVILEGES;
  ```
- 或者创建新用户专门给应用

### Q5：fallback 模式 vs 强制 online 模式有什么区别？

- **fallback 模式**（默认）：尝试连 MySQL，连不上自动降级到 SQLite。**适合开发**（避免 MySQL 挂了导致 web 起不来）。
- **强制 online 模式**（`IELTS_BUDDY_WEB_DB_MODE=online` + 提供 `WEB_DB_URL`）：如果 MySQL 连不上，**应用启动失败**。**适合生产**（确保不会"误降级"成 SQLite 写脏数据）。

### Q6：sync_meta 表的 last_error 怎么处理？

```bash
curl http://127.0.0.1:8000/healthz | python3 -m json.tool
```

看 `sync.last_error`。常见错误：
- 网络问题（公网 MySQL 防火墙 / 带宽）
- 字段类型不匹配（schema 升级未跑）
- 列名差异（MySQL vs SQLite SQL 兼容性问题）

### Q7：本地 MySQL 模式跑了一段时间，deploy 到云端怎么迁移数据？

```bash
# 1. 导出本地数据（如果有需要）
mysqldump -u root -p ietls_learn_online > backup.sql

# 2. 在云端 MySQL 创建库
mysql -h <cloud_host> -u <user> -p \
  -e "CREATE DATABASE ietls_learn_online CHARACTER SET utf8mb4;"

# 3. 导入
mysql -h <cloud_host> -u <user> -p ietls_learn_online < backup.sql
```

或写迁移脚本（推荐，分批 + 错误重试）。

---

## 7. 推荐路径

### 备案前（现在）

**强烈推荐用「模式 2：本地 MySQL」** 做以下准备：

1. 装 MySQL → 跑 init 脚本
2. 把后端切到本地 MySQL 模式
3. **真机调试**：用本地 MySQL 测试所有功能
4. 验证 web 端 + 小程序端都没问题
5. **模拟云端失败**：故意把 MySQL 关掉，看是否正确报错（不是误降级到 SQLite）

这样备案通过后，切到云端几乎零风险。

### 备案中

继续用 fallback_sqlite（不依赖网络），开发新功能。

### 备案后

切换到「模式 3：云端 MySQL」：
- 改 `.env`（或 systemd EnvironmentFile）里的 `IELTS_BUDDY_WEB_DB_URL`
- 改 `app.js` 的 `apiBaseUrl` 到备案域名
- 配置 Nginx + HTTPS
- 配置微信公众平台服务器域名
- 上传小程序代码审核

---

## 8. 相关文件

| 文件 | 用途 |
|---|---|
| `src/ielts_buddy/web/config.py` | DB 模式 + URL 读取 |
| `src/ielts_buddy/repositories/mysql_repo.py:2467` | MySQL URL 构建 |
| `src/ielts_buddy/repositories/fallback_repo.py` | online/sqlite 自动 fallback |
| `scripts/init_mysql.sql` | 建表 DDL + 种子数据 |
| `scripts/init_mysql.py` | 执行器 |
| `scripts/migrate_v3_mysql_schema.py` | v3 schema 迁移 |
| `src/ielts_buddy/web/main.py:78` | lifespan 启动逻辑 |

---

## 9. 快速命令参考

```bash
# === 模式 1：fallback（默认） ===
PYTHONPATH=src uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000

# === 模式 2：本地 MySQL ===
export IELTS_BUDDY_WEB_DB_MODE=online
export IELTS_BUDDY_WEB_DB_URL="mysql+pymysql://root:pwd@127.0.0.1:3306/ietls_learn_online?charset=utf8mb4"
PYTHONPATH=src uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000

# === 模式 3：云端 MySQL（备案后） ===
export IELTS_BUDDY_ENV=prod
export IELTS_BUDDY_WEB_DB_MODE=online
export IELTS_BUDDY_WEB_DB_URL="mysql+pymysql://ielts_app:pwd@<cloud_host>:3306/ietls_learn_online?charset=utf8mb4"
export IELTS_BUDDY_JWT_SECRET="$(openssl rand -base64 48)"
export IELTS_BUDDY_ADMIN_RESET_TOKEN="$(openssl rand -base64 32)"
export IELTS_BUDDY_WECHAT_APPID="wx5aac958e916e8199"
export IELTS_BUDDY_WECHAT_SECRET="<app_secret>"
PYTHONPATH=src uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000 --workers 4

# === 验证 ===
curl http://127.0.0.1:8000/healthz | python3 -m json.tool
```

---

## 10. 相关文档

- 设计文档：`docs/miniprogram/W10/01-小程序功能设计文档.md`
- 三端协同：`docs/miniprogram/W10/02-三端协同设计.md`
- Spec 沉淀：`docs/miniprogram/W10/04-Spec沉淀.md`
- 入口导航：`docs/miniprogram/W10/README.md`