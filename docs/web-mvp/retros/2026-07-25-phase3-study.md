# 阶段 3 复盘：随机学习 + 复习

**日期**：2026-07-25
**结论**：阶段 3 全部 10 个测试通过；87 个 web 测试全过；CLI 业务代码未受影响。

## 关键问题

### 问题 1：跨线程 SQLite 异常

**现象**：
```
sqlite3.ProgrammingError: SQLite objects created in a thread can only be used
in that same thread. The object was created in thread id 6150287360 and this
is thread id 6167113728.
```

**定位**：`src/ielts_buddy/services/review_service.py:71 record_learn` → `repositories.sqlite_repo.SQLiteLearningRepository.upsert_record` → `self._conn.execute(...)`。

**根因**：CLI 的 `SQLiteRepositoryContainer.__init__` 用 `sqlite3.connect(str(db_path))`（默认 `check_same_thread=True`）。FastAPI 同步端点跑在 anyio threadpool，跨 worker 报这个错。

**为什么之前 `WebStatsService` 没事**：`stats_service.py` 用 `app.state.web_stats_conn`（lifespan 阶段开，`check_same_thread=False`），是独立连接。

**决策**：不动 `SQLiteRepositoryContainer`（项目硬约束：Service / Repository 层零修改）。study 路由**不借壳 ReviewService**，直接用 `app.state.web_stats_conn` 写 learning_records。

**技术沉淀**：
- 一个进程里**多份** SQLite 连接可以并存：CLI 用 `SQLiteRepositoryContainer._conn`（主线程），Web 用 `web_stats_conn`（任何线程），两者指向**同一文件**时互不干扰。
- `check_same_thread=False` 是 SQLAlchemy / Django ORM 的默认行为之一；手写 sqlite3 时**必须显式设置**，否则被 threadpool 干翻。
- 后续阶段如果还要走 ReviewService 写 learning_records，要么：① 在 lifespan 阶段给 container 的 conn 加 `check_same_thread=False`（侵入 CLI 代码）；② 在 Web 端实现一个**Adapter**，把 ReviewService 包装成走 web_stats_conn —— 但这其实就是现在的方案，只是拆得更细。
- **推荐**：阶段 4（Service 重构走 Repository）时，把 `SQLiteRepositoryContainer.__init__` 加一个 `check_same_thread: bool = False` 参数，CLI 默认 True，Web 默认 False。这样 ReviewService / VocabService 等可以无修改复用。

### 问题 2：`/dashboard` 路由被旧版覆盖

**现象**：`test_dashboard_page_with_data` 失败——预期看到"已掌握"，实际看到"暂无数据"，API `/api/stats/summary` 单独测试却返回 `mastered=1`。

**定位**：`src/ielts_buddy/web/routers/auth.py:257` 和 `pages.py:35` 都定义了 `@router.get("/dashboard")`。`main.py` 里 `app.include_router(auth_routes.router)`（line 177）在 `pages_routes.router`（line 181）之前，前者被 FastAPI 视为第一个注册的 GET 路由，后者被忽略。

**根因**：阶段 1 时 dashboard 是 auth.py 的占位版本（"未登录跳 /login / 已登录展示空壳"），阶段 2 把 dashboard 升级到 pages.py，**但忘了删 auth.py 的占位**。

**修复**：删除 `auth.py:257-269` 的占位，加注释说明 dashboard 在 pages.py。

**技术沉淀**：
- FastAPI `APIRouter.include_router` 是按**注册顺序**匹配路由的——同名路由第一个匹配生效，后续被 silent ignore。
- **重构同名路由时必须全文搜**：`@router\.(get|post).*<path>`，看是否多文件定义。
- 一个改进方向：把 dashboard / stats / study 的"页面路由"全收口到 `pages_routes`（pages.py + study.py），auth.py 只放 `/login /register` 和 `/api/auth/*`。当前 study.py 已经这么做了，但 pages.py 和 auth.py 的边界还可以更清晰。

### 问题 3：Annotated[Optional[X], Depends(...)] 的 422 错误

**现象**：study 路由用 `Annotated[Optional[WebUser], Depends(get_current_user_optional)]`，未登录时 422 而非 302/401。

**定位**：FastAPI 处理 `Optional[T]` 类型注解时，**仍把 T 视为必选**——因为类型擦除后 Optional 跟 T 一样。`get_current_user_optional` 函数有 `default=None` 应该 OK，但 FastAPI 看了 `Optional[WebUser]` 优先按必选校验。

**修复**：把 `Optional[WebUser]` 换成 `WebUser | None`（PEP 604 联合类型），FastAPI 看到 `X | None` 不会拆成 X。

