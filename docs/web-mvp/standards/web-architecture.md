# Web 端整体架构规范

> 目的：让后续 Web 化工作有统一约定，避免每次都重新决策。
> 范围：`src/ielts_buddy/web/` 子包及 `tests/test_web/`。

## 1. 设计原则

### 1.1 零侵入 CLI

- **Web 子包不修改** `src/ielts_buddy/services/` 或 `src/ielts_buddy/repositories/` 下任何文件
- 复用方式：
  1. **借壳**（`__new__` 跳过 `__init__`，注入 `_user_id` / `_container`）
  2. **直 SQL**（用 `app.state.web_stats_conn`，绕过 Service 的 conn）
  3. **共享 VocabService 单例**（纯函数式，无状态）
- 例外（待阶段 4）：`SQLiteRepositoryContainer.__init__` 加 `check_same_thread` 参数

### 1.2 CLI 和 Web 共存

- 物理隔离：CLI 用 `~/.ielts-buddy/data.db`，Web 用 `~/.ielts-buddy/web_data.db`
- 业务隔离：CLI 的 `learning_records.user_id` 默认 1；Web 的 `web_users` 表完全独立
- 配置隔离：CLI 读 `~/.ielts-buddy/config.toml`；Web 读进程环境变量
- 代码路径隔离：Web 子包是 optional dependency（`pip install -e ".[web]"`）

### 1.3 多用户隔离

- 所有 `learning_records` SQL 强制带 `user_id=?`
- web_users 表 email 唯一（用 `LOWER(email)` 索引 / MySQL 端 collation）
- 任何从 `Depends(get_current_user)` 拿到的 user.id 透传到所有 SQL

## 2. 目录结构

```
src/ielts_buddy/web/
├── __init__.py
├── config.py              # 进程环境变量读
├── main.py                # FastAPI app 工厂 + lifespan + uvicorn 入口
├── services.py            # 借壳 Service 的工厂（get_stats_service / get_review_service）
├── stats_service.py       # Web 端自研版（直 SQL，跨线程 OK）
├── stats_schemas.py       # Pydantic schemas（API 响应）
├── auth/
│   ├── repository.py      # WebUser + WebUserRepository Protocol + SQLite/MySQL 实现
│   ├── security.py        # bcrypt + JWT 签发/解析
│   ├── service.py         # WebAuthService 业务逻辑
│   ├── schemas.py         # Pydantic schemas
│   └── deps.py            # FastAPI Depends（get_current_user 等）
├── routers/
│   ├── auth.py            # /login /register /api/auth/*（注册、登录、刷新、登出、me）
│   ├── pages.py           # /dashboard /stats（页面路由 + 摘要/统计聚合）
│   ├── stats.py           # /api/stats/*（API）
│   └── study.py           # /study/random /study/review /api/study/answer
├── templates/
│   ├── base.html
│   ├── pages/             # 完整页面（extends base）
│   └── partials/          # HTMX 局部刷新片段（不 extends）
└── static/
    ├── css/app.css
    └── js/htmx.min.js     # vendored 1.9.10
```

## 3. 依赖注入约定

### 3.1 用户态
| 场景 | 依赖 | 行为 |
| --- | --- | --- |
| 公开页面（首页） | `get_current_user_optional` | 缺 / 错 token → 返回 None |
| 需登录页面（dashboard / study） | `get_current_user_optional` + 路由内 None → 302 | 缺 / 错 token → 跳 /login |
| API 端点（POST/PUT/DELETE） | `get_current_user` | 缺 / 错 token → 401 |
| /api/auth/refresh 特殊 | `get_refresh_token_from_cookie` | 缺 cookie → 401 |

### 3.2 类型注解
- 全部用 `Annotated[X | None, Depends(...)]`（PEP 604），**不要** `Optional[X]`
- 业务路由用 `Depends(get_current_user_optional)`，路由内显式判 None
- 内部依赖（service / conn）不暴露 Optional

### 3.3 数据库连接
- **唯一允许**的 conn：`get_stats_conn`（`app.state.web_stats_conn`，`check_same_thread=False`）
- 任何 `conn: Annotated[sqlite3.Connection, Depends(get_stats_conn)]` 都跨线程安全
- **禁止**：`sqlite3.connect(...)` 在路由函数内新建（会被 threadpool 干翻）

## 4. 数据库约定

### 4.1 双数据库并行
- `web_data.db`（SQLite，默认）：dev / 本地
- MySQL（生产）：用 `IELTS_BUDDY_WEB_DB_MODE=online` 切换

### 4.2 路径
- 默认：`~/.ielts-buddy/web_data.db`
- 覆盖：`IELTS_BUDDY_WEB_SQLITE_PATH=/path/to/file.db`
- 测试：`tmp_path / "web_data.db"`（conftest 注入）

