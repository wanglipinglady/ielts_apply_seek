# 系统边界（Systems）

> generated_by: nexus-mapper v2
> verified_at: 2026-08-23
> provenance: AST-backed (Python 198/198 files)

本文件描述 5 个核心 System 与 4 个 Domain 的边界、入口、依赖与已知风险。

---

## System 1 — Web Application (`ielts-buddy-web-application`)

**入口**：`src/ielts_buddy/web/main.py` (953 行，19 变更 🔴 high risk)

**职责**：所有面向用户的 Web 交互 — 模板渲染、HTTP 路由、鉴权、JSON API。

**代码地图**：
```
src/ielts_buddy/web/
├── main.py                       ← FastAPI app + 启动钩子 (953 行)
├── config.py                     ← Web 专属配置 (8 变更)
├── __main__.py                   ← `python -m ielts_buddy.web` 入口
├── auth/                         ← 鉴权子包 (repository, deps, security, service)
├── routers/                      ← 16 个路由模块 (auth, articles, exam, listening, ...)
├── services.py                   ← Web 专用服务聚合
├── llm_service.py                ← LLM 调用封装
├── whisper_service.py            ← 音频转写
├── lookup_client.py              ← 词典查询
├── translation_client.py         ← 翻译 API
├── stats_service.py              ← 实时统计 API
├── listening_tts_service.py      ← TTS 合成
├── calendar_service.py           ← 日历事件
├── speaking_grade_service.py     ← 口语评分
├── templates/                    ← Jinja2 模板（含 base.html, 28 子页）
├── static/                       ← 前端静态资源（CSS/JS）
└── tools/                        ← 维护工具 (reset_password 等)
```

**对外依赖**：`ielts-buddy-service-layer`、`ielts-buddy-persistence-layer`、`ielts-buddy-core-foundation`。

**风险**：与 `web/templates/base.html` 耦合度 **1.00**（13 次共同提交）— 改 main.py 几乎必动模板。

---

## System 2 — CLI Application (`ielts-buddy-cli-application`)

**入口**：`src/ielts_buddy/cli.py` (Click group, 7 变更) + `src/ielts_buddy/__main__.py`

**职责**：面向运维 / 重度用户的命令行入口；17 命令组，65 子命令。

**命令组清单**（按 `commands/` 目录）：
| 命令组 | 文件 | 主要功能 |
| --- | --- | --- |
| `auth` | auth.py | 登录 / 退出 / whoami |
| `vocab` | vocab.py | 词库浏览 / 抽查 / 测验 (7 子命令) |
| `stats` | stats.py | 学习统计 |
| `plan` | plan.py | 计划生成 |
| `write` | write.py | 写作提交 |
| `speak` | speak.py | 口语录制 |
| `listen` | listen.py | 听力训练 |
| `grade` | grade.py | LLM 评分 |
| `exam` | exam.py | 真题模拟 |
| `report` | report.py | 报告生成 |
| `email` | email.py | 邮件发送 |
| `deploy` | deploy.py | 部署辅助 |
| `feishu` | feishu.py | 飞书集成 |
| `recommend` | recommend.py | 资源推荐 |
| `course` | course.py | 课程导入 |
| `sync` | sync.py | 跨端同步 |
| `db_status` | db_status.py | 数据库健康检查 |

**对外依赖**：与 Web 相同的 Service + Persistence 层。

**注意**：CLI 与 Web 共享 Service 层；不在 CLI 中放业务规则。

---

## System 3 — Persistence Layer (`ielts-buddy-persistence-layer`)

**入口**：`src/ielts_buddy/repositories/__init__.py` (24 模块 fan-in 🔝)

**职责**：数据持久化的统一抽象。通过 Python `Protocol` 实现多后端 + 自动回退。

**子模块**：
| 文件 | 职责 | 变更 |
| --- | --- | --- |
| `__init__.py` | 导出 `FallbackContainer` + 仓储工厂 | 9 |
| `sqlite_repo.py` | SQLite 本地实现 | **16 🔴** |
| `mysql_repo.py` | MySQL 8 在线实现 | 11 |
| `fallback_repo.py` | SQLite 优先 + MySQL 回退混合模式 | 6 |
| `core/repository.py` | Protocol 定义 | 7 |

