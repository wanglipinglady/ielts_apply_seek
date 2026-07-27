# Web MVP 开发总计划

> 范围锁定：登录 + Dashboard + 随机学习 + 复习 + 统计 五个页面
> 目标：在不改动 17 个 Service 的前提下，新增一个 Web 入口服务，让用户通过浏览器完成与 CLI 等价的核心学习闭环

---

## 1. 决策清单（2026-07-25 拍板）

| 决策点 | 结论 | 备注 |
|---|---|---|
| 前端渲染 | Jinja2 服务端渲染 + HTMX 局部刷新 | 不引入 Vue/React |
| 认证方式 | JWT（access_token 走 Authorization Header，refresh_token 走 HttpOnly Cookie） | 不使用 session 中间件 |
| 多用户隔离 | SQLite 仅 CLI 用，MySQL 仅 Web 用；Web 走独立 `web_users` 表 | 不共享 user_id 命名空间 |
| 注册/登录 | 邮箱 + 密码；密码 bcrypt 哈希；Web 用户独立于 CLI 用户 | web_users.id 与 CLI users.id 完全解耦 |
| MVP 页面 | 5 个：login/register、Dashboard、random study、review、stats | 后续 phase 扩展 |
| 部署 | 单进程 FastAPI + uvicorn；本地 dev / 生产 systemd 二选一 | 复用现有 PYTHONPATH=src |

## 2. 现有架构盘点（已落定的事实）

### 2.1 必须复用的接口（不改一行）

- `ielts_buddy.core.models`：所有 Pydantic 模型，Web 路由直接用 `model.model_dump()` / `Model(**payload)` 序列化
- `ielts_buddy.services.*`：17 个 Service，接受 `user_id` 注入；Web 层拿到 JWT → 解出 web_user_id → 调 Service 时传入
- `ielts_buddy.repositories.create_repositories(mode="online")`：在 Web 进程里强制走 online 模式（MySQL）
- `init_mysql.sql`：扩展新增 `web_users` 表，**不动**原有 9 张业务表

### 2.2 必须新增的模块

| 路径 | 职责 |
|---|---|
| `src/ielts_buddy/web/__init__.py` | Web 子包入口 |
| `src/ielts_buddy/web/main.py` | FastAPI app 工厂 + uvicorn 入口 |
| `src/ielts_buddy/web/config.py` | JWT_SECRET、TOKEN_TTL、CORS、COOKIE 配置 |
| `src/ielts_buddy/web/security.py` | bcrypt 哈希、JWT 编解码、依赖注入：get_current_user |
| `src/ielts_buddy/web/db.py` | 在线模式 RepositoryContainer 单例 + 关闭钩子 |
| `src/ielts_buddy/web/schemas.py` | 注册/登录/响应 Pydantic 模型 |
| `src/ielts_buddy/web/routers/__init__.py` | 路由聚合 |
| `src/ielts_buddy/web/routers/auth.py` | /api/auth/register, /api/auth/login, /api/auth/logout, /api/auth/me |
| `src/ielts_buddy/web/routers/pages.py` | /, /login, /register, /dashboard, /study/random, /study/review, /stats |
| `src/ielts_buddy/web/routers/api_study.py` | HTMX 片段 API：/api/study/random, /api/study/review, /api/study/stats |
| `src/ielts_buddy/web/deps.py` | 依赖项：get_container、get_user_id、get_word_service、get_review_service、get_stats_service |
| `src/ielts_buddy/web/templates/base.html` | 公共骨架（顶部 Tab + 侧边栏 + 主体） |
| `src/ielts_buddy/web/templates/pages/*.html` | 5 个整页模板 |
| `src/ielts_buddy/web/templates/partials/*.html` | HTMX 局部片段 |
| `src/ielts_buddy/web/static/css/app.css` | 自定义样式（不引入 Tailwind） |
| `src/ielts_buddy/web/static/js/htmx.min.js` | HTMX 1.9.x（vendored，不走 CDN） |
| `src/ielts_buddy/repositories/web_user_repo.py` | `WebUserRepository` Protocol + SQLite/MySQL 双实现 |
| `scripts/init_web_users.sql` | web_users 表 DDL（id 字段与 CLI users 表完全解耦） |
| `tests/test_web/` | 完整自动化测试 |

### 2.3 必须修改的现有文件

