# 安全配置说明

## ⚠️ 重要：轮换已泄露的密钥

`.env` 中包含 `IELTS_BUDDY_JWT_SECRET`，之前已被 `git` 追踪并推送到 GitHub。
虽然已用 `git rm --cached` 从索引移除，但**历史 commit 里仍然能看到密钥**。

**必须轮换**：

```bash
python -m ielts_buddy.web.tools.regen_secrets
# 输出 2 个新密钥，复制到 .env：
#   IELTS_BUDDY_JWT_SECRET=<新值>
#   IELTS_BUDDY_ADMIN_RESET_TOKEN=<新值>
```

> 注意：JWT_SECRET 变更后，**所有现有 token 失效，用户需要重新登录**。这是必要的安全措施。

如果担心 GitHub 历史 commit 残留密钥泄露，可使用 `git filter-repo` 重写历史（**会改写所有 commit hash**）。若项目是公开仓库且密钥敏感，建议：

1. 立即轮换密钥
2. 考虑将仓库设为私有
3. 或 `git filter-repo --invert-paths --path .env --path .venv --path data/web_data.db` 重写历史

## .env 文件正确使用方式

### 模板文件
- **`.env.example`** — 模板文件，含占位值，**可以提交**到 Git
- **`.env`** — 实际配置，含真实密钥，**绝不能提交**

### 推荐流程

```bash
# 1. 首次部署：复制模板
cp .env.example .env

# 2. 编辑 .env，把占位值改成实际值
vim .env

# 3. 关键变量
#   IELTS_BUDDY_JWT_SECRET=至少 32 字符的随机字符串
#   IELTS_BUDDY_ADMIN_RESET_TOKEN=随机字符串（dev 可省）
#   IELTS_BUDDY_WEB_DB_MODE=sqlite 或 online
#   IELTS_BUDDY_WEB_DB_URL=mysql+pymysql://... （online 模式时）

# 4. 提交代码时，.env 会被自动忽略
git add .
git status    # 看不到 .env
git commit
```

### .gitignore 规则摘要

当前 `.gitignore` 已正确忽略：

| 模式 | 作用 |
|------|------|
| `.env` / `.env.*` | 敏感配置（但保留 `.env.example`） |
| `.venv/` | 虚拟环境（4700+ 文件，约 50MB） |
| `*.db` / `*.sqlite*` | 数据库文件 |
| `data/` | 运行时数据目录 |
| `__pycache__/` / `*.pyc` | Python 编译缓存 |
| `.pytest_cache/` / `.coverage` | 测试缓存 |

### .env 中各变量的含义

| 变量 | 必须性 | 说明 |
|------|--------|------|
| `IELTS_BUDDY_WEB_DB_MODE` | 推荐 | `sqlite` / `online` |
| `IELTS_BUDDY_WEB_DB_URL` | online 模式必填 | MySQL 连接 URL |
| `IELTS_BUDDY_JWT_SECRET` | **prod 必须**，dev 推荐 | ≥ 32 字符随机字符串 |
| `IELTS_BUDDY_JWT_ALG` | 默认 HS256 | JWT 签名算法 |
| `IELTS_BUDDY_ACCESS_TTL` | 默认 3600 | access token 有效期（秒） |
| `IELTS_BUDDY_REFRESH_TTL` | 默认 604800 | refresh token 有效期（秒） |
| `IELTS_BUDDY_ENV` | 默认 dev | dev / prod（prod 严格检查） |
| `IELTS_BUDDY_ADMIN_RESET_TOKEN` | **prod 必须** | admin reset-password 接口密钥 |
| `IELTS_BUDDY_COOKIE_SAMESITE` | 默认 lax | lax / strict / none |
| `IELTS_BUDDY_WEB_HOST` | 默认 127.0.0.1 | Web 服务监听地址 |
| `IELTS_BUDDY_WEB_PORT` | 默认 8000 | Web 服务监听端口 |
| `IELTS_BUDDY_CORS_ORIGINS` | 默认本地 | 允许跨域 origin（逗号分隔） |

## 验证方法

```bash
# 1. .env 应该被 gitignore
git check-ignore -v .env
# 期望输出: .gitignore:20:.env    .env

# 2. 仓库里不应再有任何敏感文件
git ls-files | grep -E "^\.env$|^\.venv/|web_data\.db"
# 期望: 空

# 3. 生成强随机密钥
python -m ielts_buddy.web.tools.regen_secrets
```

## 常见错误

| 错误 | 后果 | 修复 |
|------|------|------|
| 提交 `.env` | 密钥泄露到 GitHub | `git rm --cached .env`，**轮换密钥** |
| 提交 `.venv/` | 仓库巨大（50MB+），git 慢 | `git rm -r --cached .venv/`，重建 venv |
| 提交 `*.db` | 用户数据泄露 | `git rm --cached *.db` |
| 多人共享 `JWT_SECRET` | 任何人都能伪造 token | 各环境独立密钥 |
| `IELTS_BUDDY_ENV=prod` 但未设 `JWT_SECRET` | 服务拒绝启动 | 设置 `JWT_SECRET` ≥ 32 字符 |