# 阶段 1：Web 端 JWT 认证

## 目标
为 Web 端建立独立的用户体系与 JWT 认证：邮箱 + 密码注册登录，access_token 走
`Authorization: Bearer ...`，refresh_token 走 `HttpOnly` Cookie。多用户隔离
（`web_users` 与 CLI 的 `users` 物理隔离）。

## 改动文件

### 新增
- `src/ielts_buddy/web/auth/__init__.py` — 子包
- `src/ielts_buddy/web/auth/security.py` — bcrypt 密码哈希 + JWT 签发/校验
- `src/ielts_buddy/web/auth/service.py` — `WebAuthService`（注册/登录/刷新/登出/me）
- `src/ielts_buddy/web/auth/deps.py` — FastAPI 依赖（get_current_user 等）
- `src/ielts_buddy/web/auth/schemas.py` — Pydantic 请求/响应模型
- `src/ielts_buddy/web/routers/auth.py` — `/api/auth/*` 路由
- `src/ielts_buddy/web/routers/__init__.py` — 路由包
- `src/ielts_buddy/web/templates/pages/login.html`
- `src/ielts_buddy/web/templates/pages/register.html`
- `src/ielts_buddy/web/templates/pages/dashboard.html`（阶段 2 会补全）
- `src/ielts_buddy/web/templates/partials/_flash.html`（HTMX 错误/成功片段）
- `src/ielts_buddy/web/static/css/auth.css`（登录/注册专用样式）
- `tests/test_web/test_auth_service.py`
- `tests/test_web/test_auth_api.py`
- `tests/test_web/test_auth_security.py`
- `tests/test_web/test_auth_deps.py`
- `docs/web-mvp/records/2026-07-25-02-jwt.md`
- `docs/web-mvp/retros/2026-07-25-jwt-bcrypt-version-pin.md`（如有问题）
- `docs/web-mvp/standards/web-auth.md`

### 修改
- `scripts/init_mysql.sql` — 新增 `web_users` 表
- `src/ielts_buddy/web/main.py` — 挂载 auth 路由 + 全局未授权处理
- `src/ielts_buddy/web/templates/base.html` — 顶部 nav 显示当前用户 / 登录入口
- `tests/test_web/conftest.py` — 加 `db_session` / `client_with_user` fixture
- `tests/test_web/test_app_boot.py` — Phase 0 跑测时修了 `text/javascript` mime 判断

### 关键决策记录
- `web_users` **不复用** `core/repository.py` 里的 `UserRepository`：后者是 CLI
  模式专用（username 简单表，无 password_hash），改它会污染 CLI 路径。
  Web 端单独建 `WebUserRepository`（同 Protocol 风格），`web_user_repo` / `web_user`.
- 测试用 SQLite 内存库（schema 自洽），生产用 MySQL 真实表（`init_mysql.sql`）。
  两套实现都满足 `WebUserRepository` Protocol。

## 数据模型

```sql
CREATE TABLE IF NOT EXISTS web_users (
    id              BIGINT          NOT NULL AUTO_INCREMENT,
    email           VARCHAR(255)    NOT NULL,
    password_hash   VARCHAR(255)    NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at   DATETIME        NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_web_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

物理上与 CLI 的 `users` 表完全解耦；`web_users.id` 与 `users.id` 互不干扰。

## 安全设计

1. **密码哈希**：`passlib[bcrypt]`，明文密码不出内存（不写日志、不返回给前端）。
2. **access_token**：HS256，TTL 1 小时，走 `Authorization: Bearer <token>`。
3. **refresh_token**：HS256，TTL 7 天，存 HttpOnly Cookie（`Secure` 仅生产），
   `SameSite=Lax`。
4. **邮箱格式**：用 `pydantic.EmailStr` 校验。
5. **密码强度**：最少 8 字符（阶段 1 不做复杂规则，避免拦掉用户；后续迭代再加）。
6. **不存原密码**：日志中只记 email，不记 password。
7. **CSRF**：HTMX fetch 默认带 cookie，但本阶段没有写操作，CSRF 风险低。
   阶段 2 引入写操作时加 HTMX 同步 token 头。

## 路由

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET  | `/login` | 公开 | 登录页 |
| POST | `/api/auth/login` | 公开 | 邮箱+密码 → access_token + Set-Cookie refresh |
| GET  | `/register` | 公开 | 注册页 |
| POST | `/api/auth/register` | 公开 | 创建 web_user |
| POST | `/api/auth/refresh` | 需 refresh cookie | 重新签发 access_token |
| POST | `/api/auth/logout` | 需登录 | 清 cookie + 黑名单（阶段 1 简化为只清 cookie） |
| GET  | `/api/auth/me` | 需 access | 返回当前 user 信息 |

## 依赖注入

- `get_current_user` — 解析 `Authorization` → 解码 JWT → 查 web_users → 注入 `WebUser` 模型
- `get_current_user_optional` — 解析失败返回 None（用于首页这种公开页判登录态）
- `DBAuthSession` — 单请求内复用一个 web 端的 RepositoryContainer（MySQL）

## 自动化验收

`tests/test_web/test_auth_security.py`：
- 密码哈希 ≠ 明文
- 同密码两次哈希结果不同（bcrypt salt 随机）
- 密码校验：hash(plain) == stored
- JWT encode/decode 正确，TTL/issuer 字段正确
- 篡改 token 抛异常

`tests/test_web/test_auth_service.py`：
- 注册：邮箱不重复 → user_id 拿到
- 重复注册 → 抛 `EmailAlreadyExistsError`
- 登录：成功 → 返回 user + token
- 错误密码 → 抛 `InvalidCredentialsError`
- 不存在用户 → 同上（不区分，规避邮箱枚举）
- me：用合法 access_token 拿到当前用户
- me：无/过期 token → 401
- refresh：合法 cookie → 新 access_token
- refresh：过期/缺失 → 401

`tests/test_web/test_auth_api.py`：
- 端到端：register → 200；login → 200 + Set-Cookie；me → 200；
  拿 access_token 访问其他端点 → 200。
- 错误密码：401 + JSON 错误。
- 重复注册：409 + 错误信息。
- 过期 token：401。

`tests/test_web/test_auth_deps.py`：
- 缺 Authorization → 401
- 错误签名 → 401
- access 过期但 refresh 合法 → 调用 /api/auth/refresh 后可用

## 风险点

- **bcrypt 5.x 在 Windows 上有兼容问题** — 锁定 `passlib[bcrypt]<1.8` 或用
  `bcrypt<4` 兜底。本机 macOS 不受影响，但要在 `requirements.txt` 锁版本。
- **MySQL 依赖** — 测试用内存 SQLite（`web_users` 走 SQLite 实现）；生产用
  MySQL 实现。Repository 抽象要分两个类。
- **session 中间件** — 不引入 `SessionMiddleware`；状态完全由 JWT 携带。
- **token 黑名单** — 阶段 1 不实现（logout 仅清 cookie + access TTL 短），
  阶段 4+ 引入 Redis 黑名单。

## 收尾标准
- [ ] `pytest tests/test_web -v` 全绿
- [ ] 浏览器手测：注册 → 自动登录 → 看到 Dashboard 占位 → 登出
- [ ] `docs/web-mvp/standards/web-auth.md` 写好
- [ ] 文档：变更记录 + 问题复盘（如有）