| 文件 | 修改内容 |
|---|---|
| `requirements.txt` | 新增 fastapi/uvicorn/jinja2/python-multipart/passlib[bcrypt]/pyjwt/email-validator/itsdangerous |
| `pyproject.toml` | 同上（保持依赖单一来源） |
| `src/ielts_buddy/repositories/__init__.py` | 导出 WebUserRepository、create_repositories 增加 web=True 选项 |
| `src/ielts_buddy/repositories/mysql_repo.py` | 增加 WebUserRepository 的 MySQL 实现 |
| `src/ielts_buddy/repositories/sqlite_repo.py` | 增加 WebUserRepository 的 SQLite 实现（Web 走 MySQL；SQLite 仅作 dev fallback） |
| `scripts/init_mysql.sql` | 末尾追加 web_users 表 + 索引 |
| `src/ielts_buddy/web/main.py` | 提供 `--mode web` CLI 子命令的可选入口；不影响现有 `ib` 命令 |
| `README.md` | 追加 Web 启动章节 |

> 上述修改**不改变**任何已有 Service / 已有 9 张业务表 / 现有 CLI 行为。

## 3. 阶段拆分与验收

### 阶段 0：项目骨架（先跑起来）
- 创建 `web/` 包、`templates/`、`static/`，FastAPI hello world 跑通
- HTMX、静态文件挂载、模板继承验证
- `pytest tests/test_web/test_app_boot.py` 通过

**自动化验收**
- `curl http://127.0.0.1:8000/` 返回 200，HTML 包含 `ielts-buddy` 字样
- `pytest tests/test_web/test_app_boot.py` 全部 PASS
- `python -m ielts_buddy.web.main` 启动后无 traceback

**人工验收**
- 浏览器打开 `http://127.0.0.1:8000/` 看到首页 hello 文案

### 阶段 1：JWT 认证（注册 / 登录 / 受保护依赖）
- web_users 表 schema 写入 `init_web_users.sql`，幂等
- `WebUserRepository`（Protocol） + MySQL/SQLite 双实现
- `security.py`：bcrypt 哈希、access_token/refresh_token 编解码
- `routers/auth.py`：4 个 API + 模板化的登录/注册页
- `deps.py`：`get_current_user` 依赖项，从 Authorization Header 解析

**自动化验收**
- 注册：POST /api/auth/register 成功 → 201，返回 user 信息
- 重复邮箱：409 + 明确错误信息
- 错误密码：bcrypt 校验不通过 → 401
- 登录：返回 access_token + refresh_token（refresh 走 HttpOnly Cookie）
- 受保护路由：缺 token → 401；过期 token → 401；正常 token → 注入 user
- 退出：清 cookie + 撤销 refresh
- `pytest tests/test_web/test_auth.py` 全部 PASS

**人工验收**
- 浏览器走完：访问 /login → 输错密码 → 看到错误提示 → 注册新账号 → 自动登录 → /dashboard 看到用户名
- DevTools Network 看 set-cookie 的 HttpOnly/Path/SameSite
- 直接 curl POST /api/auth/register 验证 JSON 接口

### 阶段 2：Dashboard + Stats（统计聚合页）
- `pages/dashboard.html`：欢迎语 + 5 张统计卡片 + 跳转入口
- `pages/stats.html`：完整统计视图（今日、累计、记忆等级分布、Band 进度、历史趋势）
- `api_study.py`：`GET /api/study/stats` 返回聚合 JSON
- HTMX：dashboard 卡片 hx-get 拉数据，失败时显示「暂无数据」

**自动化验收**
- 数据库无学习记录时返回 0/空数组，前端不崩
- 数据库有记录时数字与 CLI `ib stats show` 一致
- 不同 web_user 互不可见（A 注册几条，B 登录看不到）
- `pytest tests/test_web/test_stats_api.py` 全部 PASS

**人工验收**
- 浏览器 /stats：4 张大卡片 + 等级分布柱状图 + 7 天趋势表
- 注册新用户 → /stats 全是 0
- 走 CLI `ib auth login` + `ib vocab random -n 5` 制造数据 → Web /stats 数字随之变化

### 阶段 3：随机学习 + 复习（核心学习闭环）
- `pages/study/random.html`：5 个单词卡片 + 「我已学会」/「不认识」两个按钮
- `pages/study/review.html`：到期单词列表 + 标记掌握/没掌握
- `api_study.py`：
  - `GET /api/study/random?n=5` → 返回单词列表
  - `POST /api/study/record` body={word, correct} → 写 learning_records
  - `GET /api/study/review?limit=20` → 到期单词
- 艾宾浩斯逻辑由现有 `ReviewService.record_learn` 承担；Web 层只做参数适配

**自动化验收**
- 随机抽词不重复、不超过词库总数
- 标记 correct=true → memory_level 上升 → next_review 推后（与现有 review_service 行为一致）
- 标记 correct=false → memory_level 下降
- 复习列表只显示 next_review <= today 的
- `pytest tests/test_web/test_study_api.py` 全部 PASS

