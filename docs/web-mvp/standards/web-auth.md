# Web 端认证规范

> 阶段 1 落地后形成的约定。后续 phase 严格遵守。

## 1. 用户表隔离

- Web 端走独立 `web_users` 表，与 CLI 的 `users` 表物理隔离
- `web_users.id` 与 `users.id` 互不干扰，命名空间独立
- CLI 用户的 `user_id` 永远是 1（单机）或 MySQL `users.id`（联网），
  不会与 Web 端混淆

## 2. 密码

- 算法：`bcrypt`（直接用 `bcrypt` 库，不用 `passlib` —— passlib 已停维护，
  1.7.4 与 bcrypt 4.x+ 不兼容）
- 长度限制：bcrypt 4.x 严格 72 字节，业务层在调用 `hash_password` 前
  做了 `[:72]` 截断；业务层不限制长度，让用户自由输入
- 业务规则：注册时强制 ≥ 8 字符（`schemas.RegisterRequest` 校验）
- 存储：明文不落库、不写日志、不返回给前端

## 3. Token 设计

- `access_token`：HS256，TTL 1 小时，`Authorization: Bearer <token>`
- `refresh_token`：HS256，TTL 7 天，存 HttpOnly Cookie
  - `path=/api/auth`，最小化暴露面
  - `secure=True` 仅生产（`COOKIE_SECURE` 由 `IELTS_BUDDY_ENV=prod` 触发）
  - `samesite=lax`
- audience 区分：access 用 `ielts-buddy:access`，refresh 用 `ielts-buddy:refresh`，
  互相不可替代
- 不引入 token 黑名单（阶段 1）：登出仅清 cookie + access TTL 短

## 4. 错误码

`AuthError.code` 字符串枚举：

| code | HTTP | 触发条件 |
|---|---|---|
| `INVALID_EMAIL` | 400 | 邮箱为空 / 格式不合法 |
| `WEAK_PASSWORD` | 400 | 注册时密码 < 8 |
| `EMAIL_TAKEN` | 409 | 注册时邮箱已存在 |
| `INVALID_CREDENTIALS` | 401 | 登录时邮箱/密码错误（合并提示，规避邮箱枚举） |
| `USER_NOT_FOUND` | 401 | token sub 对应用户不存在 |
| `TOKEN_INVALID` | 401 | 签名错、audience 错、格式错 |
| `TOKEN_EXPIRED` | 401 | token 过期 |

不暴露：是否邮箱存在、密码强度具体要求、token 内部字段。

## 5. 端点约定

| 路径 | 方法 | 鉴权 | 用途 |
|---|---|---|---|
| `/api/auth/register` | POST | 公开 | 创建用户 + 自动登录 |
| `/api/auth/login` | POST | 公开 | 登录，下发两把 token |
| `/api/auth/refresh` | POST | refresh cookie | 换新 access + refresh |
| `/api/auth/logout` | POST | 任意 | 清 refresh cookie |
| `/api/auth/me` | GET | access | 当前用户信息 |
| `/login` | GET | 公开 | 登录页（HTML） |
| `/register` | GET | 公开 | 注册页（HTML） |
| `/dashboard` | GET | access | 阶段 1 鉴权验证页 |

## 6. 仓储隔离

- Web 端仓储（`ielts_buddy.web.auth.repository.WebUserRepository`）独立
  Protocol，**不复用** `core/repository.py` 的 `UserRepository`
- SQLite / MySQL 双实现；阶段 1 仅实现 SQLite，MySQL 实现延后到阶段 4
- 测试用 `create_sqlite_web_user_repository(":memory:")`，
  共享给 fixture 复用

## 7. 注入模式

- 单例仓储放在 `app.state.web_user_repo`，由 `lifespan` 创建/释放
- `WebAuthService` 每次请求构造（无状态壳 + 注入仓储）
- FastAPI 依赖 `Depends(get_web_auth_service)` 暴露 service，
  `Depends(get_current_user)` 暴露 `WebUser` 领域对象

## 8. 前端约束

- access_token 存 `localStorage`（阶段 1 简化为这样；阶段 4+ 切到 cookie-only）
- HTMX 表单提交，统一 `hx-post + hx-on::after-request` 处理响应
- 401 响应：access 过期 → 跳 `/login`；refresh 失败 → 跳 `/login` 并清 cookie

## 9. 不做的事（明确边界）

- 不引入 `SessionMiddleware`（JWT 自带 session 语义）
- 不实现"记住我"（refresh token 已经够长）
- 不在阶段 1 做密码强度复杂度校验（≤ 8 字符即可）
- 不在阶段 1 做邮箱验证链接（直接 trust）
- 不做速率限制（rate limiting 放阶段 4+ 安全加固）
