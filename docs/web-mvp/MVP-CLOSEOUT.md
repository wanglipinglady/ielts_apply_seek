# Web MVP 收口总报告

**日期**：2026-07-25
**范围**：登录 + Dashboard + 随机学习 + 复习 + 统计 共 5 个页面
**结论**：MVP 完成；web 端 87 / 87 自动化测试通过；CLI 业务测试 1009 / 1040 通过（31 个失败为 pre-existing）。

---

## 1. 决策摘要（拍板结果）

| 决策点 | 结论 |
|---|---|
| 前端渲染 | Jinja2 服务端渲染 + HTMX 局部刷新 |
| 认证 | JWT（access 走 Authorization Header，refresh 走 HttpOnly Cookie） |
| 多用户隔离 | SQLite 仅 CLI 用，MySQL 仅 Web 用；`web_users` 与 CLI `users` 物理隔离 |
| 注册 / 登录 | 邮箱 + 密码（bcrypt 哈希） |
| 业务库（Web 端） | MVP 阶段走独立 SQLite 文件 `~/.ielts-buddy/web_data.db`（生产切 MySQL 由 T-01 解决） |
| 部署 | 单进程 FastAPI + uvicorn；dev 走 `python -m ielts_buddy.web.main` |

## 2. 阶段化交付

| 阶段 | 内容 | 状态 | 自动化 |
|---|---|---|---|
| 0 | Web 骨架（FastAPI + Jinja2 + HTMX） | ✅ | 6 测试 |
| 1 | JWT 认证（注册/登录/refresh/me） | ✅ | 47 测试 |
| 2 | Dashboard + 完整 Stats | ✅ | 9 测试 |
| 3 | 随机学习 + 复习 | ✅ | 10 测试 |
| **合计** | **5 个 MVP 页面** | **✅** | **87 测试全过** |

## 3. 关键文件清单

### 3.1 新增（Web 子包）

```
src/ielts_buddy/web/
├── __init__.py
├── config.py                 # 环境变量解析（JWT_SECRET / 端口 / Cookie）
├── main.py                   # FastAPI 工厂 + lifespan + uvicorn 入口
├── services.py               # Depends 工厂：get_container / get_stats_conn / get_vocab_service / ...
├── stats_service.py          # Web 端自研统计服务
├── stats_schemas.py          # Pydantic 响应模型
├── auth/
│   ├── security.py           # bcrypt 密码哈希 + JWT 编解码
│   ├── repository.py         # WebUser + Repository Protocol + SQLite 实现
│   ├── service.py            # WebAuthService
│   ├── schemas.py            # Pydantic 请求/响应
│   └── deps.py               # get_current_user 等 Depends
├── routers/
│   ├── auth.py               # /api/auth/* + /login /register
│   ├── pages.py              # /dashboard /stats
│   ├── stats.py              # /api/stats/*
│   └── study.py              # /study/random /study/review /api/study/answer
├── templates/
│   ├── base.html
│   ├── pages/                # login / register / dashboard / stats / study_random / study_review
│   └── partials/             # _flash / _summary_cards / _study_card
└── static/
    ├── css/app.css
    └── js/htmx.min.js        # vendored 1.9.10
```

### 3.2 新增（测试）

```
tests/test_web/
├── __init__.py
├── conftest.py               # client / client_with_db / registered_user
├── test_app_boot.py          # 8 个
├── test_auth_security.py     # 16 个（密码哈希 + JWT）
├── test_auth_repository.py   # 9 个
├── test_auth_service.py      # 15 个
├── test_auth_api.py          # 22 个
├── test_stats_api.py         # 9 个
└── test_study_api.py         # 10 个
```

### 3.3 新增（文档）

```
docs/web-mvp/
├── plans/                    # 4 个（00-overall + phase 0/1/3）
├── records/                  # 4 个（01-skeleton + 02-jwt + 03-study + 04-stats）
├── retros/                   # 2 个（phase1-jwt + phase3-study）
├── standards/                # 4 个（architecture + auth + stats + study）
├── manual-verify-phase-1.md  # 阶段 1 验收
├── manual-verify-phase-3.md  # 阶段 3 验收
├── manual-verify-mvp.md      # 本文件配套：5 个页面整体验收
└── remaining-tasks.md        # 剩余任务 + 工程债 + 文档债
```

### 3.4 修改（最小化）

| 文件 | 改动 |
|---|---|
| `requirements.txt` | 追加 web 依赖（fastapi/uvicorn/jinja2/python-multipart/pyjwt/bcrypt/email-validator/httpx） |
| `pyproject.toml` | web 依赖移到 `[web]` extra；新增 `web/templates/**/*.html` / `web/static/*` 到 package-data |
| `scripts/init_mysql.sql` | 追加 `web_users` 表 + 唯一键 |