**人工验收**
- /study/random：连续点 5 次「我已学会」→ CLI `ib stats show` 中今日 new_words 累加
- /study/review：把今天的到期词全部标记 → 列表立即空

## 4. 自动化测试矩阵

| 测试文件 | 覆盖点 | 命令 |
|---|---|---|
| `tests/test_web/conftest.py` | FastAPI TestClient + 临时 MySQL schema + fixtures | — |
| `tests/test_web/test_app_boot.py` | app 启动、健康检查、静态文件、CORS | `pytest tests/test_web/test_app_boot.py` |
| `tests/test_web/test_auth.py` | 注册/登录/登出/受保护依赖/密码哈希/重复邮箱/过期 token | `pytest tests/test_web/test_auth.py` |
| `tests/test_web/test_stats_api.py` | 空数据/有数据/用户隔离/字段完整性 | `pytest tests/test_web/test_stats_api.py` |
| `tests/test_web/test_study_api.py` | 随机抽词不重复/艾宾浩斯逻辑/复习列表 | `pytest tests/test_web/test_study_api.py` |
| `tests/test_web/test_pages.py` | 5 个页面 GET 200/登录跳转/未登录保护 | `pytest tests/test_web/test_pages.py` |

> 所有 web 测试用 `sqlite:///:memory:` 跑（避免依赖真实 MySQL），通过 repository 抽象自动命中 SQLite 实现。集成测试在 Phase 0 末提供 `pytest -m integration` 跑真实 MySQL。

## 5. 文档矩阵

| 路径 | 内容 | 何时写 |
|---|---|---|
| `docs/web-mvp/plans/00-overall-plan.md` | 本文件 | 阶段0 启动前 |
| `docs/web-mvp/plans/phase-N-*.md` | 每阶段详细设计 | 每阶段开工前 |
| `docs/web-mvp/records/2026-07-25-NN-*.md` | 每次 commit 级变更 | 每次写代码时 |
| `docs/web-mvp/retros/issue-*.md` | 遇到的问题复盘 | 出现问题时 |
| `docs/web-mvp/standards/web-coding-conventions.md` | Web 层命名/结构/异常风格 | 阶段1 收尾 |
| `docs/web-mvp/standards/repository-extension.md` | 如何给 Repository 加新方法 | 阶段1 收尾 |
| `docs/web-mvp/standards/htmx-patterns.md` | HTMX 片段协议 | 阶段2 收尾 |
| `docs/web-mvp/standards/manual-verification-checklist.md` | 人工验收清单 | 阶段3 收尾 |
| `docs/web-mvp/REMAINING.md` | MVP 收尾时明确剩余任务 | 阶段3 收尾 |

## 6. 关键风险与对策

| 风险 | 对策 |
|---|---|
| 修改 Service 影响 CLI | 所有 Web 路由在 `ielts_buddy.web` 子包，物理隔离；每阶段 `pytest tests/ -x` 跑全量回归 |
| 引入 FastAPI 后拖慢 CLI import | Web 入口独立模块，CLI 不 import web 包；`pyproject.toml` 不把 fastapi 设为必需 |
| JWT 密钥泄露 | 从环境变量读；开发默认随机生成（启动时 warn） |
| 艾宾浩斯算法被改 | 完全沿用 `ReviewService.record_learn`，Web 层不重复实现 |
| 模板与 Service 数据不匹配 | 在 schemas.py 统一序列化函数，Service 返回 Pydantic → 模板字段 |
| 多人同时学习 | 默认 FastAPI 异步 + uvicorn 单 worker 即可（学习是低 QPS 场景） |

## 7. 不在本 MVP 范围

显式声明以下内容**不在本次范围**：
- 邮件/Feishu/Deploy/Course 等命令组
- 模拟考试（exam）、批改（grade）、写作（write）、口语（speak）、听力（listen）、计划（plan）、报告（report）、推荐（recommend）、同步（sync）命令
- 拖拽交互、富文本编辑器、ECharts 大屏
- 第三方 OAuth 登录
- 多语言（i18n）
- PWA / 离线
- 反向代理 / HTTPS（生产环境另开）

完成 MVP 后会单独规划 Phase 4（剩余命令组的 Web 化）。

## 8. 完成定义（DoD）

- 所有 5 个页面人工验收通过
- `pytest tests/ -q` 全部 PASS，原有 637+ 测试不退化
- `docs/web-mvp/` 下 5 类文档齐全
- `docs/web-mvp/REMAINING.md` 列出后续 Phase 4+ 任务
- 单条命令 `uvicorn ielts_buddy.web.main:app --reload` 可启动
- `python -m ielts_buddy.web.main --port 8000` 可启动（不需要改 ib CLI）