**核心模式**：
```python
# core/repository.py 定义 Repository Protocol
# sqlite_repo.py / mysql_repo.py 实现 Protocol
# repositories/__init__.py 通过 FallbackContainer 在运行时选择实现
```

**风险**：
- `sqlite_repo.py` 与 `mysql_repo.py` 是"双胞胎"，改一个必改另一个。
- 与 `scripts/init_mysql.sql` (10 变更) + `scripts/migrate_v3_mysql_schema.py` (7 变更) 强耦合 — schema 变更要三处同步。

---

## System 4 — Service Layer (`ielts-buddy-service-layer`)

**入口**：`src/ielts_buddy/services/__init__.py`

**职责**：所有业务规则实现 — Web / CLI 都不直接调用 Repository，必须经 Service。

**领域服务清单**（按重要性排序）：

| 服务 | 关键职责 |
| --- | --- |
| `vocab_service.py` | 词库学习闭环 (25 fan-in 🔝) |
| `review_service.py` | 复习调度 (15 fan-in) |
| `stats_service.py` | 统计聚合 (10 fan-in) |
| `personal_vocab_service.py` | 个人词库 (v3.x) |
| `exam_service.py` | 真题会话 |
| `writing_service.py` / `speaking_service.py` | 单技能服务 |
| `prep_resource_service.py` | **v3.8** 备考资源广场 |
| `reading_practice_service.py` | **v3.8** 阅读真题题库 |
| `listening_practice_service.py` | **v3.8** 听力练习 |
| `speaking_practice_service.py` | **v3.8** 口语练习 |
| `reading_question_generator.py` | **v3.8** 阅读题目生成器 |
| `listening_question_generator.py` | **v3.8** 听力题目生成器 |
| `sync.py` | 同步 worker / 守护线程 (793 行) |
| `sync_service.py` | 同步 service 封装 (168 行) |
| `auth_service.py`, `grading_service.py`, `recommend_service.py`, `mistake_service.py`, `plan_service.py`, `report_service.py`, `course_service.py`, `feishu_service.py`, `email_service.py`, `deploy_service.py`, `diff_service.py`, `db_health.py` | 支撑服务 |

**注意 `sync.py` vs `sync_service.py`**：
- `sync.py` — 低层 worker（793 行，含 `SyncWorker`、`SyncDaemonThread`、`SyncWorkerAsync`）
- `sync_service.py` — 高层 service 封装（168 行，`SyncService`）
- 二者是分层关系，非重名。

---

## System 5 — Core Foundation (`ielts-buddy-core-foundation`)

**入口**：`src/ielts_buddy/core/` + `src/ielts_buddy/web/auth/`

**职责**：枢纽层 — Pydantic 模型、运行时配置、Web 鉴权。

**核心模块**：
| 模块 | fan-in | 关键内容 |
| --- | --- | --- |
| `core/models.py` | **46 🔝** | `Word`, `LearningRecord`, `TestSession`, `DailySummary`, `StudyPlan`, `ExamQuestion`, `ExamSession` ... |
| `web/auth/repository.py` | **40 🔝** | Web 鉴权仓储（密码哈希、token 签发） |
| `core/config.py` | 27 | Pydantic Settings |
| `web/auth/deps.py` | 25 | FastAPI Depends 鉴权 |
| `web/auth/security.py` | 9 | JWT / passlib |

**风险**：改 `core/models.py` 影响全仓 — 任何字段变更必须同步两后端 + 所有引用方。

---

## Domain 概览

详细语义见 `concepts/domains.md`。摘要：

- `ielts-buddy-domain-vocab-learning` — 词汇闭环（摄入→复习→统计）
- `ielts-buddy-domain-exam-simulation` — 四技能真题 + LLM 评分
- `ielts-buddy-domain-prep-resources` — **v3.8 新增**，资源广场 + 阅读题库
- `ielts-buddy-domain-sync-daemon` — 本地→在线后台同步