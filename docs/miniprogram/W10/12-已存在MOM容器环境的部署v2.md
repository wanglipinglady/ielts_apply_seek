# ECS 已存在 MOM 容器的部署方案 v2（2026-09-29）

> **场景**：ECS 已有 Docker 容器 `mom-qa-mvp:1.0`（运行 uvicorn:8000 + Streamlit:8501）。
>
> **目标**：在不破坏 MOM 容器的前提下，新增个人网站 + 雅思备考助手。

---

## 1. 最终架构图

```
                              公网
                               ↓ HTTPS (TCP 443)
                    ┌────────────────────────┐
                    │ Nginx :443 (新装)        │
                    │ 域名路由 + TLS 终止    │
                    └──┬──────────┬──────────┘
                       │          │
        wanglipingresume.com      ielts.wanglipingresume.com
                       │          │
                       │          ↓
                       │   ┌──────────────────────┐
                       │   │ uvicorn:8001          │  ← 新增（雅思备考助手）
                       │   │ systemd 管理          │
                       │   └──────────────────────┘
                       ↓
            ┌──────────────────────┐
            │ /var/www/personal/    │  ← 新增（个人网站静态文件）
            └──────────────────────┘
            
            
                    已有的（不动）
            ┌──────────────────────────────────┐
            │ Docker: mom-qa-mvp:1.0          │
            │   ├─ uvicorn:8000  (FastAPI)    │
            │   └─ Streamlit:8501             │
            │                                 │
            │ MySQL :3306 (systemd 管)         │
            │ containerd (系统级)               │
            │ cloudmonitor/aegis/aliyun (阿里云) │
            └──────────────────────────────────┘
```

---

## 2. 端口分配（最终版）

| 端口 | 服务 | 状态 | 管理方式 |
|---|---|---|---|
| 22 | SSH | 已有 | systemd |
| 80 | Nginx HTTP | 🆕 新增 | systemd（跳转 HTTPS） |
| 443 | Nginx HTTPS | 🆕 新增 | systemd |
| 3306 | MySQL | 已有 | systemd |
| **8000** | **MOM FastAPI** | **不动** | **Docker 容器** |
| **8001** | **雅思备考助手** | 🆕 新增 | **systemd** |
| 8501 | Streamlit (MOM) | 不动 | Docker 容器 |

---

## 3. 实施步骤（每一步可直接复制执行）

### Step 1：装 Nginx（10 分钟）

```bash
sudo apt update
sudo apt install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
sudo systemctl status nginx
```

### Step 2：上传 SSL 证书到 ECS（5 分钟）

```bash
# === 在 Mac 上（密钥登录） ===
scp -i ~/Downloads/你的密钥.pem \
  ~/Downloads/27520228_wanglipingresume.com_nginx/wanglipingresume.com.pem \
  ~/Downloads/27520228_wanglipingresume.com_nginx/wanglipingresume.com.key \
  admin@118.190.148.121:/tmp/

# === 在 ECS 上 ===
sudo mkdir -p /etc/nginx/ssl/wanglipingresume.com
sudo mv /tmp/wanglipingresume.com.* /etc/nginx/ssl/wanglipingresume.com/
sudo chmod 600 /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.key
ls /etc/nginx/ssl/wanglipingresume.com/
```

### Step 3：个人网站静态文件（1 分钟）

```bash
sudo mkdir -p /var/www/personal
echo "<!DOCTYPE html>
<html>
<head><title>Wang Liping</title></head>
<body>
<h1>Wang Liping's Resume</h1>
<p>Welcome to my personal site.</p>
</body>
</html>" | sudo tee /var/www/personal/index.html
```

### Step 4：上传雅思备考助手代码（3 分钟）

```bash
# === 在 Mac 上 ===
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.venv' \
  --exclude='.runtime' --exclude='*.pyc' --exclude='.env' \
  -e "ssh -i ~/Downloads/你的密钥.pem" \
  /Users/wangliping/Public/selfProgram/ielts_apply_seek/ \
  admin@118.190.148.121:/opt/ielts_buddy/
```

### Step 5：装 Python 依赖（5 分钟）

```bash
# === 在 ECS 上 ===
cd /opt/ielts_buddy
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[web]"
```