**技术沉淀**：
- `Optional[X]` 在 Pyright / IDE 看来是 `X | None`，但 FastAPI 的类型解析基于 `get_type_hints`，对 `Optional` 的处理不如 PEP 604 直接。
- 一致性建议：**Web 端路由里所有"可选注入"都用 `X | None`**（page_dashboard / study 路由都统一了）。
- 阶段 2 留下的 pages.py 是 `Annotated[Optional[WebUser], Depends(get_current_user_optional)]` —— 当时能跑通是因为 FastAPI 版本对 Optional 还没这么严，或者 pages.py 注册顺序靠前侥幸过关。后续可以统一改成 `WebUser | None`。

### 问题 4：测试 fixture 重复定义

**现象**：`client_with_db` 和 `web_db_path` 在 `tests/test_web/test_stats_api.py` 私有，study 测试找不到。

**根因**：写 stats 测试时没意识到这两个 fixture 会跨测试文件复用。

**修复**：上移到 `tests/test_web/conftest.py`，stats test 里的本地副本删掉。

**技术沉淀**：
- **跨文件复用的 fixture 必须放 conftest.py**。
- 写完第二个测试文件时**复盘**前一个的私有 fixture，能合并就合并。

### 问题 5：partial 默认提示文案跟 mode 不匹配

**现象**：复习空队列时显示"今日新词已学完 ✅"。

**定位**：`_study_card.html` 写的是 `{{ empty_msg or "今日新词已学完 ✅" }}`；但 `page_study_review` 没传 `empty_msg`（路由只算 `due_remaining`），partial 走 fallback。

**修复**：partial 里按 `mode` 分支给默认提示；路由层在 `word is None` 时显式传 `empty_msg`，跟 fallback 保持一致。

**技术沉淀**：
- partial 默认文案要跟 route 显式传值保持一致；route 不传时 partial 必须有合理 fallback，反之亦然。
- 写 partial 时**别假定 route 一定会传 X**——给 X 设个 `{% if X %}...{% else %}fallback{% endif %}` 兜底。

## 决策记录

| 决策 | 备选 | 选这个的理由 |
| --- | --- | --- |
| study 路由直接走 web_stats_conn | 借壳 ReviewService | 后者跨线程 bug，绕开最简；阶段 4 走 Repository 时再统一 |
| VocabService 单例复用（lru_cache） | 每次请求 new VocabService | 词库 ~10MB，加载耗时长 |
| 答题端点返回 partial HTML | 返回 JSON + 客户端拼 | Jinja2 渲染在服务端，前端不写 JS |
| `hx-swap="outerHTML"` 替换整张题卡 | innerHTML / beforeend | 整张卡包含"显示答案"按钮的 hidden 切换状态，重置干净 |
| 新词选题：band 5-9 随机 + 过滤已学 | 按 band 等量 / 按 user 偏好 | MVP 简单优先；后续可加偏好字段 |
| 复习选题：取 memory_level ASC + next_review ASC 一题 | 一次性拉 20 题缓存 | MVP 单题；多题缓存涉及 HTMX 端点设计更复杂 |
| 答题结果"显示答案"按钮用原生 onclick | HTMX 切换 hidden | hidden 切换是单元素状态机，HTMX 收益小、引入额外请求 |

## 后续沉淀

- **架构原则**：Web 端所有 SQLite 操作必须用 `app.state.web_stats_conn`（`check_same_thread=False`）。不要借壳 CLI 的 Service / Repository。
- **新增 Web 端业务路由的 checklist**：
  1. 路由函数用 `get_current_user_optional`（页面）或 `get_current_user`（API）
  2. `Annotated[WebUser | None, Depends(...)]` 而不是 `Optional[WebUser]`
  3. 数据库走 `conn: Annotated[sqlite3.Connection, Depends(get_stats_conn)]`
  4. partial 模板用 `{% if word %}` + `{% if empty_msg %}fallback{% else %}{% endif %}` 兜底
  5. 测试同时覆盖 401（API）、302（页面）、200+数据、用户隔离

## 踩坑清单（避免再犯）

1. FastAPI `include_router` 同名路由按注册顺序匹配——重构前先 grep。
2. `Annotated[Optional[X], Depends(...)]` 在 FastAPI 里行为不对，用 `X | None`。
3. SQLite 跨线程要 `check_same_thread=False`，lifespan 阶段统一开。
4. partial 默认文案要跟 route 显式传值保持 fallback 关系。
5. fixture 跨文件就上移 conftest.py。
