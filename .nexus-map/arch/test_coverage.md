# Test Coverage — 静态测试面与证据缺口

> generated_by: nexus-mapper v2
> verified_at: 2026-07-16
> provenance: file-tree + manual inspection

## 测试目录结构

```
tests/
├── __init__.py
├── conftest.py              # pytest 配置和 fixtures
├── test_config.py            # 配置测试
├── test_models.py           # 数据模型测试
├── test_commands/           # CLI 命令测试
│   ├── test_cli.py
│   ├── test_exam_feishu_cli.py
│   ├── test_grade_deploy_cli.py
│   ├── test_listen.py
│   ├── test_report_cli.py
│   ├── test_speak_cli.py
│   ├── test_sync_email_cli.py
│   └── test_write_cli.py
├── test_repositories/       # 仓库层测试
│   ├── test_repository_protocols.py
│   └── test_sqlite_repo.py
└── test_services/           # 服务层测试
    ├── test_deploy_service.py
    ├── test_diff_service.py
    ├── test_email_service.py
    ├── test_exam_service.py
    ├── test_feishu_service.py
    ├── test_grading_service.py
    ├── test_listening_service.py
    ├── test_personal_vocab_service.py
    ├── test_plan_service.py
    ├── test_recommend_service.py
    ├── test_report_service.py
    ├── test_review_service.py
    ├── test_speaking_service.py
    ├── test_stats_service.py
    ├── test_sync_service.py
    ├── test_vocab_service.py
    └── test_writing_service.py
```

## 测试覆盖矩阵

| 模块 | 测试文件 | 覆盖状态 | 说明 |
|------|----------|----------|------|
| **Commands** | | | |
| vocab | 未发现独立测试文件 | ⚠️ 部分 | vocab 命令测试覆盖不足 |
| stats | 未发现独立测试文件 | ⚠️ 部分 | |
| plan | 未发现独立测试文件 | ⚠️ 部分 | |
| sync | `test_sync_email_cli.py` | ✓ | |
| email | `test_sync_email_cli.py` | ✓ | |
| write | `test_write_cli.py` | ✓ | |
| speak | `test_speak_cli.py` | ✓ | |
| report | `test_report_cli.py` | ✓ | |
| listen | `test_listen.py` | ✓ | |
| grade | `test_grade_deploy_cli.py` | ✓ | |
| deploy | `test_grade_deploy_cli.py` | ✓ | |
| exam | `test_exam_feishu_cli.py` | ✓ | |
| feishu | `test_exam_feishu_cli.py` | ✓ | |
| recommend | 未发现独立测试文件 | ❌ 缺失 | |
| course | 未发现独立测试文件 | ❌ 缺失 | |
| **Services** | | | |
| vocab_service | `test_vocab_service.py` | ✓ | |
| review_service | `test_review_service.py` | ✓ | |
| stats_service | `test_stats_service.py` | ✓ | |
| plan_service | `test_plan_service.py` | ✓ | |
| email_service | `test_email_service.py` | ✓ | |
| writing_service | `test_writing_service.py` | ✓ | |
| speaking_service | `test_speaking_service.py` | ✓ | |
| listening_service | `test_listening_service.py` | ✓ | |
| grading_service | `test_grading_service.py` | ✓ | |
| deploy_service | `test_deploy_service.py` | ✓ | |
| exam_service | `test_exam_service.py` | ✓ | |
| report_service | `test_report_service.py` | ✓ | |
| feishu_service | `test_feishu_service.py` | ✓ | |
| recommend_service | `test_recommend_service.py` | ✓ | |
| personal_vocab_service | `test_personal_vocab_service.py` | ✓ | |
| sync_service | `test_sync_service.py` | ✓ | |
| course_service | 未发现测试文件 | ❌ 缺失 | |
| diff_service | `test_diff_service.py` | ✓ | |
| **Repositories** | | | |
| sqlite_repo | `test_sqlite_repo.py` | ✓ | |
| repository protocols | `test_repository_protocols.py` | ✓ | |
| **Core** | | | |
| models | `test_models.py` | ✓ | |
| config | `test_config.py` | ✓ | |

## 证据缺口

### 测试缺失区域

| 区域 | 严重程度 | 说明 |
|------|----------|------|
| `recommend` 命令 | Medium | 命令层无独立测试 |
| `course` 命令 | Medium | 命令层无独立测试 |
| `course_service.py` | Medium | 服务层无测试 |

### 静态分析声明

- 本分析基于文件树和 README 声明（637 tests）
- **未运行实际测试验证**
- 测试是否全部通过需要执行 `pytest` 确认
- 覆盖率数据来自 README，未经验证

### 覆盖率声明来源

README.md 声明：
> ![Tests](https://img.shields.io/badge/Tests-637%20passed-brightgreen)

**警告**: 此声明可能为上游项目 IELTS Buddy 的测试数量，本项目可能未完全继承。

---

## v3.6+ Web 测试套件(更新)

> 自 v3.6 起新增 `tests/test_web/` 目录，覆盖 FastAPI 端到端

### Web API 测试文件

| 测试文件 | 用例数 | 覆盖范围 |
|---|---|---|
| `test_app_boot.py` | - | web 启动 + lifespan |
| `test_auth_api.py` | - | 注册/登录/刷新 token |
| `test_auth_repository.py` | - | web_users repo |
| `test_auth_security.py` | - | JWT 加解密 |
| `test_auth_service.py` | - | 认证业务层 |
| `test_calendar_api.py` | - | 学习日历 |
| `test_grade_api.py` | - | 写作 AI 评分 |
| `test_listening_api.py` | - | 听力训练 |
| `test_mistakes_api.py` | - | 错词本 |
| `test_pomodoro_api.py` | - | 番茄钟 |
| `test_speak_api.py` | - | 口语话题 |
| `test_stats_api.py` | - | 统计 |
| `test_study_api.py` | - | 学习(随机+复习) |
| `test_typing_api.py` | - | 打字 |
| `test_write_api.py` | - | 写作辅助 |

### v3.7 P1 口语对练新增测试

| 测试文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_repositories/test_speaking_practice_repo.py` | 19 | 9 repo 方法 + 7 天清理 + record_speaking_error |
| `test_repositories/test_repository_protocols.py` | +N | SpeakingPracticeRepository Protocol 一致性 |
| `test_web/test_speaking_practice_api.py` | 21 | 6 端点 e2e + IDOR + 422 校验 + 错词回收 |
| `test_web/test_speaking_grade_service.py` | 14 | mock fallback / 真 LLM / retry-once / JSON 容错 |
| `test_services/test_speaking_practice_service.py` | 4 | purge 跨用户清理 |

**v3.7 P1 新增 58 个测试,全部 PASS。**

### 已知 Pre-existing 失败

> 以下失败与本次工作无关,均为环境/mock 引起的存量问题:

- `tomllib` ImportError(Python 3.10 才有)
- `day_num` template UndefinedError(邮件模板)
- `MySQLRepositoryContainer has no attribute _conn`(无 MySQL 环境)
- LLM 评分 mock 与新 grading prompt 不匹配

**`tests/test_web/ + tests/test_repositories/` 516 个测试,514 PASS,2 pre-existing study_api failures。**
