# Web 端开发规范与文档索引

> 后续 Web 化工作（包括 T-01~T-19）必读。
> 任何修改 Web 子包前先翻这份索引，确保新代码符合既有约定。

---

## 1. 必读 5 份文档

| 文档 | 何时读 |
|---|---|
| [`plans/00-overall-plan.md`](plans/00-overall-plan.md) | 接手 Web 时第一份读 |
| [`standards/web-architecture.md`](standards/web-architecture.md) | 写新模块 / 新路由前 |
| [`standards/web-auth.md`](standards/web-auth.md) | 动认证相关代码前 |
| [`standards/web-stats.md`](standards/web-stats.md) | 动统计相关代码前 |
| [`standards/web-study.md`](standards/web-study.md) | 动学习/复习相关代码前 |

## 2. 4 条硬约束（违反任意一条 PR 拒绝）

1. **零侵入 CLI**：`src/ielts_buddy/services/` `src/ielts_buddy/repositories/` `src/ielts_buddy/core/` `src/ielts_buddy/commands/` `src/ielts_buddy/cli.py` **不许改一行**。
   - Web 端复用：借壳 / 直 SQL / 共享 VocabService 单例
   - 例外（待 T-01）：`SQLiteRepositoryContainer.__init__` 加 `check_same_thread` 参数

2. **Web 端所有 SQLite 连接走 `get_stats_conn`**：
   - `conn: Annotated[sqlite3.Connection, Depends(get_stats_conn)]`
   - 禁止路由函数内 `sqlite3.connect(...)`
   - 跨线程安全靠 `check_same_thread=False`（lifespan 阶段开）

3. **`Annotated[X | None, Depends(...)]` 不要用 `Optional[X]`**：
   - 路由：`user: Annotated[WebUser | None, Depends(get_current_user_optional)]`
   - 路由内显式判 None → 302 /login

4. **要带 cookie / 自定义 header 的路由必须复用 `response` 形参**：
   ```python
   def api_logout(response: Response) -> Response:
       _clear_refresh_cookie(response)
       response.status_code = 204
       return response
   ```

## 3. 5 条软约束（建议遵守）

1. **Pydantic 响应模型**：API 端点禁止裸 dict
2. **依赖注入构造 Service**：不要在路由函数里 `new Service()`，统一走 `get_*_service`
3. **Jinja2 partial 用 `{% if X %}fallback{% else %}{% endif %}` 兜底**：route 不传时 partial 仍能渲染
4. **跨文件复用的 fixture 放 conftest.py**：`tests/test_web/conftest.py` 已有 3 个（`client` / `client_with_db` / `registered_user`）
5. **重构同名路由前先 grep**：`@router\.(get|post).*<path>` 全文，避免 silent ignore

## 4. 测试约定

### 4.1 三个核心 fixture

| Fixture | 用途 |
|---|---|
| `client` | 内存 SQLite user repo，不持久化；适合 boot/auth 单测 |
| `client_with_db` | `tmp_path` 上 web_data.db，适合 stats/study 业务表测 |
| `registered_user` | 1 个注册好的用户（dict 含 email/password/user_id/access_token/refresh_token） |

### 4.2 覆盖清单

每个新功能必须覆盖：
- 401（API 未登录）/ 302（页面未登录）
- 200 + 关键字段
- 多用户隔离（A 看不到 B 的数据）
- 异常路径（404 / 400 / 422）

### 4.3 跑测命令

```bash
# Web 端
PYTHONPATH=src python -m pytest tests/test_web/ -v

# CLI 业务回归（确保 Web 改造没破坏后端）
PYTHONPATH=src python -m pytest tests/test_services tests/test_commands tests/test_repositories -q
# 当前基线：1009 passed, 31 failed（pre-existing，与 Web 无关）
```

## 5. 文档目录

```
docs/web-mvp/
├── plans/                      # 阶段计划（0/1/2/3）
├── records/                    # 阶段变更记录（按日期 + 序号）
├── retros/                     # 复盘（每个问题独立小节）
├── standards/                  # 规范（架构 / 认证 / 统计 / 学习）
├── MVP-CLOSEOUT.md             # MVP 收口总报告
├── manual-verify-mvp.md        # 5 个页面整体人工验收
├── manual-verify-phase-1.md    # 阶段 1 单独验收
├── manual-verify-phase-3.md    # 阶段 3 单独验收
└── remaining-tasks.md          # 剩余任务 + 工程债 + 文档债
```

### 5.1 文档更新触发条件

| 触发 | 必更新 |
|---|---|
| 改了 `web/main.py` `web/services.py` `web/auth/*` | `standards/web-architecture.md` |
| 加了新认证端点 | `standards/web-auth.md` + `records/YYYY-MM-DD-NN-*.md` |
| 加了新 stats 端点 | `standards/web-stats.md` + `records/...` |
| 加了新 study 端点 | `standards/web-study.md` + `records/...` |
| 遇到 bug 调试超过 30 分钟 | `retros/YYYY-MM-DD-issue-name.md` |
| 阶段完成 | `records/YYYY-MM-DD-NN-phase-N-*.md` + 更新 `MVP-CLOSEOUT.md` |
| PR 合并 | `remaining-tasks.md` 里把已完成的勾掉 |

## 6. 已知陷阱（直接照搬避坑）

| 坑 | 解决 |
|---|---|
| `Optional[X]` 类型注解 422 | 用 `X \| None` |
| `response.set_cookie` 不下发 | 复用 `response` 形参 |
| 跨线程 SQLite 异常 | `check_same_thread=False` |
| FastAPI 同名路由 silent ignore | 注册前 grep |
| passlib 1.7.4 与 bcrypt 4.x+ 不兼容 | 用 `bcrypt` 库 |
| 复习空队列 partial 走 fallback 文案 | `partial` 用 `{% if X %}fallback{% else %}` 兜底 |
| bcrypt 72 字节限制 | 业务层 `[:72]` 截断 |
| fixture 跨文件用 | 放 conftest.py |
| `get_streak` 起始日误判 | "今天也算连续"，与 CLI 行为一致 |
| `learning_records.word_data` 反序列化 | 用 `Word(**json.loads(...))` 而非 `parse_obj` |

## 7. 工作流程（新功能）

1. **读 `remaining-tasks.md`**：找到对应 T-NN
2. **读 5 份 standards**：确认改动方向符合约定
3. **写代码**：先抄相似文件（如 stats 路由抄 study 路由）
4. **写测试**：先 401/302 → 再 200 + 数据 → 再多用户隔离 → 再异常路径
5. **跑 web 全测 + CLI 业务回归**：
   ```bash
   PYTHONPATH=src python -m pytest tests/test_web/ tests/test_services tests/test_commands tests/test_repositories -q
   ```
6. **写变更记录**：`records/YYYY-MM-DD-NN-feature.md`
7. **更新 standards**（如有新约定）
8. **更新 remaining-tasks**：把 T-NN 移到已完成区（顶部新增"已完成"段，或 git tag 时记录）
9. **人工验证**：`manual-verify-mvp.md` 追加新功能条目

## 8. 不在本规范范围

- CLI 业务逻辑的修改（CLI 端有自己的规范）
- LLM 调用（grok 集成在 `services/grading_service.py`，跟 Web 无关）
- 数据库 migration（Web 端只走 `CREATE TABLE IF NOT EXISTS`，新表加 DDL 到 `scripts/init_mysql.sql`）
