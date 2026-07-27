# 剩余任务清单（MVP 之后）

**MVP 范围**：登录 + Dashboard + 随机学习 + 复习 + 统计（5 个页面，87 个 web 测试通过）。
**当前未做**：以下任务按优先级 P0/P1/P2 排序。

---

## 0. 自动化基线（运行命令 + 当前结果）

```bash
# Web 端（必须 100% 通过）
PYTHONPATH=src python -m pytest tests/test_web/ -q
# → 87 passed

# CLI 业务回归（Web 改造没破坏后端的判定依据）
PYTHONPATH=src python -m pytest tests/test_services tests/test_commands tests/test_repositories -q
# → ~1009 passed, ~31 failed（失败均为 pre-existing，与 Web 无关）
```

### 0.1 pre-existing 失败归因（2026-07-25 MVP 收口时记录）

**当前沙箱**（Python 3.10 + macOS，无外网）有 31 个测试失败，全部是历史遗留：

| 失败文件 / 用例 | 数量 | 原因 | 是否 Web 引入 |
|---|---|---|---|
| `test_grading_service.py::TestGradeEssay` 等 | 14 | 调真实 LLM（grok），无 mock；沙箱无外网 | ❌ pre-existing |
| `test_email_service.py::TestGenerateDailyEmail` | 11 | jinja2 模板字段 `'day_num' is undefined` | ❌ pre-existing |
| `test_auth_cli.py::TestAuthLogin::test_login_writes_back_user_id_to_config` | 1 | `ModuleNotFoundError: No module named 'tomllib'` | ❌ pre-existing |
| `test_auth_service.py::TestLogin::test_login_writes_back_user_id_to_config` | 1 | 同上 | ❌ pre-existing |
| `test_grading_service.py::TestGradeEssay::test_grade_essay_success` | 1 | LLM 返回 score 5.0 期望 6.5（断言漂移） | ❌ pre-existing |
| `test_grading_service.py::TestErrorStats::test_error_summary_persisted_in_column` | 1 | LLM 返回 `{}` 期望非空 | ❌ pre-existing |
| `test_grading_service.py::TestTaskType::test_grade_essay_task1_academic` | 1 | LLM 返回 `None` 期望 dict | ❌ pre-existing |
| `test_grading_service.py::TestCallGrok::test_call_grok_*` | 4 | mock 路径断言漂移 | ❌ pre-existing |

**判定标准**：MVP 收口后**任一**CLI 测试由"通过"变"失败"才算 Web 引入的回归。

### 0.2 后续处理建议

- **test_grading_service.py 失败**：沙箱外网 + LLM mock 改造（用 `pytest-mock` 或 `vcrpy`）；不在 Web 范围
- **test_email_service.py `'day_num' undefined`**：jinja2 strict mode 兼容 / 模板加 `{% set day_num = ... %}`；可独立 PR
- **tomllib 失败**：3.10 装 `tomli`；CI 切 3.11+ 即解
- 上述 3 项不阻塞 Web 推进，独立排期

---

## 1. P0：必须做（生产前阻塞）

### T-01 把 Service 改成走 Repository + 切 MySQL
- **目标**：Web 端能切 MySQL（生产部署需要），CLI 继续 SQLite
- **现状**：study 路由自己写 SQL，绕开 ReviewService（跨线程 bug）。阶段 2 也自己写 WebStatsService。CLI 的 `SQLiteRepositoryContainer` 不能动。
- **方案**：
  1. `SQLiteRepositoryContainer.__init__` 加 `check_same_thread: bool = True` 参数
  2. CLI 默认 `True`（保持原行为），Web 显式传 `False`
  3. 把 WebStatsService / study 路由的 SQL 改回走 `container.learning` 抽象
  4. Web 端注册 MySQL 容器（`create_repositories(mode="online", connection_url=...)`）
  5. 数据库 init SQL（`scripts/init_mysql.sql`）已存在，验证表结构对齐
- **影响**：study 路由、stats 路由、main.py 的 lifespan
- **风险**：跨线程 + 跨数据库 dialect，SQL 兼容性要复测

### T-02 CSRF 保护
- **现状**：refresh token 用 HttpOnly + SameSite=Lax cookie，dev 安全；生产需要 CSRF
- **方案**：在 `api_router` 加 CSRF 中间件，对 POST/PUT/DELETE 校验 `X-CSRF-Token` header（值 = cookie 里的 csrf_token）
- **影响**：auth router、study router、stats router 的写端点

### T-03 生产部署配置
- systemd unit（`EnvironmentFile=/etc/ielts-buddy/web.env`）
- nginx 反代（gzip + WebSocket 转发给 uvicorn）
- 阿里云 ECS / RDS 的 MySQL DSN 注入

## 2. P1：强烈建议（半年内）

### T-04 错题本 / 收藏夹
- CLI 已有 `vocab_categories` 表（favorites / mistakes 两个 system 分类）
- Web 端缺入口：当前 study 页只能答 ✓/✗，不能加星标 / 加入错词本
- 需要：星标按钮 + 错词本页 `/vocab/mistakes` + 收藏夹页 `/vocab/favorites`

### T-05 考试 / 批改 / 写作 / 口语（CLI 其它 9 大模块）
- CLI 已有 9 个 Service（exam/grade/writing/speaking/...），都没 Web 化
- 优先级建议：
  1. **考试**（exam）：题库 + 答题 + 报告，跟学习最相关
  2. **批改**（grade）：长任务，需 SSE 流式响应（已有项目经验 `W3_W6_阶段问题复盘.md`）
  3. **写作 / 口语**：素材库 + 模板
  4. **推荐 / 报告 / 课程 / 飞书 / 邮件**：运维类
