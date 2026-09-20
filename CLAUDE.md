# CLAUDE.md — ielts-buddy 项目指南

## 项目概述
IELTS 雅思词汇学习 CLI 工具，支持随机抽词、英译中测验、艾宾浩斯间隔重复复习和学习统计。

## 技术栈
- Python 3.10+, Click CLI, Rich (终端美化), Pydantic (数据模型)
- SQLite (复习记录存储)
- 安装: `pip install -e .` → CLI 命令 `ib` 或 `ielts`

## 目录结构
```
src/ielts_buddy/
├── __init__.py       # 版本号
├── cli.py            # Click group 入口，注册 vocab + stats
├── core/
│   ├── config.py     # 配置管理 (~/.ib/, 环境变量 IELTS_BUDDY_HOME)
│   └── models.py     # Pydantic 数据模型 (Word, ReviewRecord, Stats)
├── data/
│   ├── vocab_band5.json  # Band 5 词库 (131词)
│   ├── vocab_band6.json  # Band 6 词库 (80词)
│   └── vocab_band7.json  # Band 7 词库 (115词)
├── services/
│   ├── vocab_service.py   # 词库加载/随机抽词/搜索/按band筛选
│   ├── review_service.py  # 艾宾浩斯复习 (间隔: 0/1/2/4/7/15/30天, SQLite)
│   └── stats_service.py   # 学习统计 (今日/总计/正确率/等级分布)
└── commands/
    ├── vocab.py      # vocab random/quiz/review 命令
    └── stats.py      # stats show 命令

tests/
├── conftest.py             # 测试 fixtures (tmp_path, mock数据)
├── test_models.py          # 数据模型测试 (25个)
├── test_config.py          # 配置测试 (18个)
└── test_services/
    ├── test_vocab_service.py   # 词库服务测试 (30个)
    ├── test_review_service.py  # 复习服务测试 (29个)
    └── test_stats_service.py   # 统计服务测试 (9个)
└── test_commands/
    └── test_cli.py             # CLI命令测试 (17个)
```

## 关键命令
```bash
ib vocab random [-n 5] [-b 7]   # 随机抽词，支持按band筛选
ib vocab quiz [-n 10] [-b 7]    # 英译中测验，自动记录到SQLite
ib vocab review [-n 20]         # 复习到期单词（艾宾浩斯算法）
ib stats show                   # 学习统计面板
ib --version                    # 版本信息
```

## 测试
```bash
pytest                         # 运行全部 133 个测试
pytest --cov=ielts_buddy       # 覆盖率报告 (92%)
pytest tests/test_services/    # 只跑服务层测试
```

## 数据存储
- 词库: `src/ielts_buddy/data/vocab_band*.json` (JSON, 随包分发)
- 用户数据: `~/.ib/` (默认) 或 `$IELTS_BUDDY_HOME/`
  - `reviews.db` — SQLite, 复习记录

## 词库格式 (JSON)
```json
{
  "word": "contribute",
  "phonetic": "/kənˈtrɪbjuːt/",
  "pos": "v.",
  "definition": "贡献，促成",
  "example": {"en": "Many factors contribute...", "zh": "很多因素..."},
  "collocations": ["contribute to", "contribute significantly"],
  "synonyms": ["add to", "assist", "donate"],
  "etymology": "con- (一起) + tribute (给予) → 贡献",
  "topic": "society"
}
```

## 注意事项
- config.py 中 DB_PATH/APP_DIR 是延迟求值（函数调用），不在模块导入时固化
- quiz 命令的 KeyboardInterrupt 已处理（不会 crash）
- 词库没有重复词，所有字段 100% 完整
- Rich 表格在窄终端可能换行，建议 ≥80 列

## 未来迭代方向 (参考 docs/PRD.md)
- Phase 2: 听力练习、写作模板、口语话题
- Phase 3: AI 批改、模拟考试
- 更多词库 (Band 8+, 专题词库)
- 每日学习计划/提醒

---

## 多端共享 service 层契约（铁律，2026-08-24 加入）

> 本项目存在 **3 个调用同一份后端的端**：CLI v3.8 + Web v3.8 + 微信小程序「屠鸭智取」。
> 三端共用 `src/ielts_buddy/services/` 下的所有 service 函数 + `ietls_learn_online` MySQL 数据库。
> 任何对 service 层 / schema / 公共工具的改动，**同时影响三端**。

### 5 条铁律

1. **service 层是单一真相源**——CLI / Web / 小程序共用同一份代码，禁止单独 fork
2. **改 service 函数签名 = 同时改三端**——必须用 `grep` 列出所有调用方（`grep -rn "from ielts_buddy.services" src/ielts_buddy/`）并同步更新
3. **MySQL schema 改动必须用 alembic 迁移**——禁止手改字段；新增字段用 `ALTER TABLE ... ADD COLUMN`，禁止 `DROP COLUMN` 老字段
4. **新增字段默认可选**——不破坏老调用（用 `Optional[T] = None` + 默认值）
### 5. **每个公共 API 都要有契约测试**——锁住 schema；CI 流水线强制跑

### 监控铁律（异常处理，2026-08-24 加）

> 本项目 8 周赛事期间依赖"事件驱动型"异常通知，**不靠时间轮询**。所有通知走 `ielts_buddy.monitoring.notifier` 模块。

#### 3 级严重度

