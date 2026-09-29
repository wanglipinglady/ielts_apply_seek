# Docker、Supervisor、Nginx 三者关系与实际部署指南（2026-09-29）

> **场景**：你的 ECS 已有 Streamlit + uvicorn agent 系统用 supervisor 管理，80/443 端口空着。
>
> **本文目的**：澄清 Docker / Supervisor / Nginx 各自做什么，互相怎么协作。

---

## 1. 三者各是什么？

### 1.1 Nginx（**Web 服务器 / 反向代理**）

```
定位：在公网 80/443 端口监听，转发到内网应用
```

- 用户请求先到 Nginx → Nginx 看域名 → 转发到对应后端
- **不跑业务逻辑**，只起"路由 + TLS + 静态文件"作用
- 类比：**前台接待员**（不管业务细节）

### 1.2 Docker（**容器化部署**）

```
定位：把一个应用 + 它的所有依赖打包成"集装箱"，在隔离环境里跑
```

- 每个容器是一个独立的 Linux 子系统
- 例：你的 ECS 里 `/usr/local/bin/uvicorn` 实际上可能是 Docker 容器内运行的（PID 485263 是 docker-proxy）
- 类比：**集装箱房**（自包含、可丢包）

### 1.3 Supervisor（**进程管理器**）

```
定位：守护一个进程，挂了自动重启，提供 Web 控制台
```

- 比 systemd 更轻量，常用在 Docker 容器里
- 你的 ECS 上 PID 1412717 是 `supervisord -c /etc/supervisor/supervisord.conf`
- 类比：**保安 + 维修工**（应用挂了，自动重启）

---

## 2. 三者关系（一图说清）

```
                   公网（用户）
                       │
                       │ HTTPS (TCP 443)
                       ↓
┌──────────────────────────────────────┐
│ Nginx :443 (新装)                       │
│  - SSL 终止                            │
│  - 域名路由                             │
│  - 反向代理到内网                       │
└──────┬─────────────────────────┬───────┘
       │                         │
       │ wanglipingresume.com     │ ielts.wanglipingresume.com
       ↓                         ↓
┌──────────────┐          ┌─────────────────┐
│ /var/www/     │          │ uvicorn:8000    │
│ 静态 HTML    │          │ (雅思备考助手)   │
└──────────────┘          └─────────────────┘
                                      │
                                      │ (现在的 8000 已被占用)
                                      ↓
                              ┌─────────────────┐
                              │ uvicorn:8000    │
                              │ (Streamlit 系统)│
                              └─────────────────┘

进程管理：
- Supervisor 管 Streamlit + uvicorn（agent MOM）
- systemd 管 Nginx（即将安装）
```

**关键点**：
- **Nginx 必须装**（目前没装）
- **后端 2 个 uvicorn 进程都监听 8000 端口 → 冲突**
- **Streamlit 已经用 Supervisor 管了**
- **新部署的 雅思备考助手 也可以用 Supervisor 管**（保持一致）

---

## 3. 你的具体问题：电子 MOM 系统会和 Nginx 部署冲突吗？

### 3.1 短回答：**不会冲突**，但需要规划端口

| 资源 | 现状 | 部署 Nginx 后 |
|---|---|---|
| 端口 80 | 空 | Nginx 占用（HTTP 跳转） |
| 端口 443 | 空 | Nginx 占用（HTTPS） |
| 端口 8000 | uvicorn（agent MOM） | Nginx 反代到 8000 = 转发请求到 8000 |
| 端口 8501 | Streamlit | **没人转发**（你之前应该用别的入口访问） |

### 3.2 端口冲突的解决方案

雅思备考助手也需要 8000，但 8000 已经被占用。3 个方案：

| 方案 | 端口分配 | 复杂度 |
|---|---|---|
| **方案 A**：雅思助手改用 8001 | MOM: 8000, 雅思: 8001 | 简单 |
| **方案 B**：把 MOM 改成 8002 | MOM: 8002, 雅思: 8000 | 中等 |
| **方案 C**：都放到 8000 但不同路径 | MOM: 8000/mom/, 雅思: 8000/ielts/ | 复杂（需改 MOM 代码） |

**推荐方案 A**（最小改动）：
- MOM 不动（8000 继续）
- 雅思用 8001
- Nginx 配置：
  ```nginx
  location / {  # 雅思（新增）
      proxy_pass http://127.0.0.1:8001;
  }
  ```