### Step 6：写生产 .env（1 分钟）

```bash
cat > /opt/ielts_buddy/.env <<'EOF'
IELTS_BUDDY_WEB_DB_MODE=online
IELTS_BUDDY_WEB_DB_URL=mysql+pymysql://remote_user:Pass@666@127.0.0.1:3306/ietls_learn_online?charset=utf8mb4
IELTS_BUDDY_LLM_API_KEY=sk-cp-crF61iHIxekGHshefJm0zWb6GFmL0x_tV47xBBYok369iI92IEWjdym7l6UXHXO-EmSyNqtJvd6v3qcjZdS-CoXH63u9Bt3Zl-EcA2mIF8ggnQdARmVp34c
IELTS_BUDDY_LLM_BASE_URL=https://api.minimaxi.com/v1
IELTS_BUDDY_LLM_MODEL=MiniMax-M2.7-highspeed
IELTS_BUDDY_ENV=prod
TZ=Asia/Shanghai
IELTS_BUDDY_JWT_SECRET=$(openssl rand -base64 48)
IELTS_BUDDY_WECHAT_APPID=wx5aac958e916e8199
IELTS_BUDDY_WECHAT_SECRET=<你的 AppSecret>
chmod 600 /opt/ielts_buddy/.env
```

### Step 7：systemd 管 uvicorn:8001（3 分钟）

```bash
sudo vim /etc/systemd/system/ielts-web.service
```

写入：

```ini
[Unit]
Description=IELTS Buddy Web (FastAPI on port 8001)
After=network.target

[Service]
Type=simple
User=admin
Group=admin
WorkingDirectory=/opt/ielts_buddy
EnvironmentFile=/opt/ielts_buddy/.env
ExecStart=/opt/ielts_buddy/.venv/bin/uvicorn ielts_buddy.web.main:app --host 127.0.0.1 --port 8001 --workers 2
Restart=always
RestartSec=5
StandardOutput=append:/var/log/ielts-buddy/web.log
StandardError=append:/var/log/ielts-buddy/web-error.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/log/ielts-buddy
sudo systemctl daemon-reload
sudo systemctl enable ielts-web
sudo systemctl start ielts-web
sudo systemctl status ielts-web
```

### Step 8：Nginx 配置（5 分钟）

```bash
# 删默认 site
sudo rm /etc/nginx/sites-enabled/default

# 创建我们的配置
sudo vim /etc/nginx/sites-available/wanglipingresume
```

写入：

```nginx
# === 个人网站 ===
server {
    listen 80;
    server_name wanglipingresume.com www.wanglipingresume.com;
    return 301 https://wanglipingresume.com$request_uri;
}

server {
    listen 443 ssl http2;
    server_name wanglipingresume.com www.wanglipingresume.com;

    ssl_certificate     /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.pem;
    ssl_certificate_key /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    add_header Strict-Transport-Security "max-age=31536000" always;

    root /var/www/personal;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}

# === 雅思备考助手（8001 端口，避开 MOM 的 8000）===
server {
    listen 80;
    server_name ielts.wanglipingresume.com www.ielts.wanglipingresume.com;
    return 301 https://ielts.wanglipingresume.com$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ielts.wanglipingresume.com www.ielts.wanglipingresume.com;

    ssl_certificate     /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.pem;
    ssl_certificate_key /etc/nginx/ssl/wanglipingresume.com/wanglipingresume.com.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 30M;

    access_log /var/log/nginx/ielts-access.log;
    error_log  /var/log/nginx/ielts-error.log;

    location / {
        proxy_pass http://127.0.0.1:8001;        # ← 8001，不是 8000
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_read_timeout 60s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/wanglipingresume /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Step 9：验证（2 分钟）

```bash
# 雅思助手
curl http://127.0.0.1:8001/healthz | python3 -m json.tool
# 期望: db_mode=online, mysql_reachable=true

# Nginx 监听
ss -tlnp | grep -E ":80|:443|:8000|:8001|:8501"
# 期望看到 80 / 443 / 8000 (docker-proxy) / 8001 / 8501 (docker-proxy)

