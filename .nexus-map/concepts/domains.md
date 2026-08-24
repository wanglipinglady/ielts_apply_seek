# 领域概念（Domains）

> generated_by: nexus-mapper v2
> verified_at: 2026-08-23
> provenance: AST-backed for service entry points; cross-references inferred from file naming and import direction

本文件解释 4 大业务领域的概念模型、数据流、与服务映射。

---

## Domain 1 — 词汇学习循环 (`ielts-buddy-domain-vocab-learning`)

**业务目标**：让用户用最小时间掌握最有价值的雅思词汇。

**闭环流程**：
```
摄入 (CLI: vocab add / Web: 个人词库添加)
  ↓
LearningRecord (rate: again/hard/good/easy)
  ↓
vocab_service.schedule_review() — 间隔重复算法
  ↓
stats_service.mastery_score() — 掌握度
  ↓
report_service.generate_daily() — 日报聚合
```

**关键模型** (`core/models.py`)：
- `Word` — 单词 + 释义 + 例句 + 标签
- `LearningRecord` — 单次学习记录（含 ease factor, interval, next_review_at）
- `DailySummary` — 每日聚合（new/learning/mastered）

**服务入口**：
- `services/vocab_service.py`（25 fan-in 🔝）— 核心调度
- `services/personal_vocab_service.py` — 个人词库（v3.x）
- `services/stats_service.py`（10 fan-in）— 掌握度统计

---

## Domain 2 — 真题模拟与评分 (`ielts-buddy-domain-exam-simulation`)

**业务目标**：还原 IELTS 真实考试体验，并给出可解释的分数。

**四技能服务**：
| 技能 | 服务 | 配套 |
| --- | --- | --- |
| Listening | `listening_service.py` | `listening_tts_service.py` |
| Reading | `exam_service.py`（共享） | — |
| Writing | `writing_service.py` | `llm_service.py` |
| Speaking | `speaking_service.py` | `whisper_service.py`, `speaking_grade_service.py` |

**会话模型**：
- `TestSession` — 单次考试会话（start_at, end_at, target_band）
- `ExamSession` — 真题套题（题目集合）
- `ExamQuestion` — 单题（按技能定义）

**LLM 评分链路**：
```
用户提交 (Writing/Speaking)
  ↓
writing_service.submit() / speaking_service.submit()
  ↓
llm_service.grade() — 调用 DeepSeek / OpenAI 兼容 API
  ↓
grading_service.parse_response() — 解析 4 维分数
  ↓
stats_service.update_mastery() — 反馈给学习循环
```

---

## Domain 3 — 备考资源广场 (`ielts-buddy-domain-prep-resources`) 🆕 v3.8

**业务目标**：聚合高质量第三方资源 + 提供阅读真题题库，减少用户找资料的时间。

**两大部分**：

### 3a. 资源广场（`prep_resource_service.py`）
**数据源**：管理员录入或脚本导入的外部资源（剑桥真题 PDF、YouTube 频道、Podcast RSS 等）。

**核心字段**：
- `title`, `source_type` (book / video / podcast / website)
- `skill` (listening / reading / writing / speaking)
- `band_range` (4-6, 6-7, 7+)
- `recommend_score`, `publish_date`
- `url`, `description`

**前端入口**：`/resources` 页面，含筛选（skill / source_type / band）与排序（最新 / 最推荐）。

### 3b. 阅读真题题库（`reading_practice_service.py` + `reading_question_generator.py`）
**数据源**：`scripts/seed_listening_questions.py` 类似的 seed 脚本（具体文件名待确认）。

**题型**：填空、判断、匹配、heading 匹配等 IELTS Reading 经典题型。

**答题闭环**：
```
浏览题目 (GET /reading/practice)
  ↓
开始会话 (POST /reading/sessions)
  ↓
提交答案 (POST /reading/sessions/{id}/submit)
  ↓
自动评分 (reading_practice_service.grade())
  ↓
统计反馈 (stats_service.update_reading_mastery())
```

### 3c. 听力练习（`listening_practice_service.py`）🆕 v3.8
与 3b 类似，音频驱动的听力训练，与 `listening_question_generator.py` 配对使用。

**v3.8 架构特点**：仅依赖 Persistence 层，不触碰 Core — 干净的增量边界。

---

## Domain 4 — 本地↔在线同步守护线程 (`ielts-buddy-domain-sync-daemon`)

**业务目标**：让用户在离线 / 弱网时也能用本地 SQLite 工作，回到在线时无缝合并到 MySQL。

**架构**：
```
本地写入 (SQLite)
  ↓
SyncWorker (services/sync.py: 793 行)
  ├─ SyncWorker (同步推送/拉取)
  ├─ SyncDaemonThread (守护线程，每 N 秒触发)
  └─ SyncWorkerAsync (asyncio 适配)
  ↓
冲突解决 (last-write-wins + user_id 隔离)
  ↓
增量同步到 MySQL
```

**配套 service**：`services/sync_service.py`（168 行，高层 `SyncService` 封装）。

**风险**：
- 多端并发时同一用户数据可能冲突（当前策略 LWW，无 CRDT）。
- `sync.py` 793 行较长，建议未来按 (push / pull / conflict) 拆分子模块。

---

## 跨域关系

```
vocab-learning  ←→  exam-simulation
       ↓                ↓
   stats_service ←—  report_service
       ↑                ↑
       └───  prep-resources (v3.8) ──┘
                ↑
                └──  reading 答题统计
                ↑
                └──  listening 答题统计

所有 domain 共享：persistence-layer + core-foundation
sync-daemon 横切所有 domain（后台搬运）
```