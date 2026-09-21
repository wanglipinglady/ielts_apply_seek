# IELTS Buddy · 本地开发 / 部署 (deploy/)

> 一键启动 MySQL + Web 后端，用于备案前的本地联调。
> 备案通过后，改 `IELTS_BUDDY_WEB_DB_URL` 即可指向云端 MySQL。

---

## 📋 文件清单

| 文件 | 用途 |
|---|---|
| `docker-compose.yml` | 一键起 MySQL + Web |
| `Dockerfile` | Web 后端镜像构建（依赖项目根 pyproject.toml） |
| `.env.dev.example` | 环境变量模板（复制为 `.env` 后填真实值） |
| `dev.sh` | 一键启动脚本（推荐用法） |

---

## 🚀 快速启动

### 前置

**必须**：装 Docker（任选一种）

```bash
# OrbStack（推荐，macOS 轻量）
brew install --cask orbstack

# Docker Desktop（功能全）
brew install --cask docker

# Colima（开源）
brew install colima docker docker-compose
colima start
```

### 启动

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek/deploy

# 1. 复制环境模板
cp .env.dev.example .env

# 2. 编辑 .env 填入真实 LLM_API_KEY
nano .env   # 或 vim .env

# 3. 一键启动
bash dev.sh

# 输出会显示：
# - 服务状态
# - healthz 健康检查（确认 db_mode=online, mysql_reachable=true）
# - 访问 URL
# - 真机调试提示
```

### 验证

```bash
curl http://127.0.0.1:8000/healthz | python3 -m json.tool
```

期望：
```json
{
  "status": "ok",
  "db_mode": "online",
  "mysql_reachable": true,
  ...
}
```

---

## 🛠️ 常用命令

```bash
# 启动（默认）
bash dev.sh

# 清数据重启
bash dev.sh --reset

# 停止（保留数据）
bash dev.sh --stop

# 停止 + 删数据
bash dev.sh --purge

# 看日志（follow）
bash dev.sh --logs

# 状态
bash dev.sh --status
```

---

## 📱 真机调试（小程序）

1. 启动后端后（`db_mode=online`），改 `miniprogram/app.js`：
   ```js
   apiBaseUrl: 'http://<Mac LAN IP>:8000'  // 例: 'http://172.20.10.2:8000'
   ```

2. 微信开发者工具 → 真机调试 → 自动预览 → 扫码

3. 跟之前流程一样：登录 → 学习 → 复习 → 口语录音 → 评分

4. **数据会写入 Docker 里的 MySQL**，重启容器数据还在

---

## 🗄️ 直接操作 MySQL

```bash
# 进入容器内的 mysql shell
docker exec -it ielts-mysql mysql -uroot -prootpass_dev_only ietls_learn_online

# 或从 Mac 直连（端口 3306 已暴露）
mysql -h 127.0.0.1 -u ielts_app -papppass_dev_only ietls_learn_online

# 常用查询
SHOW TABLES;
SELECT COUNT(*) FROM web_user;
SELECT id, email, created_at FROM web_user ORDER BY id DESC LIMIT 5;
SELECT * FROM speaking_practice_records ORDER BY id DESC LIMIT 5;
SELECT id, word, wrong_count FROM mistakes ORDER BY wrong_count DESC LIMIT 10;
```

---

## 🔧 备案后切到云端 MySQL

只需改 `.env` 的 `IELTS_BUDDY_WEB_DB_URL`：

```bash
# 从本地 MySQL 改为云端
# IELTS_BUDDY_WEB_DB_URL=mysql+pymysql://ielts_app:pwd@mysql:3306/ietls_learn_online?charset=utf8mb4
IELTS_BUDDY_WEB_DB_URL=mysql+pymysql://ielts_app:pwd@<阿里云 host>:3306/ietls_learn_online?charset=utf8mb4

# 重启
bash dev.sh --stop
bash dev.sh
```

---

## 🛑 常见问题

### Docker daemon not running

启动 Docker Desktop / OrbStack / Colima，再重试。

### mysql_reachable: false

```bash
# 1. 看 mysql 容器日志
docker logs ielts-mysql --tail=50

# 2. 看 healthcheck
docker inspect ielts-mysql --format='{{.State.Health.Status}}'

# 3. 进入容器手动测
docker exec -it ielts-mysql mysql -uroot -p
#   SHOW DATABASES;
#   USE ietls_learn_online;
#   SHOW TABLES;
```

### Web 容器起不来

```bash
docker logs ielts-web --tail=50
```

常见原因：
- LLM_API_KEY 不对 → 改成 mock 也能起
- MySQL 没起来 → `depends_on: service_healthy` 会等 30s 重试

### 数据被清掉了

```bash
# 找最后一次 reset 之前的容器（如果没 purge volume）
docker volume ls | grep mysql_data
```

> 一旦 `bash dev.sh --purge` 执行，volume 真删，数据不可恢复。**生产前务必做 snapshot 备份**。

### 端口冲突（8000 / 3306）

改 `docker-compose.yml`：
```yaml
ports:
  - "18000:8000"   # 改成其他端口
  - "13306:3306"
```

---

## 📚 相关文档

- [07-MySQL模式启动指南.md](../docs/miniprogram/W10/07-MySQL模式启动指南.md)
- [README.md](../docs/miniprogram/W10/README.md)

---

## 🎯 部署架构示意

```
┌─────────────────────────────────────────────────────┐
│                   Mac 本机                            │
│                                                      │
│  ┌──────────────┐                                   │
│  │ 微信开发者工具│                                   │
│  │ + 真机调试   │                                   │
│  └──────┬───────┘                                   │
│         │ HTTP                                      │
│         └─────────────┐  │
│  ┌───  Docker  ────┐  │
│  │                  │  │
│  │  ┌────────────┐ │  │
│  │  │ ielts-web  │ │  │   ← 容器 1：FastAPI + uvicorn
│  │  │ :8000      │◄┼──┘
│  │  └────────────┘ │
│  │        │         │
│  │  ┌────────────┐ │
│  │  │ ielts-mysql│ │   ← 容器 2：MySQL 8.0
│  │  │ :3306      │ │
│  │  └────────────┘ │
│  │                  │
│  └──────────────────┘
│
│  volumes:
│    - mysql_data:/var/lib/mysql      ← MySQL 数据持久化
│    - audio_data:/root/.ielts-buddy  ← 录音文件持久化
│    - whisper_models:/root/.cache    ← Whisper 模型持久化
└─────────────────────────────────────────────────────┘

备案后：
   docker compose 整个替换为云端
   - Web 容器 → 阿里云 ECS（跑 systemd + uvicorn）
   - MySQL 容器 → 阿里云 RDS for MySQL（托管）
   - 加 Nginx 反向代理 + HTTPS
```