# 不动 Mom 容器
docker ps
# 应该看到 mom-qa-mvp 还在 Up
```

### Step 10：DNS 解析（备案通过后操作）

阿里云 DNS 控制台 → 添加 A 记录：

| 主机记录 | 类型 | 值 |
|---|---|---|
| `@` | A | 118.190.148.121 |
| `ielts` | A | 118.190.148.121 |
| `www` | A | 118.190.148.121 |

### Step 11：微信小程序公众平台

服务器域名：
- `https://ielts.wanglipingresume.com`（request / uploadFile / downloadFile）

---

## 4. 故障排查速查

| 症状 | 排查 |
|---|---|
| `502 Bad Gateway` | `systemctl status ielts-web` 看 uvicorn 是否在跑 |
| `connect refused :8001` | uvicorn 没起 / .env 配错 / MySQL 连不上 |
| `502 Bad Gateway` 但 uvicorn 在跑 | 看 `/var/log/nginx/ielts-error.log` |
| SSL 握手失败 | `nginx -t` 测配置 + `openssl x509 ... \| grep DNS:` 看证书 |
| `upstream timeout` | uvicorn 进程卡死，看 `/var/log/ielts-buddy/web-error.log` |
| MOM 系统突然挂了 | **不要碰！** 看 `docker logs mom-qa-mvp` 自己排 |

---

## 5. 验证清单

部署完成后逐项打勾：

| 检查项 | 命令 | 期望 |
|---|---|---|
| Nginx 在跑 | `systemctl status nginx` | active |
| Nginx 配置 OK | `nginx -t` | syntax is ok |
| Nginx 监听 80/443 | `ss -tlnp \| grep -E ":80 \|:443 "` | LISTEN |
| uvicorn:8001 在跑 | `systemctl status ielts-web` | active |
| uvicorn 健康 | `curl http://127.0.0.1:8001/healthz` | 200 + db_mode=online |
| MOM 容器还活着 | `docker ps` | mom-qa-mvp Up (healthy) |
| 个人网站可访问 | `curl https://127.0.0.1/ -H "Host: wanglipingresume.com"` | 200 + HTML |
| 雅思助手可访问 | `curl https://127.0.0.1/ -H "Host: ielts.wanglipingresume.com"` | 200 + JSON |

---

## 6. 重要提醒

| ❌ 不要做 | ✅ 要做 |
|---|---|
| 不要 `docker stop mom-qa-mvp` | 只在自己 /opt/ielts_buddy 操作 |
| 不要重启 supervisor | 它空跑，不用管 |
| 不要改 MySQL 端口 | 已有 MOM 系统在用 |
| 不要碰 aegis / aliyun / cloudmonitor | 阿里云内置监控 |

---

## 7. 应急回滚

如果部署出问题需要回滚：

```bash
# 1. 停 uvicorn:8001
sudo systemctl stop ielts-web
sudo systemctl disable ielts-web

# 2. 关 Nginx
sudo systemctl stop nginx
sudo systemctl disable nginx
sudo apt remove nginx -y

# 3. 删除部署文件
sudo rm -rf /opt/ielts_buddy
sudo rm -rf /etc/nginx/ssl/wanglipingresume.com
sudo rm -rf /var/www/personal
sudo rm -rf /var/log/ielts-buddy

# 4. MOM 系统完全不受影响（验证）
docker ps  # 应该看到 mom-qa-mvp 仍然 Up
curl http://118.190.148.121:8000/healthz  # MOM 应该还能访问
```

---

## 8. 时间估算

| 步骤 | 时间 |
|---|---|
| Step 1-2：装 Nginx + 上传证书 | 15 分钟 |
| Step 3-4：网站 + 上传代码 | 5 分钟 |
| Step 5-6：装依赖 + 写 .env | 5 分钟 |
| Step 7：systemd | 3 分钟 |
| Step 8-9：Nginx 配置 + 验证 | 5 分钟 |
| Step 10-11：DNS + 公众平台 | 5 分钟（备案后） |
| **总计（不含备案）** | **约 40 分钟** |

---

## 9. 完成后给项目地图的更新

部署完后我会把这次的实操经验（Docker 容器共存、端口 8001 选择、supervisor 空跑的处理）固化到 `W10/12-已存在MOM容器环境的部署v2.md`（本文档），下次类似环境直接用。
<!-- v2 spacer 1 -->
