# Web 端密码管理说明

## 1. 密码加密规则

| 项目 | 规则 |
|------|------|
| **算法** | bcrypt（直接用 `bcrypt` 库，不走 passlib） |
| **格式** | `$2b$12$<22 字符 salt><31 字符 hash>`，共 60 字符 |
| **cost** | 默认 12（bcrypt 默认） |
| **盐** | 每次 `bcrypt.gensalt()` 自动生成，**每个账号不同** |
| **密码长度** | **最多 72 字节**（bcrypt 4.x+ 硬限制，超长截断） |

**代码位置**：`src/ielts_buddy/web/auth/security.py`

```python
def hash_password(plain_password: str) -> str:
    raw = plain_password.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, password_hash: str) -> bool:
    raw = plain_password.encode("utf-8")[:72]
    return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
```

## 2. ⚠️ 重要事实：bcrypt 是单向哈希

**无法"反解密"看到原密码。** 任何声称能"显示原密码"的工具都是骗人的。

只有一种方式能拿到明文密码：

1. **用户在某次注册 / 改密时**记下的明文
2. **重置密码**：用新密码覆盖旧 hash，**新明文密码会一次性返回**

## 3. 三种密码处理能力（新增）

| 能力 | 接口 | 谁可用 | 用途 |
|------|------|--------|------|
| **① 用户自助改密** | `POST /api/auth/change-password` | 已登录用户 | 改自己密码（需输旧密码） |
| **② Admin 重置密码** | `POST /api/auth/admin/reset-password` | 服务端内部接口 | 输入 email → 返回**一次性新明文密码** |
| **③ CLI 重置脚本** | `python -m ielts_buddy.web.tools.reset_password` | 服务器管理员 | 不需要 Web 服务在跑，直接改 db |

### 3.1 接口 ①：用户自助改密

```bash
curl -X POST http://localhost:8000/api/auth/change-password \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"old_password": "OldPass123!", "new_password": "NewPass456!"}'
```

返回：
- 200 `{"ok": true}` — 成功
- 401 `INVALID_CREDENTIALS` — 旧密码错 / 未登录
- 400 `WEAK_PASSWORD` — 新密码 < 8 位

### 3.2 接口 ②：Admin 重置密码

**配置（生产环境必须）**：
```bash
export IELTS_BUDDY_ADMIN_RESET_TOKEN="一段长随机字符串"
```

**调用**：
```bash
curl -X POST http://localhost:8000/api/auth/admin/reset-password \
  -H "X-Admin-Token: <IELTS_BUDDY_ADMIN_RESET_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@x.com"}'
```

返回：
```json
{
  "email": "user@x.com",
  "new_password": "aB3xY7zQ9m",  ← 一次性明文，**立即保存**
  "user_id": 4
}
```

错误码：
- 401 — 缺 / 错 `X-Admin-Token`
- 401 `INVALID_CREDENTIALS` — email 不存在（防枚举）

### 3.3 工具 ③：CLI 重置脚本

**不需要** Web 服务在跑，直接连数据库：

```bash
# 自动生成 10 位随机密码
python -m ielts_buddy.web.tools.reset_password --email user@x.com --yes

# 指定新密码
python -m ielts_buddy.web.tools.reset_password \
    --email user@x.com \
    --new-password "MyNewPwd123!" \
    --yes
```

输出：
```
┌─ 密码已重置 ────────────────────────────────────┐
│  email:        user@x.com
│  user_id:      4
│  new_password: aB3xY7zQ9m    ← 请立即保存
│  hash 在 db:  $2b$12$...
└──────────────────────────────────────────────────┘
```

环境变量：
- `IELTS_BUDDY_WEB_DB_MODE` — `sqlite`（默认）或 `online`（MySQL）
- `IELTS_BUDDY_WEB_SQLITE_PATH` — SQLite 文件路径（默认 `~/.ielts-buddy/web_data.db`）
- `IELTS_BUDDY_WEB_DB_URL` — MySQL 连接 URL

## 4. 安全设计要点

| 设计 | 原因 |
|------|------|
| bcrypt 单向哈希 | 业界标准，**抗暴力破解**（cost=12 → 单次哈希 ~250ms） |
| 每个用户独立 salt | 同一密码的两个用户 hash 也不同，**抗彩虹表** |
| Admin 接口需 `X-Admin-Token` | 防滥用，token 必须存服务端环境变量 |
| Email 不存在也返回 `INVALID_CREDENTIALS` | **防邮箱枚举攻击**（攻击者不能借此枚举账号） |
| 一次性返回明文密码 | 客户端必须立即保存；服务端只存 bcrypt hash，**不留明文** |
| 72 字节截断 | 与历史习惯一致，业务层不强制长度限制 |

## 5. 找回密码的推荐流程（用户侧）

1. 用户在登录页点"忘记密码"
2. 客户端调 `/api/auth/admin/reset-password`（需要后端配置 token）
3. 后端生成新密码，返回给客户端
4. 客户端把新密码展示给用户，让用户立即登录后改密

> 注：项目**不内置**邮件发送，admin 重置依赖"管理员 → 用户"线下沟通。

## 6. 验证

```bash
.venv/bin/python /Users/wangliping/.trae-cn/work/.../password_reset_test.py
```

应输出 `14/14 PASS`。覆盖：
- HTTP admin reset 带 / 缺 / 错 token
- HTTP admin reset 不存在 email（防枚举）
- HTTP change-password 已登录 / 未登录 / 旧密码错
- CLI reset --new-password / 自动生成 / 不存在 email
- 重置后用新密码登录成功

## 7. 文件清单

| 文件 | 修改 |
|------|------|
| `src/ielts_buddy/web/auth/security.py` | （无修改）现有 `hash_password` / `verify_password` 复用 |
| `src/ielts_buddy/web/auth/repository.py` | Protocol + SQLite + MySQL 实现新增 `set_password()` |
| `src/ielts_buddy/web/auth/service.py` | 新增 `change_password()` / `reset_password()` / `_generate_random_password()` |
| `src/ielts_buddy/web/auth/schemas.py` | 新增 `ChangePasswordRequest/Response`、`ResetPasswordRequest/Response` |
| `src/ielts_buddy/web/routers/auth.py` | 新增 `/api/auth/change-password`、`/api/auth/admin/reset-password` |
| `src/ielts_buddy/web/config.py` | 新增 `ADMIN_RESET_TOKEN` 配置（dev 占位、prod 强校验） |
| `src/ielts_buddy/web/tools/reset_password.py` | 新增 CLI 重置脚本 |
| `src/ielts_buddy/repositories/sqlite_repo.py` | 启用 `journal_mode=WAL`（修"`attempt to write a readonly database`"误报） |