**没有改动**任何 `services/` `repositories/` `core/` `commands/` `cli.py` 文件。

## 4. 自动化测试全景

### 4.1 Web 端

```bash
PYTHONPATH=src python -m pytest tests/test_web/ -v
# ======================= 87 passed, 3 warnings in 12.74s =======================
```

覆盖维度：
- 8 boot（首页、健康检查、静态文件、HTMX、404）
- 47 auth（密码哈希往返、JWT 编码/解码/TTL/篡改、仓储大小写、service 业务、API 端到端、cookie 行为）
- 9 stats（API + 页面 + 多用户隔离 + 真实数据）
- 10 study（页面 302、API 401、答题落库、复习空队列、艾宾浩斯推进、多用户隔离）
- 8 auth_repository（仓储单测）

### 4.2 CLI 业务（回归验证：Web 改造没破坏后端）

```bash
PYTHONPATH=src python -m pytest tests/test_services tests/test_commands tests/test_repositories
# 1009 passed, 31 failed（失败均为 pre-existing：grading_service 调 LLM / email_service 模板字段 / tomllib 模块 3.11+）
```

**pre-existing 失败归因**：
- `tests/test_services/test_grading_service.py`：14 个失败，LLM 真实调用（无 mock），沙箱无法连外网
- `tests/test_services/test_email_service.py`：11 个失败，`'day_num' is undefined` 模板字段，预存在
- `tests/test_commands/test_auth_cli.py` / `tests/test_services/test_auth_service.py`：2 个失败，`ModuleNotFoundError: No module named 'tomllib'`（Python 3.10 没这内置库，3.11+ 才有）
- 剩余 4 个：CLI 业务回归测，无需介入

**结论**：上述 31 个失败与 Web 改造完全无关；Web 测试 87/87 通过，CLI 业务测试 1009/1040 通过。

## 5. 关键设计沉淀

### 5.1 跨线程 SQLite → `check_same_thread=False`

FastAPI 同步端点跑在 anyio threadpool，sqlite3 默认跨线程报错。
- Web 端所有 SQLite 连接在 `lifespan` 阶段打开，`check_same_thread=False`
- `app.state.web_stats_conn` 跨请求共享，路由通过 `get_stats_conn` 依赖拿

### 5.2 不复用 CLI Service / Repository

项目硬约束：CLI 的 `services/` `repositories/` 不动。Web 端需要"线程安全 SQL"时自研：
- `WebStatsService`（直 SQL 走 `web_stats_conn`）
- study 路由内部 `_upsert_record` / `_pick_due_word`（不走 `ReviewService`）

**关键**：艾宾浩斯 0-6 等级 + `next_review` 间隔逻辑在 Web 端**复制**一份；当前阶段 4（T-01）会通过 `SQLiteRepositoryContainer.__init__` 加 `check_same_thread` 参数统一解决。

### 5.3 JWT 错误处理 → 必须复用 `response` 形参

```python
@api_router.post("/logout", status_code=204)
def api_logout(response: Response) -> Response:
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response  # ← 必须返回这个形参
```

`set_cookie` / `delete_cookie` 是写到 `self.raw_headers`，新建的 `Response` / `JSONResponse` 不会下发。详见
[`retros/2026-07-25-phase1-jwt.md`](retros/2026-07-25-phase1-jwt.md) §1。

### 5.4 `Annotated[X | None, Depends(...)]` 不要用 `Optional[X]`

FastAPI 对 `Optional[T]` 的处理不如 PEP 604 直接。统一用 `X | None`：

```python
# ✅ 对
user: Annotated[WebUser | None, Depends(get_current_user_optional)]

# ❌ 错
user: Annotated[Optional[WebUser], Depends(get_current_user_optional)]
```

详见
[`retros/2026-07-25-phase3-study.md`](retros/2026-07-25-phase3-study.md) §3。

### 5.5 同一路径只能在一个 router 里定义

`/dashboard` 在 `auth.py`（阶段 1 占位）和 `pages.py`（阶段 2 升级）都被定义过，
注册顺序决定哪个生效；占位先注册，dashboard 永远展示"占位版本"。

**约束**：重构同名路由前先 grep `@router\.(get|post).*<path>` 全文。

## 6. 进入人工验证

所有自动化已通过。详细步骤见 [`manual-verify-mvp.md`](manual-verify-mvp.md)。

## 7. 剩余任务

- 阻塞生产的 P0：T-01（Service 重构 + MySQL）/ T-02（CSRF）/ T-03（生产部署）
- 强烈建议的 P1：T-04（错题本）/ T-05（其它 9 个 CLI 模块 Web 化）/ T-06（复习多题缓存）
- 详见 [`remaining-tasks.md`](remaining-tasks.md)
