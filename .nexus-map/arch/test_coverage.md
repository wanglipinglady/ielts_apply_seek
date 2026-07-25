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
