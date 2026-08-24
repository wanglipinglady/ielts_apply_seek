# INDEX — IELTS Buddy (ielts-apply-seek)

> generated_by: nexus-mapper v2
> verified_at: 2026-08-23
> provenance: AST-backed (Python 198/198 files) with inferred notes for non-Python (bash ×3, javascript ×9, sql ×1)

## 一句话定位

**IELTS Buddy** 是面向雅思考生的本地优先 + 在线同步双模式训练工具：FastAPI Web + Click CLI 双入口、SQLite/MySQL 双后端、覆盖词汇循环 / 四技能真题 / 口语批改 / 备考资源广场（v3.8 新增）/ 阅读真题题库（v3.8 新增）。

## 核心数据（90 天）

| 指标 | 值 |
| --- | --- |
| Python 源文件 | 198 |
| 代码行数 | 58,399 |
| 顶层节点 (Module + Class) | 770 |
| Import 边 | 5,338 |
| Git 提交 | 67 (3 位作者) |
| 测试模块 | 86 (含 4 个测试包) |

## 五大系统（System）

| ID | 名称 | 行数 / 热点 |
| --- | --- | --- |
| `ielts-buddy-web-application` | FastAPI Web (28 页面) | 6 routers + main.py，热点 🔴 (19 变更) |
| `ielts-buddy-cli-application` | Click + Rich CLI | 17 命令组 / 65 子命令 |
| `ielts-buddy-persistence-layer` | SQLite + MySQL + Fallback | Protocol 抽象 + v3 容器回退 |
| `ielts-buddy-service-layer` | 26 领域服务 | 词库 / 考试 / 评分 / 同步 / v3.8 备考 |
| `ielts-buddy-core-foundation` | Models + Config + Auth | 被 46 模块 import 的枢纽 |

## 四大领域（Domain）

`vocab-learning`（词库闭环）· `exam-simulation`（四技能真题+LLM评分）· `prep-resources`（v3.8 资源广场+阅读题库）· `sync-daemon`（本地→在线守护同步）。

## 三处最高风险（hub + git）

1. `src/ielts_buddy/web/main.py` — 19 变更，与 `base.html` 耦合度 1.00，**重构前必读耦合数据**。
2. `src/ielts_buddy/repositories/sqlite_repo.py` — 16 变更，依赖核心 11 个模块；与 `mysql_repo.py` 形成双胞胎对。
3. `src/ielts_buddy/repositories/mysql_repo.py` — 11 变更；`scripts/init_mysql.sql` 与 `migrate_v3_mysql_schema.py` 强耦合（schema 与脚本同改）。

## 操作指南（硬路由）

| 场景 | 第一动作 |
| --- | --- |
| 改 Web 路由 | 先读 `arch/systems.md` → 改 routers → 看 `hotspots/git_forensics.md` 检查 main.py 耦合 |
| 改数据库 schema | 先读 `concepts/domains.md` 确认领域归属 → 看 `arch/dependencies.md` 检查 repository → 同步 `scripts/init_mysql.sql` 与 `migrate_v3_mysql_schema.py` |
| 新增 CLI 命令 | 参考 `arch/systems.md` 的 `ielts-buddy-cli-application` 章节 |
| 看测试覆盖 | `arch/test_coverage.md`（4 测试包 ×86 模块 ×24k 行） |
| 解释架构 | `arch/systems.md` + `arch/dependencies.md`（含 Mermaid 图） |
| 查 git 热点 | `hotspots/git_forensics.md` |

## 证据缺口（evidence gap）

- **Function 节点被截断**（3311 个）：当前 AST 在 `--max-nodes 500` 下只保留 Module + Class；后续如需查看函数级热度，请用 `--max-nodes 200` 重跑或直接 `grep -n 'def '` 目标文件。
- **3 个非 Python 文件未解析**：bash（3）、javascript（9）、sql（1），主要为工具脚本和 `.github/workflows/`，不影响主架构结论。
- **CI 状态未运行**：测试静态覆盖率来自 AST 文件计数，未实际触发 `pytest`；CI 健康度不在本产物范围内。

## 文档结构

```
.nexus-map/
├── INDEX.md                          ← 本文件 (L0 摘要)
├── raw/
│   ├── ast_nodes.json                ← Tree-sitter Python 提取
│   ├── git_stats.json                ← 90 天提交热点
│   └── file_tree.txt                 ← 过滤后的源码目录
├── concepts/
│   ├── concept_model.json            ← Schema V1, 10 节点 / 17 边
│   └── domains.md                    ← 4 大领域语义说明
├── arch/
│   ├── systems.md                    ← 5 系统边界
│   ├── dependencies.md               ← Mermaid 依赖图
│   └── test_coverage.md              ← 静态测试面 + 缺口
└── hotspots/
    └── git_forensics.md              ← 风险热点 + 耦合对
```