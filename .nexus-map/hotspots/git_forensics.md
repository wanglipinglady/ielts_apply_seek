# Git Forensics — 热点与耦合

> generated_by: nexus-mapper v2
> verified_at: 2026-08-23
> provenance: AST + git_stats.json (90 天窗口) + query_graph.py --impact

---

## 1. 提交概览（90 天）

| 指标 | 值 |
| --- | --- |
| 总提交 | 67 |
| 作者数 | 3 |
| 平均提交间隔 | 1.3 天/次 |
| 分析窗口 | 2026-05-25 → 2026-08-23 |

---

## 2. 热点 Top 10（按变更次数）

| # | 文件 | 变更 | 风险 | 备注 |
| ---: | --- | ---: | :---: | --- |
| 1 | `src/ielts_buddy/web/main.py` | 19 | 🔴 high | Web 总入口，耦合度 1.00 (与 base.html) |
| 2 | `src/ielts_buddy/repositories/sqlite_repo.py` | 16 | 🔴 high | 本地仓储，热度最高的数据库代码 |
| 3 | `src/ielts_buddy/web/templates/base.html` | 13 | 🟡 med | 基础模板 |
| 4 | `src/ielts_buddy/repositories/mysql_repo.py` | 11 | 🟡 med | 在线仓储，与 sqlite_repo 是双胞胎 |
| 5 | `scripts/init_mysql.sql` | 10 | 🟡 med | MySQL schema DDL |
| 6 | `src/ielts_buddy/repositories/__init__.py` | 9 | 🟡 med | Repository 容器导出 |
| 7 | `src/ielts_buddy/web/config.py` | 8 | 🟡 med | Web 配置 |
| 8 | `src/ielts_buddy/web/templates/pages/personal_vocab.html` | 8 | 🟡 med | 个人词库页 |
| 9 | `src/ielts_buddy/core/repository.py` | 7 | 🟡 med | Repository Protocol |
| 10 | `scripts/migrate_v3_mysql_schema.py` | 7 | 🟡 med | v3.x schema 迁移 |

> 风险阈值：`changes < 5` → low / `5–15` → medium / `> 15` → high

---

## 3. 强耦合对（co-change ≥ 5）

来自 `query_graph.py --impact --git-stats` 真实查询：

### 3.1 `web/main.py` ↔ `web/templates/base.html`
- **耦合度 1.00**（13 次共同提交）
- **含义**：每次改 main.py 几乎必改 base.html
- **风险**：改路由上下文时连带改前端变量

### 3.2 `web/main.py` ↔ `repositories/sqlite_repo.py`
- **耦合度 0.62**（10 次共同提交）
- **含义**：Web 启动时对仓储的初始化逻辑频繁调整

### 3.3 `web/main.py` ↔ `web/auth/repository.py`
- **耦合度 0.71**（5 次共同提交）
- **含义**：鉴权集成频繁调整

### 3.4 `web/main.py` ↔ `repositories/mysql_repo.py`
- **耦合度 0.46**（5 次共同提交）
- **含义**：启动时在线模式判断

---

## 4. 双胞胎对（必同步修改）

以下文件对**必须**同步修改，否则会破坏双后端一致性：

| 对 | 含义 |
| --- | --- |
| `sqlite_repo.py` ↔ `mysql_repo.py` | 所有 Repository 方法必须两后端都有 |
| `repositories/{sqlite,mysql}_repo.py` ↔ `scripts/init_mysql.sql` | 新表需 DDL |
| `repositories/{sqlite,mysql}_repo.py` ↔ `scripts/migrate_v3_mysql_schema.py` | 在线库迁移脚本 |
| `repositories/{sqlite,mysql}_repo.py` ↔ `core/models.py` | Pydantic 模型与 DB schema 一致 |

---

## 5. Web 端最大影响半径

来自 `--impact src/ielts_buddy/web/main.py`：

| 维度 | 数值 |
| --- | --- |
| 上游依赖（此文件 import） | 11 个内部模块 |
| 下游依赖者（谁 import 此文件） | 8 个模块（含 `__main__`, 4 个 routers, 5 个测试） |
| Git 风险 | 🔴 high（19 变更） |

**结论**：改 main.py 影响 8 个下游模块；每次提交前建议先看 `git diff src/ielts_buddy/web/main.py` 上下游。

---

## 6. v3.8 相关改动分布

近 90 天的 v3.8 P3（备考资源广场 + 阅读真题题库）相关文件变更频率：

| 文件 | 变更 | 性质 |
| --- | ---: | --- |
| `web/main.py` | 19 | 含 v3.8 启动钩子（reading/listening seed） |
| `web/templates/base.html` | 13 | 含 v3.8 导航 |
| `repositories/__init__.py` | 9 | 新增 prep_resource / reading_question 工厂 |
| `web/auth/repository.py` | 7 | 含 v3.8 API 鉴权适配 |

**v3.8 改动量主要集中在 Web + Repository 层**（不意外 — 这是新增功能的标准切入点）。

---

## 7. 风险缓解建议（基于证据，非凭空）

| 风险 | 证据 | 建议 |
| --- | --- | --- |
| 改 main.py 影响 8 个下游 | `--impact` 显示 8 个下游模块 | 大改前先看 `git log --oneline src/ielts_buddy/web/main.py` 了解历史 |
| 双胞胎不一致 | sqlite_repo + mysql_repo 都进了 Top 10 | 任何 Repo 改动后跑 `pytest tests/test_repositories/` |
| Schema 同步缺失 | init_mysql.sql + migrate_v3_mysql_schema.py + 两个 repo 共 4 处 | 新增字段必须 4 处同步 |
| Web 鉴权频繁动 | auth/repository.py 7 变更 + coupling 0.71 | 鉴权层抽接口降低耦合 |
| Function 节点缺失 | AST 截断 3311 个 Function | 需要函数级热度时用 `git log --follow --pickaxe-regex -S "def "` 或直接 grep |

---

## 8. evidence gap

- **耦合度数据**：仅 `git_stats.json` + `git_detective.py` 默认算法产出，未做时间窗口细分。
- **作者维度贡献度**：未分析 3 位作者的代码所有权分布（团队协作风险未知）。
- **CI 状态**：未在本产物中包含 CI 通过率；后续可关联 GitHub Actions 历史。