但 MOM 的 8000 现在没人转发（你的截图显示 `ss -tlnp` 只监听了 8000，没看到别人加端口给它反代）。MOM 现在是直接访问 `IP:8000` 吗？这个需要确认。

### 3.3 域名分配

| 域名 | 后端 | 端口 |
|---|---|---|
| `wanglipingresume.com` | 静态网站 | `/var/www/` |
| `ielts.wanglipingresume.com` | 雅思备考助手 uvicorn | 8001（推荐） |
| （MOM 系统的域名）| 8501（Streamlit）或 8000（uvicorn）| 看实际情况 |

### 3.4 不修改现有系统能做吗？

**可以**。只要：

1. ✅ 不动 supervisor 配置（继续管 MOM）
2. ✅ 不改 MOM 的 8000 端口
3. ✅ 不重启用 Nginx 之外的任何服务
4. ✅ Nginx 配置时只 listen 443，不动 8000 / 8501

**所有改动只新增**，不动现有的：
- 新增 Nginx（监听 80/443）
- 新增 雅思备考助手 uvicorn（监听 8001）
- 新增 systemd service 管 Nginx（不取代 supervisor）

---

## 4. 部署架构（新方案）

```
                    公网
                     ↓
       ┌──────────────────────────┐
       │ Nginx :443 (HTTPS)        │  ← 新装
       │  - SSL 终止              │
       │  - 域名路由              │
       └──────┬─────────┬─────┬───┘
              │         │     │
              ↓         ↓     ↓
   ┌────────────┐  ┌────────────┐  ┌─────────────┐
   │ /var/www/  │  │ uvicorn    │  │ uvicorn     │
   │ 静态网站    │  │ 雅思助手    │  │ MOM 系统     │
   │ (新)        │  │ (新):8001  │  │ (旧):8000   │
   └────────────┘  └────────────┘  └─────────────┘
                          │                 │
                       systemd 管       supervisor 管
                       (新)             (旧，不动)
```

---

## 5. 实施步骤（基于你的实际情况）

### 5.1 不需要做的（保留现状）

- ❌ 不动 supervisor
- ❌ 不动 MOM 系统的 uvicorn 进程
- ❌ 不动 Streamlit 进程
- ❌ 不动 8501 端口
- ❌ 不动任何 systemd 内置服务

### 5.2 需要做的

#### A. 安装 Nginx（10 分钟）

```bash
sudo apt update
sudo apt install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
sudo systemctl status nginx
```

#### B. 上传 SSL 证书（5 分钟）

```bash
# 在 Mac 上传（用密钥登录）
scp -i ~/Downloads/你的密钥.pem 你的证书.pem root@118.190.148.121:/tmp/

# 在 ECS 上
sudo mkdir -p /etc/nginx/ssl/wanglipingresume.com
sudo mv /tmp/*.pem /etc/nginx/ssl/wanglipingresume.com/
sudo chmod 600 /etc/nginx/ssl/wanglipingresume.com/*.key
```

#### C. 部署雅思备考助手（30 分钟）

```bash
# 1. 上传代码
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='.venv' \
  --exclude='.runtime' --exclude='*.pyc' \
  /Users/wangliping/Public/selfProgram/ielts_apply_seek/ \
  admin@118.190.148.121:/opt/ielts_buddy/

# 2. 安装依赖
ssh admin@118.190.148.121
cd /opt/ielts_buddy
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[web]"

# 3. .env（生产）
cat > /opt/ielts_buddy/.env <<'EOF'
IELTS_BUDDY_WEB_DB_MODE=online
IELTS_BUDDY_WEB_DB_URL=mysql+pymysql://remote_user:Pass@666@127.0.0.1:3306/ietls_learn_online?charset=utf8mb4
IELTS_BUDDY_LLM_API_KEY=sk-cp-...
IELTS_BUDDY_LLM_BASE_URL=https://api.minimaxi.com/v1
IELTS_BUDDY_LLM_MODEL=MiniMax-M2.7-highspeed
IELTS_BUDDY_ENV=prod
TZ=Asia/Shanghai
IELTS_BUDDY_JWT_SECRET=<openssl rand -base64 48>
IELTS_BUDDY_WECHAT_APPID=wx5aac958e916e8199
IELTS_BUDDY_WECHAT_SECRET=<your_app_secret>
EOF
chmod 600 /opt/ielts_buddy/.env

# 4. 启动 uvicorn（8001，不冲突）
/opt/ielts_buddy/.venv/bin/uvicorn ielts_buddy.web.main:app \
  --host 127.0.0.1 --port 8001 --workers 2 &
disown

# 5. 测一下
curl http://127.0.0.1:8001/healthz
```