| 级别 | 触发条件 | 通知通道 | 你的介入 |
|------|----------|----------|----------|
| **🟢 P3 INFO** | 已知小问题 / 数据有偏差 | 仅写死信日志 | ❌ 不介入 |
| **🟡 P2 WARNING** | 重试 1 次仍失败 / 异常类型不明 | **邮件** | ❓ 工作时间看 |
| **🔴 P1 CRITICAL** | 服务挂了 / 数据污染 / 涉及钱 / 未成年人 | **微信服务通知 + 邮件** | ✅ **立即介入** |

#### 5 条铁律

1. **不靠时间轮询**——只在异常 + AI 不能自愈时触发
2. **5 分钟静默期**——同一 signature 的 P2 只发 1 次，避免刷屏
3. **AI 自愈优先**——8 类已知异常（LLM 超时 / Whisper 失败 / MySQL 抖动 / 等）自动重试，不通知
4. **不可自愈立即升级**——suppress() 达到 max_retries 自动升级到 P1
5. **死信队列**——所有通知统一写 `~/.ielts-buddy/.dead_letter.log`，AI 自查

#### 接入示例

```python
from ielts_buddy.monitoring.notifier import notify, suppress, Severity

# 简单通知
notify("服务挂了", Severity.P1_CRITICAL, context={"task": "speaking_score"})

# AI 自愈循环
for attempt in range(3):
    try:
        result = call_llm()
        break
    except Exception as e:
        if not suppress(e, Severity.P2_WARNING, "llm_timeout"):
            raise  # 已升级到 P1 + 通知过你
```

#### 自愈签名清单（自动重试不通知）

| signature | 含义 | 自愈策略 |
|-----------|------|----------|
| `llm_timeout` | LLM 调用超时 | 自动切备用模型（混元 → DeepSeek） |
| `llm_rate_limit` | LLM 限流 | 自动退避 |
| `whisper_crash` | Whisper 失败 | 自动切 CPU 模式 |
| `mysql_timeout` | MySQL 慢 | 自动触发 fallback_sqlite |
| `network_blip` | 网络抖动 | 自动重试 |
| `ci_flaky_test` | CI 偶发失败 | 自动 rebase 重跑 |
| `subscription_api_throttle` | 微信订阅消息限流 | 退避 + 队列 |
| `user_token_expired` | 用户 token 过期 | 自动 refresh_token |

#### 升级签名清单（达到 max_retries 即升级到 P1）

| signature | 含义 |
|-----------|------|
| `service_crashed` | 服务进程崩溃 |
| `data_corrupted` | 数据被污染 |
| `permission_denied` | 权限被拒（合规） |
| `payment_error` | 涉及钱的错误 |
| `minors_data_leaked` | 未成年人数据泄露 |
| `wechat_audit_blocked` | 微信审核被封 |
| `unknown_exception` | 未知异常（最危险） |

#### CI 流水线

- `tests/test_monitoring/`（16 个测试）覆盖：分级 / 静默 / 自愈 / 死信 / 健康快照
- `.github/workflows/ci.yml` 加 `monitoring-tests` job（先于全量测试跑）
- `.github/workflows/weekly-recheck.yml` 每周一跑：健康快照 + 风险 recheck

---

### 路由层约定（按"端"分组，但共享 service）

```
src/ielts_buddy/web/routers/
├── auth.py            ← ← Web + 小程序共用
├── study.py           ← ← Web + 小程序共用
├── wechat.py          ← ← 【小程序专用】新增的路由，前缀 /api/wx/
└── ...
```

- 小程序路由统一加 `/api/wx/` 前缀，与 Web 端 `/api/` 区分
- service 函数禁止加"端"判断（不允许 `if request_source == "wechat"` 这种逻辑）
- 路由层做"端到端编排"，service 层做"业务逻辑"

### 提交前 checklist（任何人改 service / schema 必须跑）

```
□ 我改的是 service / schema / 公共函数吗？
  → YES：下面 5 项都要做
  →  NO：跳过
□ 改了哪几个 service 函数？列出调用方清单
□ CLI 端是否调用了？ → 跑 CLI smoke test（ib vocab random -n 5）
□ Web 端是否调用了？ → 跑 web 端 curl 测试
□ 小程序端是否调用了？ → 跑小程序真机测试
□ 契约测试是否通过？ → pytest tests/test_contracts/ -v
□ MySQL schema 是否改了？
  → YES：必须用 alembic 生成迁移脚本 + 在本地 SQLite 也跑一遍
  →  NO：跳过
```

### 契约测试位置

- `tests/test_contracts/` ← 新增目录
- 现有 `tests/test_web/` ← 已有，按 router 拆分
- 现有 `tests/test_services/` ← 已有，按 service 拆分
- 现有 `tests/test_commands/` ← 已有，按 CLI 命令拆分

跑契约测试：

```bash
pytest tests/test_contracts/ -v
```

### 大赛期间版本号策略（2026-08-24 ~ 2026-10-17）

| 端 | 版本 | 状态 |
|----|------|------|
| CLI | v3.8 | ✅ 已发布，**冻结**，只修 bug |
| Web | v3.8 | ✅ 已发布，**冻结**，只修 bug |
| 小程序 | v1.0 (2026-09-22 计划发布) | 🆕 新开发 |

> 大赛期间 **CLI v3.8 + Web v3.8 不加新功能**——所有新功能只走小程序。
> 这条简化了契约管理：W2–W8 改的任何代码，老 CLI / Web 都不感知（除非动了 service 层）。

---

## 相关文件
- PRD: docs/PRD.md (923行)
- 开发计划: docs/PLAN.md (761行)
- 测试报告: docs/TEST_REPORT.md
- 每日邮件: /home/node/clawd/scripts/daily-ielts-mail.py