- 每个 Web 化前先确认 Service 是否需要 Repository 化（见 T-01）

### T-06 复习多题缓存
- 当前复习只显示一题，答对后再访问会重新选（按 memory_level ASC 可能选到同一题）
- 方案：进入复习时拉 20 题到 session/cookie，答完一题从队列取下一题

### T-07 i18n
- 现状：中文硬编码在模板 / 路由文案
- 方案：i18n 框架（建议 `fastapi-babel` 或手写 dict），至少 zh-CN / en-US 两套

### T-08 词汇难度自适应
- 当前随机学习：band 5-9 等概率随机
- 方案：根据用户最近正确率动态调整 band 分布（答得好的提升 band）

## 3. P2：可选（远期）

### T-09 PWA / 移动端
- 加 manifest.json + service worker，可离线查看统计、复习

### T-10 数据导入 / 导出
- CLI 已有 `sync_service` 导出 CSV / JSON
- Web 端缺下载入口：`/api/sync/export?format=csv`

### T-11 第三方登录
- 加 OAuth2（Google / GitHub），免去邮箱注册

### T-12 暗色模式
- CSS variables 已抽离，加 `@media (prefers-color-scheme: dark)`

### T-13 错题本推送
- 答错的词加进 "今日错词" 列表，每日邮件推送（CLI 已有 daily_email.html）

### T-14 学习小组 / 排行榜
- 需新增 group / score 表
- 多用户数据共享维度

## 4. 工程债

### T-15 删 `pages.py:44-58` 里的 `_bind_user` 改 setter 副作用
- 当前 `WebStatsService(user_id=0)` 之后又 `svc._user_id = int(user.id)`，是 hack
- 阶段 1 重构时改：依赖注入 `get_stats_service(user: WebUser = Depends(get_current_user))` 直接构造

### T-16 抽公共 `Optional[WebUser]` 依赖
- 5 个页面路由都写 `Depends(get_current_user_optional)`，提到 `auth.deps`
- 顺便把 `Annotated[Optional[WebUser], ...]` 统一成 `Annotated[WebUser | None, ...]`

### T-17 删 `auth.py` 顶部的 import 检查 + 占位代码
- 阶段 1 留下的 `from ielts_buddy.web.auth.repository import WebUser` 保留就行
- 占位代码全清理

### T-18 templates/ 目录加 base_layout.html 抽出 header/footer
- 当前 base.html 已经是 layout，但 partials 里部分 inline 渲染了 header
- 阶段 4 重构时统一

### T-19 增 CI：GitHub Actions 跑 web 测试
- `.github/workflows/ci.yml` 已有 CLI 跑测，追加 web job：
  ```yaml
  web-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -e ".[web]"
      - run: PYTHONPATH=src pytest tests/test_web/ -v
  ```

## 5. 文档债

- [ ] 各 CLI 命令的 Web 化方案（哪些走 SSE / 哪些走轮询 / 哪些直接同步）
- [ ] 性能压测报告（dashboard 页面在 10k 学习记录下的响应时间）
- [ ] 安全审计（密码强度 / rate limit / SQL 注入 / XSS）
- [ ] 部署 runbook（systemd + nginx + MySQL + 备份恢复）

## 优先级小结

| 序号 | 任务 | 优先级 | 估时 | 备注 |
| --- | --- | --- | --- | --- |
| T-01 | Service 重构 + MySQL | P0 | 2 周 | 阻塞生产 |
| T-02 | CSRF | P0 | 3 天 | 阻塞生产 |
| T-03 | 生产部署 | P0 | 1 周 | 阻塞生产 |
| T-04 | 错题本 / 收藏夹 | P1 | 1 周 | 提升完成度 |
| T-05 | 9 个 CLI 模块 Web 化 | P1 | 1-2 月 | 最大工作量 |
| T-06 | 复习多题缓存 | P1 | 3 天 | 体验优化 |
| T-07 | i18n | P1 | 1 周 | 国际化 |
| T-08 | 自适应难度 | P2 | 1 周 | 算法 |
| T-09 | PWA | P2 | 1 周 | 移动端 |
| T-10 | 数据导入导出 | P2 | 3 天 | 工具 |
| T-11 | 第三方登录 | P2 | 1 周 | 增长 |
| T-12 | 暗色模式 | P2 | 2 天 | 体验 |
| T-13 | 错题推送 | P2 | 1 周 | 内容 |
| T-14 | 小组 / 排行榜 | P2 | 2 周 | 增长 |
| T-15~19 | 工程债 | P1 | 1 周 | 维护性 |

---

## 6. 已完成（2026-07-25 MVP 收口时锁定）

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | Web 骨架（FastAPI + Jinja2 + HTMX） | ✅ 6 测试通过 |
| 1 | JWT 认证（注册/登录/refresh/me） | ✅ 47 测试通过 |
| 2 | Dashboard + 完整 Stats | ✅ 9 测试通过 |
| 3 | 随机学习 + 复习 | ✅ 10 测试通过 |
| **合计** | **5 个 MVP 页面，87 web 测试** | **✅ 全部通过** |

详细见 [`MVP-CLOSEOUT.md`](MVP-CLOSEOUT.md)。