#### D. 配置 Nginx（10 分钟）

```bash
sudo vim /etc/nginx/sites-available/ielts
```

```nginx
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

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_read_timeout 60s;
    }
}

# 个人网站静态
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

    root /var/www/personal;
    index index.html;
    location / { try_files $uri $uri/ =404; }
}
```

```bash
sudo mkdir -p /var/www/personal
echo "<h1>Wang Liping's Resume</h1>" > /var/www/personal/index.html
sudo ln -s /etc/nginx/sites-available/ielts /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### E. DNS 解析（重要！备案后才有）

阿里云 DNS 控制台 → 添加：
| 主机记录 | 类型 | 值 |
|---|---|---|
| `@` | A | 118.190.148.121 |
| `ielts` | A | 118.190.148.121 |
| `www` | A | 118.190.148.121 |

#### F. 微信小程序公众平台

服务器域名：
- `https://ielts.wanglipingresume.com`（request / uploadFile / downloadFile）

`app.js`：
```javascript
apiBaseUrl: 'https://ielts.wanglipingresume.com'
debug: false
```

---

## 6. 故障排查速查

| 症状 | 排查 |
|---|---|
| Nginx 启动失败 | `sudo nginx -t` 看配置错误 |
| 502 Bad Gateway | uvicorn 没起？`curl http://127.0.0.1:8001/healthz` |
| MOM 系统挂了 | `supervisorctl status`（**不要重启 supervisor**） |
| 端口冲突 | `sudo ss -tlnp` 看谁占 8000 / 8001 / 8501 |
| SSL 握手失败 | `openssl x509 -in ...pem -text -noout \| grep DNS:` |

---

## 7. 关键概念再强化

| 概念 | 你的理解 | 实际 |
|---|---|---|
| Docker | 部署后端 | ❌ Docker 是**容器化**工具，部署**任意应用**（后端 / 前端 / 数据库） |
| Nginx | 部署前端 | ❌ Nginx 是**Web 服务器**，跑**静态文件 + 反向代理**（前端代码可以放在 Nginx 后面，也可以放在任何静态文件服务器后面） |
| Supervisor | 不知道 | 进程管理器，systemd 的轻量替代 |

**修正后的理解**：
- Docker = 隔离 + 启动（管理整个应用环境）
- Nginx = Web 服务器（路由 + HTTPS + 静态文件）
- Supervisor / systemd = 进程管理器（保活 + 监控）
- 三者**不冲突**，**可叠加**

---

## 8. 下一步

你需要在 ECS 上跑：

```bash
# 1. 装 Nginx（最小入侵）
sudo apt install -y nginx

# 2. 把 supervisor 配置 dump 一份（确认 MOM 不受影响）
sudo cat /etc/supervisor/supervisord.conf
sudo supervisorctl status

# 3. 看 MOM 的实际启动命令
ls /etc/supervisor/conf.d/
cat /etc/supervisor/conf.d/*.conf 2>&1
```

把输出发我，我帮你确认：
- MOM 的真实启动端口
- 是否需要给 MOM 加 Nginx 反代
- 雅思助手用什么端口最合适

---

## 9. 我已经做好的

| 产物 | 位置 |
|---|---|
| ECS 环境探测脚本 | `scripts/ecs_env_probe.sh` |
| Docker / Supervisor / Nginx 关系说明 | `docs/miniprogram/W10/11-Docker和Supervisor环境部署指南.md`（本文档） |
| 完整部署方案 | `docs/miniprogram/W10/10-完整部署方案（含原理+流程图+自建指南）.md` |
| 部署方案 v2（基于你的环境） | 待写，等你确认端口分配 |

---

## 10. 推送状态

| Commit | 内容 |
|---|---|
| `75bf924` | docs(W10): SSL 免费证书主+www |
| `3b33ee1` | docs(W10): 完整部署方案 |
| 待推送 | `11-Docker和Supervisor环境部署指南.md`（本文档） + `ecs_env_probe.sh` |

请告诉我 ECS 上 supervisor 配置（MOM 启动端口），我把文档按真实情况更新成"v2 部署方案"。
<!-- spacer 4 -->

<!-- spacer v5 -->
