# IELTS Apply Seek — Nexus Map Index

> generated_by: nexus-mapper v2
> verified_at: 2026-07-16
> provenance: file-tree + git-stats + manual inspection (AST extraction unavailable due to missing tree-sitter)

## 项目概述

IELTS Apply Seek（ielts-apply-seek）是一款面向程序员的 **雅思备考 CLI 工具**，将词汇学习、写作辅助、口语练习和科学复习整合到终端中。项目基于开源项目 IELTS Buddy 进行二次开发，目标是构建一个通用工具，同时服务习惯界面化的用户。

## 核心系统

| 系统 | 职责 | 代码路径 | 状态 |
|------|------|----------|------|
| **CLI 入口** | 命令行接口编排，14 个命令组，46 个子命令 | `src/ielts_buddy/cli.py` | implemented |
| **词汇系统** | 大词库加载（4485词）、精选词库、艾宾浩斯复习、SQLite 缓存 | `src/ielts_buddy/services/vocab_service.py` | implemented |
| **数据模型** | Pydantic 数据模型定义（Word、LearningRecord、StudyPlan 等） | `src/ielts_buddy/core/models.py` | implemented |
| **命令层** | 14 个命令模块（vocab/stats/plan/sync/email/write/speak/report/listen/grade/deploy/exam/feishu/recommend） | `src/ielts_buddy/commands/` | implemented |
| **服务层** | 17 个业务服务（词汇/复习/统计/邮件/写作/口语等） | `src/ielts_buddy/services/` | implemented |
| **数据层** | SQLite 仓库抽象，JSON 数据文件 | `src/ielts_buddy/repositories/` + `data/` | implemented |
| **知识卡片** | 课程内容管理，中文知识卡片生成 | `src/ielts_buddy/services/course_service.py` | implemented |
| **测试套件** | 637 个测试用例，覆盖 commands/services/repositories | `tests/` | implemented |

## 技术栈

- **CLI**: Click 8.0+
- **数据建模**: Pydantic 2.0+
- **UI 美化**: Rich
- **存储**: SQLite + JSON
- **模板**: Jinja2
- **AI 集成**: OpenAI, Anthropic
- **测试**: pytest (637 tests)

## Git 热点（近 90 天）

- `src/ielts_buddy/services/grading_service.py` — 3 次变更（最高风险）
- `src/ielts_buddy/services/exam_service.py` — 2 次变更
- `src/ielts_buddy/services/personal_vocab_service.py` — 2 次变更
- `src/ielts_buddy/services/recommend_service.py` — 2 次变更
- `src/ielts_buddy/services/report_service.py` — 2 次变更

## 耦合关系

核心服务层高度耦合：exam_service 与 grading/personal_vocab/recommend/report/review/stats_service 存在 `coupling_score=1.0` 的强耦合关系，表明这些服务频繁共同变更。

## 项目结构

```
src/ielts_buddy/
├── cli.py                  # CLI 入口 (14 命令组, 46 子命令)
├── commands/               # 命令层 (14 个模块)
├── services/               # 服务层 (17 个业务服务)
├── core/                   # 核心 (models, config, repository 协议)
├── repositories/           # 数据仓库 (SQLite 实现)
├── data/                   # 内置数据 (词库 4485 词 + 资源)
└── templates/             # HTML 模板
```

## 证据缺口

- AST 解析因缺少 tree-sitter 而不可用，节点/边关系来自人工推断
- 部分服务的具体实现细节待进一步确认

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