### 4.3 Schema 幂等
- 业务表（learning_records / personal_vocab / ...）用 `CREATE TABLE IF NOT EXISTS`
- 字段补齐走 `_migrate_legacy_schema`（参考 `sqlite_repo.py:255`）
- 不在 Web 端用 `ALTER TABLE`（避免和 CLI 端 migration 冲突）

## 5. 模板约定

### 5.1 base.html
- 顶部 `<head>` 引 CSS + HTMX
- `<nav>` 渲染 user 态：未登录显示登录/注册，已登录显示 dashboard / study / stats + 登出
- `<main class="container">` 包 block content

### 5.2 partials
- **不** extends base
- 纯 HTML 片段，HTMX 局部替换用
- 默认值用 `{% if X %}{{ X }}{% else %}fallback{% endif %}` 兜底

### 5.3 文案
- 全部中文硬编码
- i18n 阶段（T-07）后再抽 babel

## 6. 路由命名

| 类别 | 模式 | 例子 |
| --- | --- | --- |
| 公开页面 | `GET /{path}` | `/`, `/login`, `/register` |
| 受保护页面 | `GET /{feature}` | `/dashboard`, `/stats`, `/study/random`, `/study/review` |
| 业务 API | `GET/POST /api/{resource}/{action}` | `/api/auth/register`, `/api/stats/summary`, `/api/study/answer` |
| 健康检查 | `GET /healthz` | `/healthz` |
| 静态 | `GET /static/{path}` | `/static/css/app.css` |

## 7. 测试约定

### 7.1 三个核心 fixture（conftest.py）
```python
client             # 内存 SQLite user repo，不持久化
client_with_db     # tmp_path 上 web_data.db，stats / study 用
registered_user    # 1 个注册好的用户（含 access_token）
```

### 7.2 覆盖清单
- 401（API 未登录）/ 302（页面未登录）
- 200 + 关键字段
- 多用户隔离
- 异常路径（404 / 400 / 弱密码）
- 持久化（写 DB / 读 DB）

### 7.3 性能基线
- 单测 < 5s
- 全 web 套件 < 30s

## 8. 安全约定

### 8.1 密码
- bcrypt 哈希（`bcrypt.hashpw`），4.x+ 限制 72 字节，截断
- 至少 8 位

### 8.2 JWT
- HS256，密钥 ≥ 32 字节
- Access token 1 小时，Authorization: Bearer 头传递
- Refresh token 7 天，HttpOnly + SameSite=Lax cookie
- aud 区分 access / refresh，避免 token 互用

### 8.3 Cookie
- 名称 `ib_refresh`（默认），可通过 `IELTS_BUDDY_REFRESH_COOKIE` 覆盖
- dev: `Secure=False`
- prod: `Secure=True`（HTTPS only）

### 8.4 待办
- [ ] CSRF（生产前必做，T-02）
- [ ] Rate limit（注册 / 登录防爆破）
- [ ] 密码强度仪表盘（弱密码告警）

## 9. 部署约定

### 9.1 进程模型
- dev: `python -m ielts_buddy.web.main --reload`
- prod: `uvicorn ielts_buddy.web.main:app --workers 4 --proxy-headers`

### 9.2 环境变量
| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `IELTS_BUDDY_JWT_SECRET` | prod 必填 | dev 随机 | ≥ 32 字符 |
| `IELTS_BUDDY_WEB_DB_MODE` | 否 | `online` | `sqlite` / `memory` 走 web_data.db |
| `IELTS_BUDDY_WEB_DB_URL` | prod 必填 | 空 | MySQL DSN |
| `IELTS_BUDDY_WEB_SQLITE_PATH` | 否 | `~/.ielts-buddy/web_data.db` | dev 路径 |
| `IELTS_BUDDY_WEB_HOST` | 否 | `127.0.0.1` | |
| `IELTS_BUDDY_WEB_PORT` | 否 | `8000` | |
| `IELTS_BUDDY_REFRESH_TTL` | 否 | `604800` | 7 天 |
| `IELTS_BUDDY_ACCESS_TTL` | 否 | `3600` | 1 小时 |

### 9.3 systemd unit 模板
```ini
[Unit]
Description=IELTS Buddy Web
After=network.target mysql.service

[Service]
User=ielts
WorkingDirectory=/srv/ielts-buddy
EnvironmentFile=/etc/ielts-buddy/web.env
ExecStart=/srv/ielts-buddy/venv/bin/uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

## 10. 阶段化路径

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| 0 | Web 骨架 | ✅ |
| 1 | JWT 认证 | ✅ |
| 2 | Dashboard + 统计 | ✅ |
| 3 | 随机学习 + 复习 | ✅（MVP 完成） |
| 4 | Service 重构走 Repository + MySQL | 待 T-01 |
| 5 | 错题本 / 收藏夹 | 待 T-04 |
| 6 | 9 个 CLI 模块 Web 化 | 待 T-05 |
| 7 | CSRF / Rate limit / i18n | 待 T-02/T-07 |
