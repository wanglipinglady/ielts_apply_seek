# 📚 ietls_apply_seek 是在开源项目IELTS Buddy的基础上，针对自己的需求进行改造，一边学习一边应用，希望有个通用工具，也服务习惯界面化的用户

> **在你写代码的地方，顺便把雅思考了。**

IELTS Buddy 是一款面向程序员的雅思备考 CLI 工具，将词汇学习、写作辅助、口语练习和科学复习整合到终端中。
# 1. 进入项目目录
cd d:\0000-maven\self-program\ielts_apply_seek

# 2. 安装/更新依赖
pip install -e .

# 3. 启动 Web 服务
python -m ielts_buddy.web --port 8000

# 4. 浏览器访问
# http://127.0.0.1:8000
![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![Tests](https://img.shields.io/badge/Tests-637%20passed-brightgreen)
![Vocab](https://img.shields.io/badge/Vocab-4485%20words-orange)
![Commands](https://img.shields.io/badge/CLI-46%20commands-purple)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ 功能一览

| 模块 | 命令 | 说明 |
|------|------|------|
| 📖 词汇学习 | `ib vocab random` | 随机抽词，展示音标/释义/例句/搭配/词源 |
| 🔍 词库搜索 | `ib vocab search` | 按单词/释义/主题模糊搜索 |
| 📋 词库浏览 | `ib vocab list` | 按 Band/Topic 分页浏览 |
| 📊 词库概览 | `ib vocab info` | 各级别数量 + 主题分布柱状图 |
| ✏️ 英译中测验 | `ib vocab quiz` | 答对/答错自动记录 |
| 🔄 中译英测验 | `ib vocab quiz --mode zh2en` | 双向测验，提升主动产出 |
| 🧠 艾宾浩斯复习 | `ib vocab review` | 间隔重复 (0/1/2/4/7/15/30天) |
| 📈 学习统计 | `ib stats show` | 今日/总计/正确率/记忆等级分布 |
| 📉 趋势分析 | `ib stats trend` | 每日学习量 ASCII 柱状图 |
| 🎯 Band 进度 | `ib stats progress` | 各 Band 掌握比例进度条 |
| 📅 学习计划 | `ib plan show/set` | 目标 Band + 每日学习量 + 考试倒计时 |
| 🔗 数据导出 | `ib sync all` | 导出学习数据为 JSON |
| 📧 每日邮件 | `ib email send` | HTML 学习报告邮件 |
| ✍️ 写作辅助 | `ib write topics/templates/synonyms/vocab` | 话题库 + 句型 + 同义替换 |
| 🎤 口语练习 | `ib speak topics/practice/vocab` | Part 1/2/3 话题 + 抽题练习 |
| 🌐 网页报告 | `ib report build` | 学习日历热力图 + GitHub Pages |
| 🎧 听力资源 | `ib listen resources/dictation` | 32 个精选资源 + 听写模式 |
| ✍️ AI 批改 | `ib grade essay/task1/feedback` | AI 写作评分 + 详细反馈 |
| 📝 模拟考试 | `ib exam start/history` | 限时测验 + 历史记录 |
| 🚀 自动部署 | `ib deploy push/status/setup` | GitHub Pages 一键部署 |
| 🧠 智能推荐 | `ib recommend` | 根据学习数据智能推荐下一步 |
| 📋 飞书同步 | `ib feishu sync/check/export/status` | 飞书多维表格双向同步 |

## 🚀 快速开始

```bash
# 安装
git clone https://github.com/Rory-X/ielts-buddy.git
cd ielts-buddy
pip install -e .

# 开始学习
ib vocab random -n 5          # 随机学 5 个词
ib vocab quiz -n 10           # 英译中测验 10 题
ib vocab quiz --mode zh2en    # 中译英测验
ib vocab review               # 复习到期单词
ib stats show                 # 查看学习统计
ib recommend                  # 智能推荐下一步
```

## 🌐 v3 多端同步（MySQL 主存 + SQLite 离线）

> 2026-08 起，Web/CLI 数据自动共享到云端 MySQL；离线时本地 SQLite 兜底。

### 模式说明

| 模式 | 触发条件 | 行为 |
|---|---|---|
| `online`（默认） | 启动期能 ping 通 MySQL | 读写全走 MySQL；本地 SQLite 仅作缓存 |
| `fallback_sqlite` | MySQL 临时不可达 | 读写本地 SQLite + 标 `pending_upload`；MySQL 恢复后自动回切 |
| `sqlite` | 强制 `IELTS_BUDDY_WEB_DB_MODE=sqlite` 或 `IELTS_BUDDY_MODE=local` | 仅本地 SQLite，不推送 |

### Web 启动

```bash
# 默认（online + 自动降级）
python -m ielts_buddy.web --port 8000

# 强制本地
IELTS_BUDDY_WEB_DB_MODE=sqlite python -m ielts_buddy.web --port 8000

# 自定义 MySQL（覆盖默认 118.190.148.121:3306）
IELTS_BUDDY_WEB_DB_URL='mysql+pymysql://user:pwd@host:3306/db?charset=utf8mb4' \
    python -m ielts_buddy.web --port 8000

# 关闭后台同步（写本地后不推 MySQL）
IELTS_BUDDY_SYNC_INTERVAL_SEC=0 python -m ielts_buddy.web --port 8000
```

启动后访问：
- `http://127.0.0.1:8000/healthz` —— 后端状态 + 同步水位 + pending_upload 计数
- `http://127.0.0.1:8000/login` —— 登录（用统一 users 表里的账号）

### CLI 启动

```bash
# 1. 在线模式登录（必须在 users 表里存在）
ib auth login wanglipingresume

# 2. 查看同步状态
ib db-status show
#   DB Mode: online
#   MySQL 可达: ✓
#   上次同步:
#     pull: 2026-08-22T17:43:56+00:00
#     push: 2026-08-22T17:35:43+00:00
#   pending_upload 计数：
#     personal_vocab       0
#     learning_records     0
#     ...

# 3. 立即同步一次（推本地 + 拉远端）
ib db-status sync-now

# 4. 长驻后台 daemon（适合 nohup 后台跑）
nohup ib sync daemon --interval 60 > ~/.ielts-buddy/sync.log 2>&1 &
```

### 配置文件位置

- CLI 主配置：`~/.ielts-buddy/config.toml`（`[general].mode`）
- Web 环境变量：项目根目录 `.env`
- 数据文件：`~/.ielts-buddy/ielts_buddy.db`（CLI 与 Web 共享）
- 同步错误日志：`~/.ielts-buddy/sync_errors.log`
- 备份：`~/.ielts-buddy/backup_v3_<时间戳>.json`

### 数据共享原理

```
任意一台机器登录同一账号 → 看到同一份数据
       │
       │  每 30s 后台增量同步
       ▼
  ┌─────────────────────────┐
  │  MySQL (云端主存)        │ ← 所有设备最终都到这里
  └─────────────────────────┘
       ▲           ▲
       │           │
   ┌───┴──┐    ┌───┴──┐
   │ 设备 A│    │ 设备 B│   ← 各有自己的 SQLite 缓存
   └──────┘    └──────┘
```

冲突解决：`updated_at` 时间戳比较，新者赢（last-write-wins）。

### 首次部署（已有老版本数据）

```bash
# 1. 升级 MySQL schema（articles 表 + 各表 updated_at/sync_status）
MYSQL_PASSWORD='xxx' python scripts/migrate_v3_mysql_schema.py

# 2. 合并 web_users → users
MYSQL_PASSWORD='xxx' python scripts/migrate_v3_users_merge.py

# 3. 重启 web/CLI，自动跑 SQLite _MIGRATIONS（幂等）
```

详细设计见 [`docs/v3_mysql_fallback_design.md`](docs/v3_mysql_fallback_design.md)，
实施复盘见 [`docs/v3_retrospective.md`](docs/v3_retrospective.md)。

## 📖 词库

内置 **4485 个** 雅思核心词汇（大词库），覆盖 Band 5-9：

| Band | 数量 | 特征 |
|------|------|------|
| Band 5 | 1227 | 基础高频词 |
| Band 6 | 1127 | 进阶常用词 |
| Band 7 | 1076 | 高分核心词 |
| Band 8 | 745 | 学术高阶词 |
| Band 9 | 310 | 低频冲刺词 |

另有 **526 词精选词库**（`--curated`），每个词含完整搭配、同义词和词源分析。

## 🧠 艾宾浩斯复习

基于遗忘曲线的智能复习调度：

```
首次学习 → 1天后 → 2天后 → 4天后 → 7天后 → 15天后 → 30天后
```

每次复习根据答对/答错自动调整间隔，直到单词进入长期记忆。

## ✍️ 写作辅助

```bash
ib write topics                        # 浏览所有话题
ib write topics --category technology  # 按类别筛选
ib write templates --type introduction # 查看开头句型
ib write synonyms important            # 查同义替换
ib write vocab "人工智能"               # 话题高分词汇
```

## ✍️ AI 写作批改

```bash
ib grade essay "Your essay text here..."  # Task 2 批改
ib grade task1 "Task 1 response..."       # Task 1 批改
ib grade feedback                         # 查看历史反馈
```

AI 评分维度：Task Response、Coherence & Cohesion、Lexical Resource、Grammatical Range & Accuracy。

## 📝 模拟考试

```bash
ib exam start              # 开始限时模拟考试
ib exam start --time 30    # 30分钟限时
ib exam history            # 查看考试历史
```

## 🎤 口语练习

```bash
ib speak topics --part 2     # 浏览 Part 2 话题
ib speak practice --part 2   # 随机抽题练习
ib speak vocab "旅行"         # 话题关键词汇
```

## 🌐 网页学习报告

```bash
ib report daily                    # 生成今天的报告 HTML
ib report build                    # 生成全部报告 + 首页
ib report serve                    # 本地预览

ib deploy push                     # 部署到 GitHub Pages
ib deploy status                   # 查看部署状态
```

📊 在线报告: https://rory-x.github.io/ielts-buddy/

## 🎧 听力资源

```bash
ib listen resources                  # 浏览 32 个资源
ib listen resources --type podcast   # 按类型筛选
ib listen dictation -n 20 -b 7      # 听写模式
```

## 📈 统计面板

```bash
ib stats show      # 概览（今日/累计/正确率/streak）
ib stats trend     # 每日学习趋势
ib stats progress  # Band 掌握进度条
ib stats history   # 学习日志
```

## 🧠 智能推荐

```bash
ib recommend         # 查看今日推荐
```

根据学习数据自动分析薄弱项、待复习数、掌握率，给出个性化学习建议。

## 📋 飞书同步

```bash
ib feishu sync       # 同步学习数据到飞书多维表格
ib feishu check      # 检查待同步数据
ib feishu export     # 导出为 Bitable 格式
ib feishu status     # 同步状态
```

## 📧 每日邮件 & 自动化推送

```bash
ib email preview   # 预览邮件内容
ib email send      # 发送学习报告
```

### 自动化流程

- **每天 9:00** — 自动发送学习邮件 + 飞书推送今日计划
- **每天 21:00** — 飞书推送学习总结 + 自动部署报告到 GitHub Pages
- **每周一 9:00** — 飞书推送周报

## 📅 学习计划

```bash
ib plan set --band 7 --daily 30               # 设置目标
ib plan set --exam-date 2026-06-01            # 设置考试日期
ib plan show                                   # 查看今日计划
```

## ⚡ 性能

| 操作 | 耗时 |
|------|------|
| 词库加载 | < 500ms |
| 模糊搜索 | < 100ms |
| 精确查找 | < 10ms |

首次加载后自动建立 SQLite 缓存，后续启动更快。

## 🛠 技术栈

- **CLI**: [Click](https://click.palletsprojects.com/)
- **美化**: [Rich](https://github.com/Textualize/rich)
- **数据模型**: [Pydantic](https://docs.pydantic.dev/)
- **存储**: SQLite + JSON
- **模板**: Jinja2
- **测试**: pytest (637 tests)

## 📁 项目结构

```
src/ielts_buddy/
├── cli.py                  # CLI 入口 (14 命令组, 46 子命令)
├── commands/               # 命令层
│   ├── vocab.py            # 词汇 (random/quiz/review/search/list/info)
│   ├── stats.py            # 统计 (show/trend/progress/history)
│   ├── plan.py             # 计划 (show/set)
│   ├── sync.py             # 同步 (vocab/records/stats/all)
│   ├── email.py            # 邮件 (preview/send)
│   ├── write.py            # 写作 (topics/templates/synonyms/vocab)
│   ├── speak.py            # 口语 (topics/practice/vocab)
│   ├── report.py           # 报告 (daily/build/serve)
│   ├── listen.py           # 听力 (resources/detail/dictation)
│   ├── grade.py            # 批改 (essay/task1/feedback)
│   ├── deploy.py           # 部署 (push/status/setup)
│   ├── exam.py             # 考试 (start/history)
│   ├── feishu.py           # 飞书 (sync/check/export/status)
│   └── recommend.py        # 推荐 (智能学习推荐)
├── services/               # 服务层
├── data/                   # 词库 + 资源数据
└── templates/              # HTML 模板
```

## 🧪 测试

```bash
pytest                           # 运行全部 637 个测试
pytest --cov=ielts_buddy         # 覆盖率报告
```

## 📋 版本历史

- **v3.0.0** (2026-08-23) — **MySQL 主存 + SQLite 自动降级 + 双向同步**
  - Web/CLI 共用统一 `users` 表，跨设备共享数据
  - MySQL 不可达时自动降级到本地 SQLite，恢复后自动同步
  - last-write-wins 冲突解决
  - 详见 [`docs/v3_mysql_fallback_design.md`](docs/v3_mysql_fallback_design.md)
- **v1.2.0** (2026-03-07) — 智能推荐 + 飞书同步 + 自动化推送
- **v1.1.0** (2026-03-06) — AI 批改 + 模拟考试 + GitHub Pages 部署
- **v1.0.0** (2026-03-06) — 14 命令组 MVP 完整版
- v0.6.0 — 网页学习报告 + 听力资源
- v0.5.0 — 大词库 4485 词 + 性能优化
- v0.4.0 — 写作辅助 + 口语练习
- v0.3.0 — 飞书同步 + 邮件升级
- v0.2.0 — 词库扩充 + 中译英 + 学习计划
- v0.1.0 — MVP 核心闭环

## 📄 License

MIT
