# 阶段 1 人工验证清单

> 全部自动化测试已通过（`pytest tests/test_web/` 68/68）。
> 本清单是必须由人工在浏览器 / 真实环境验证的项目，自动化无法覆盖。

## 1. 启动服务

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
PYTHONPATH=src \
  IELTS_BUDDY_WEB_DB_MODE=sqlite \
  IELTS_BUDDY_WEB_PORT=8000 \
  python -m ielts_buddy.web.main
```

预期输出：
- `Uvicorn running on http://127.0.0.1:8000`
- 顶部出现 `UserWarning: JWT_SECRET 未设置...` 警告（dev 正常）

## 2. 健康检查

```bash
curl -i http://127.0.0.1:8000/healthz
```

预期：
```json
{"status":"ok","app":"ielts-buddy-web","version":"0.1.0","db_mode":"sqlite"}
```
HTTP 200。

## 3. 浏览器端到端

1. 打开 `http://127.0.0.1:8000/`，应看到 "IELTS Buddy Web" + Phase 1 标签
2. 顶部 nav 应显示 "登录 / 注册"（未登录态）
3. 点 "注册"，填写邮箱 + 8 位以上密码，提交
4. 预期自动跳到 `/dashboard`，顶部显示 `已登录：<你的邮箱>`，右边有 "登出" 链接
5. DevTools → Application → Cookies 看到 `ib_refresh`：
   - `HttpOnly` ✓
   - `Path=/api/auth` ✓
   - `SameSite=Lax` ✓
6. 点 "登出"，应跳回首页
7. 再访问 `http://127.0.0.1:8000/dashboard`，应跳 `/login`

## 4. Cookie 安全属性（DevTools）

| 属性 | 期望 | 实际 |
|---|---|---|
| `HttpOnly` | ✓ |  |
| `Secure` | ✗（dev） |  |
| `Path` | `/api/auth` |  |
| `SameSite` | `Lax` |  |

## 5. API curl 验证

```bash
# 注册
curl -i -X POST http://127.0.0.1:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@x.com","password":"password123"}'
# 预期：201 + Set-Cookie ib_refresh=... + access_token 在 body

# 重复注册
curl -i -X POST http://127.0.0.1:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@x.com","password":"password123"}'
# 预期：409 + {"code":"EMAIL_TAKEN",...}

# 弱密码
curl -i -X POST http://127.0.0.1:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"weak@x.com","password":"short"}'
# 预期：422（pydantic 校验）

# 登录
curl -i -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@x.com","password":"password123"}'
# 预期：200 + Set-Cookie + access_token

# 错误密码
curl -i -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@x.com","password":"WRONG"}'
# 预期：401 + {"code":"INVALID_CREDENTIALS"}

# me（带 access token）
ACCESS=...  # 从上面 login 拿
curl -i http://127.0.0.1:8000/api/auth/me \
  -H "Authorization: Bearer $ACCESS"
# 预期：200 + {"id":...,"email":"test@x.com",...}

# 登出
curl -i -X POST http://127.0.0.1:8000/api/auth/logout
# 预期：204 + Set-Cookie ib_refresh=; Max-Age=0
```

## 6. JWT_SECRET 缺失的 prod 行为

```bash
IELTS_BUDDY_ENV=prod python -m ielts_buddy.web.main
```

预期：**启动失败**，错误信息：
```
RuntimeError: 生产环境必须设置 IELTS_BUDDY_JWT_SECRET（≥32 字符）
```

## 7. CLI 与 Web 隔离验证

```bash
# 用 CLI 查用户
PYTHONPATH=src python -m ielts_buddy.cli user list
```

预期：CLI 仍然只看到 CLI `users` 表的用户，**不会**看到刚才 Web 注册的
`test@x.com`。两者物理隔离。

## 8. 验证结束

完成后请在工单 / 群里回复"阶段 1 人工验证通过"，或列出失败项。
