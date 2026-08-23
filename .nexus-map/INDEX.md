# IELTS Apply Seek — Nexus Map Index

> generated_by: nexus-mapper v2
> verified_at: 2026-08-23
> provenance: file-tree + git-stats + manual inspection (AST extraction unavailable due to missing tree-sitter)
> last_major_refactor: v3.0.0（MySQL 主存 + SQLite 离线 + 双向同步）

## 项目概述

IELTS Apply Seek（ielts-apply-seek）是一款面向程序员的 **雅思备考 CLI 工具**，将词汇学习、写作辅助、口语练习和科学复习整合到终端中；同时提供 Web 端（FastAPI + uvicorn）。项目基于开源项目 IELTS Buddy 进行二次开发。**v3 起 Web/CLI 共享统一 `users` 表，数据存于 MySQL 主存 + 本地 SQLite 兜底缓存。**

## 核心系统

| 系统 | 职责 | 代码路径 | 状态 |
|------|------|----------|------|
| **CLI 入口** | 命令行接口编排，14 个命令组，46+ 个子命令 | `src/ielts_buddy/cli.py` | implemented |
| **Web 入口** | FastAPI app + 路由 + lifespan | `src/ielts_buddy/web/main.py` | implemented |
| **FallbackContainer** | **v3**：MySQL+SQLite 双 backend，自动降级/回切 | `src/ielts_buddy/repositories/fallback_repo.py` | implemented |
| **SyncWorker** | **v3**：MySQL↔SQLite 双向增量同步 + last-write-wins | `src/ielts_buddy/services/sync.py` | implemented |
| **db_health** | **v3**：MySQL ping + TTL 缓存 | `src/ielts_buddy/services/db_health.py` | implemented |
| **统一 auth** | **v3**：users 表（CLI+Web 共用），web auth 适配 MySQL | `src/ielts_buddy/web/auth/repository.py` | implemented |
| **词汇系统** | 大词库加载（4485词）、精选词库、艾宾浩斯复习、SQLite 缓存 | `src/ielts_buddy/services/vocab_service.py` | implemented |
| **数据模型** | Pydantic 数据模型定义（Word、LearningRecord、StudyPlan 等） | `src/ielts_buddy/core/models.py` | implemented |
| **命令层** | 15 个命令模块（vocab/stats/plan/sync/email/write/speak/report/listen/grade/deploy/exam/feishu/recommend/auth/db_status） | `src/ielts_buddy/commands/` | implemented |
| **服务层** | 19 个业务服务（词汇/复习/统计/邮件/写作/口语/sync 等） | `src/ielts_buddy/services/` | implemented |
| **数据层** | SQLite + MySQL 双实现 + Factory | `src/ielts_buddy/repositories/` | implemented |
| **v3 迁移脚本** | **v3**：MySQL DDL 升级 + web_users → users 合并 | `scripts/migrate_v3_*.py` | implemented |
| **测试套件** | 642+ 个测试用例，含 v3 同步集成测试 | `tests/` | implemented |

## v3 架构亮点

```
┌─────────────────┐                    ┌─────────────────┐
│   Web (FastAPI)  │                    │  CLI (Click)    │
│   + asyncio      │                    │  + threading    │
│   SyncWorker     │                    │  SyncWorker     │
└────────┬─────────┘                    └────────┬─────────┘
         │                                      │
         ▼                                      ▼
   ┌─────────────────────────────────────────────────────┐
   │              FallbackContainer                      │
   │  ┌─────────────┐         ┌────────────────────┐     │
   │  │ online      │ ◀─────▶ │ fallback_sqlite    │     │
   │  │ MySQL 容器  │  sync   │ SQLite 容器        │     │
   │  └─────────────┘         └────────────────────┘     │
   └─────────────────────────────────────────────────────┘
              │                       │
              ▼                       ▼
      ┌──────────────┐        ┌────────────────┐
      │ MySQL 主存   │        │ ~/.ielts-buddy/│

---

## [操作指南] 强制执行步骤

> 本节是对所有读取本文件的 AI 发出的硬性操作指令，不是建议。

### 步骤1 — 必须先读完以下所有文件（顺序不限）

读完本文件后，在执行任何任务之前，必须依次 read 以下文件完整内容：

- `.nexus-map/arch/systems.md` — 系统边界与代码位置
- `.nexus-map/arch/dependencies.md` — 系统间依赖关系与 Mermaid 图
- `.nexus-map/arch/test_coverage.md` — 测试面与证据缺口
- `.nexus-map/hotspots/git_forensics.md` — Git 热点与耦合风险
- `.nexus-map/concepts/domains.md` — 核心领域概念

> 这些文件均为高密度摘要，总量通常 < 5000 tokens，是必要的上下文成本。
> 不得以"任务简单"或"只改一个文件"为由跳过。

### 步骤2 — 按任务类型追加操作（步骤1 完成后执行）

- 若任务涉及**接口修改、新增跨模块调用、删除/重命名公共函数**：
  → 必须运行 `query_graph.py --impact <目标文件>` 确认影响半径后再写代码。
- 若任务需要**判断某文件被谁引用**：
  → 运行 `query_graph.py --who-imports <模块名>`。
- 若仓库结构已发生重大变化（新增系统、重构模块边界）：
  → 任务完成后评估是否需要重新运行 nexus-mapper 更新知识库。
