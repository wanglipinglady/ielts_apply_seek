# 测试覆盖（Test Coverage — 静态）

> generated_by: nexus-mapper v2
> verified_at: 2026-08-23
> provenance: AST-backed (Python 198/198 files); 仅统计文件数与行数，**未实际运行 pytest**

---

## 测试面总览

| 测试包 | 模块数 | Class 数 | 行数 |
| --- | ---: | ---: | ---: |
| `tests/` (顶层) | 5 | 12 | 943 |
| `tests/test_commands/` | 13 | 53 | 2,193 |
| `tests/test_repositories/` | 11 | 52 | 3,695 |
| `tests/test_services/` | 29 | 171 | 8,820 |
| `tests/test_web/` | 27 | 71 | 8,561 |
| **合计** | **86** | **359** | **24,212** |

> 行数与代码行（58,399）比 ≈ **1 : 2.4**，对个人项目属于较高覆盖。

---

## 映射到被测系统

| 被测系统 | 测试模块数 | 主要测试文件 |
| --- | ---: | --- |
| `ielts-buddy-web-application` | 27 | `tests/test_web/*`（含 `test_listening_startup_seed`, `test_prep_resource_api`, `test_reading_practice_api`, `test_stats_api` 等） |
| `ielts-buddy-cli-application` | 13 | `tests/test_commands/*`（auth, vocab, recommend, course, exam 等） |
| `ielts-buddy-persistence-layer` | 11 | `tests/test_repositories/*`（含 `test_sqlite_repo`, `test_mysql_repo`, `test_focus_session_repository`, `test_typing_repository`, `test_speaking_practice_repo`） |
| `ielts-buddy-service-layer` | 29 | `tests/test_services/*`（最大测试包，171 个 TestX class） |
| `ielts-buddy-core-foundation` | 5 | `tests/test_config.py`（顶层测试包中的 `TestConfig`, `TestGetMode`, `TestGetMysqlUrl`） |

---

## v3.8 新功能的测试覆盖

| 新功能 | 服务 | 测试文件 |
| --- | --- | --- |
| 备考资源广场 API | `prep_resource_service` | `tests/test_web/test_prep_resource_api.py` |
| 阅读真题题库 API | `reading_practice_service` | `tests/test_web/test_reading_practice_api.py` |
| 阅读启动种子 | `reading_practice_service` | `tests/test_web/test_reading_startup_seed.py` |
| 听力启动种子 | `listening_practice_service` | `tests/test_web/test_listening_startup_seed.py` |
| 统计 API | `stats_service` | `tests/test_web/test_stats_api.py` |
| 个人词库 | `personal_vocab_service` | `tests/test_services/test_user_id_resolution.py` 等 |

**v3.8 改动均同步增加了 Web API 测试** — 高质量的增量交付。

---

## evidence gap（缺口）

| 缺口 | 影响 | 建议 |
| --- | --- | --- |
| **AST 阶段未运行 pytest** | 静态覆盖率≠实际通过率 | 在 CI 跑 `pytest --cov=src/ielts_buddy`，下次产物补充覆盖率数字 |
| **3 个非 Python 文件未解析** | `.github/workflows/ci.yml`, `scripts/setup_whisper.sh` 等未纳入 AST | 边缘脚本，对核心结论无影响 |
| **3311 Function 节点被截断** | 函数级覆盖未知 | 用 `--max-nodes 200` 重跑可补齐，或直接 `pytest --collect-only -q` 拿精确函数计数 |
| **集成测试与端到端测试未单独标注** | 可能存在跨系统测试但归到了子包 | 建议在 README 标注 e2e 测试触发方式 |

---

## 测试运行入口（推断）

基于 `pyproject.toml` 与文件结构推断（**未实测**）：

```bash
# 安装依赖
pip install -e ".[test]"

# 跑全部
pytest

# 单系统测试
pytest tests/test_web/                  # Web API
pytest tests/test_commands/             # CLI
pytest tests/test_repositories/         # 持久化
pytest tests/test_services/             # Service 层
```

> 实际命令以 `pyproject.toml` 与 `pytest.ini` 配置为准。