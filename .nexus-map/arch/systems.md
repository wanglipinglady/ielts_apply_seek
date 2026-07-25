# Systems — 系统边界与代码位置

> generated_by: nexus-mapper v2
> verified_at: 2026-07-16
> provenance: file-tree + manual inspection

## 系统边界定义

### 1. CLI 入口系统 (cli-entry)

| 属性 | 值 |
|------|-----|
| **职责** | 命令行接口编排，注册 14 个命令组，46 个子命令 |
| **代码路径** | `src/ielts_buddy/cli.py` |
| **状态** | implemented |
| **入口点** | `cli()` 函数，Click group |

**子命令注册**:
- vocab, stats, plan, sync, email, write, speak, report, listen, grade, deploy, exam, feishu, recommend, course

---

### 2. 词汇学习系统 (vocabulary-system)

| 属性 | 值 |
|------|-----|
| **职责** | 大词库加载（4485词）、精选词库、艾宾浩斯复习、SQLite 缓存、内存索引加速 |
| **代码路径** | `src/ielts_buddy/services/vocab_service.py` |
| **状态** | implemented |

**关键组件**:
- `VocabService` 类：词库加载、搜索、过滤
- SQLite 缓存：`vocab_cache.db`
- 内存索引：`_word_index`, `_band_index`, `_topic_index`, `_search_index`

---

### 3. 数据模型系统 (data-models)

| 属性 | 值 |
|------|-----|
| **职责** | Pydantic 数据模型定义，统一数据结构 |
| **代码路径** | `src/ielts_buddy/core/models.py` |
| **状态** | implemented |

**核心模型**:
- `Word`: 词库单词模型
- `LearningRecord`: 学习记录模型
- `TestSession`: 测试会话模型
- `DailySummary`: 每日学习摘要
- `StudyPlan`: 学习计划模型
- `PersonalWord`: 个人词库单词
- `GradeResult`: AI 写作批改结果

---

### 4. 命令层系统 (commands-layer)

| 属性 | 值 |
|------|-----|
| **职责** | 14 个命令模块，提供用户交互接口 |
| **代码路径** | `src/ielts_buddy/commands/` |
| **状态** | implemented |

**命令模块列表**:
| 模块 | 主要功能 |
|------|---------|
| `vocab.py` | 随机单词、测验、复习、搜索、浏览、个人词库 |
| `stats.py` | 统计展示、趋势分析、进度查看 |
| `plan.py` | 学习计划设置与展示 |
| `sync.py` | 数据同步 |
| `email.py` | 邮件预览与发送 |
| `write.py` | 写作辅助（话题、句型、同义词） |
| `speak.py` | 口语练习（Part 1/2/3 话题） |
| `report.py` | 网页报告生成 |
| `listen.py` | 听力资源、听写模式 |
| `grade.py` | AI 写作批改 |
| `deploy.py` | GitHub Pages 部署 |
| `exam.py` | 模拟考试 |
| `feishu.py` | 飞书多维表格同步 |
| `recommend.py` | 智能学习推荐 |
| `course.py` | 课程内容管理 |

---

### 5. 服务层系统 (services-layer)

| 属性 | 值 |
|------|-----|
| **职责** | 17 个业务服务，实现核心业务逻辑 |
| **代码路径** | `src/ielts_buddy/services/` |
| **状态** | implemented |

**服务列表**:
| 服务 | 职责 |
|------|------|
| `vocab_service.py` | 词库管理 |
| `review_service.py` | 艾宾浩斯复习调度 |
| `stats_service.py` | 学习统计 |
| `plan_service.py` | 学习计划管理 |
| `email_service.py` | 邮件发送 |
| `writing_service.py` | 写作辅助 |
| `speaking_service.py` | 口语练习 |
| `listening_service.py` | 听力资源 |
| `grading_service.py` | AI 写作批改 |
| `deploy_service.py` | GitHub Pages 部署 |
| `exam_service.py` | 模拟考试 |
| `report_service.py` | 网页报告生成 |
| `feishu_service.py` | 飞书同步 |
| `recommend_service.py` | 智能推荐 |
| `personal_vocab_service.py` | 个人词库管理 |
| `sync_service.py` | 数据同步 |
| `course_service.py` | 课程内容管理 |

---

### 6. 数据仓库系统 (repository-layer)

| 属性 | 值 |
|------|-----|
| **职责** | 数据持久化抽象，SQLite 实现 |
| **代码路径** | `src/ielts_buddy/repositories/` |
| **状态** | implemented |

**核心文件**:
- `repository.py`: 仓库接口协议定义
- `sqlite_repo.py`: SQLite 实现

---

### 7. 内置数据系统 (built-in-data)

| 属性 | 值 |
|------|-----|
| **职责** | 词库 JSON 文件、资源数据 |
| **代码路径** | `src/ielts_buddy/data/` |
| **状态** | implemented |

**数据文件**:
| 文件 | 内容 |
|------|------|
| `vocab_band5.json` | Band 5 词汇 (1227词) |
| `vocab_band6.json` | Band 6 词汇 (1127词) |
| `vocab_band7.json` | Band 7 词汇 (1076词) |
| `vocab_band8.json` | Band 8 词汇 (745词) |
| `vocab_band9.json` | Band 9 词汇 (310词) |
| `vocab_master.json` | 大词库 (4485词) |
| `writing_templates.json` | 写作句型模板 |
| `writing_topics.json` | 写作话题 |
| `speaking_topics.json` | 口语话题 |
| `listening_resources.json` | 听力资源 |
| `synonyms.json` | 同义词表 |

---

### 8. 测试系统 (test-suite)

| 属性 | 值 |
|------|-----|
| **职责** | 637 个测试用例，覆盖 commands/services/repositories |
| **代码路径** | `tests/` |
| **状态** | implemented |

**测试目录**:
- `tests/test_commands/`: CLI 命令测试
- `tests/test_services/`: 服务层测试
- `tests/test_repositories/`: 仓库层测试

---

### 9. 知识卡片系统 (knowledge-cards)

| 属性 | 值 |
|------|-----|
| **职责** | 课程内容管理，中文知识卡片生成 |
| **代码路径** | `src/ielts_buddy/services/course_service.py` |
| **状态** | implemented |

**关联目录**:
- `courses/`: 课程内容目录
- `docs/知识卡片*.md`: 知识卡片制作规范与实现文档

---

## 边界模糊区域

| 区域 | 问题描述 |
|------|---------|
| `utils/` 或 `common/` | 未发现明显的 utils/common 目录，边界清晰 |
| AI 集成 | `grok.py` 在 `docs/` 目录，与服务层的 AI 调用有一定耦合 |
