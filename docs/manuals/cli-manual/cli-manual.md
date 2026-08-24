IELTS Buddy · 命令行操作手册
  把雅思考进终端

17 个命令组、65 个子命令，覆盖词汇、复习、写作、口语、听力、批改、考试、报告、邮件、飞书、智能推荐全流程。

v3.8 · 适用于 `ib` CLI（基于 Click + Rich）· 验证于 2026-08-23

## 目录

1. [适用场景与边界](#scope)
2. [安装与首次启动](#install)
3. [数据模式：local / online / fallback_sqlite](#mode)
4. [全局行为：banner、登录、模式注入](#global)
5. [auth · 登录与身份](#auth)
6. [vocab · 词汇学习](#vocab)
7. [stats · 学习统计](#stats)
8. [plan · 学习计划](#plan)
9. [vocab review · 艾宾浩斯复习](#review)
10. [write · 写作辅助](#write)
11. [speak · 口语话题](#speak)
12. [listen · 听力资源](#listen)
13. [grade · AI 写作批改](#grade)
14. [exam · 模拟考试](#exam)
15. [report · 网页报告](#report)
16. [email · 每日邮件](#email)
17. [deploy · GitHub Pages 部署](#deploy)
18. [feishu · 飞书同步](#feishu)
19. [sync · 数据同步](#sync)
20. [db-status · 数据库健康](#db-status)
21. [recommend · 智能推荐](#recommend)
22. [course · 课程管理](#course)
23. [错误排查](#troubleshoot)
24. [配置文件与目录](#config)
25. [自动化与 daemon](#automation)

## 一、适用场景与边界

### 1.1 适用场景

- **通勤碎片学习**：用 `ib vocab random -n 5`、`ib vocab quiz` 在地铁上做 5-15 分钟的单词冲刺。
- **科学复习**：用 `ib vocab review` 跑艾宾浩斯间隔重复，0/1/2/4/7/15/30 天间隔。
- **AI 写作批改**：`ib grade essay "..."` 让 LLM 按雅思四个维度评分，`ib grade diff` 看改写对比。
- **学习数据复盘**：`ib stats trend` 看每日趋势，`ib stats progress` 看各 Band 掌握比例。
- **每日报告推送**：`ib email send` 或 `nohup ib sync daemon &` 跑后台同步。
- **多设备共享**：online 模式下两台机器登录同一账号 → 看到同一份数据。
- **离线场景**：断网时自动降级到 SQLite，恢复后自动回切。

### 1.2 不在范围

- 真实口语录音打分——CLI 端 `speak` 仅做抽题和话题浏览；录音 + Whisper 转写 + LLM 评分请走 Web 的「口语对练」(`/speak/practice`)。
- 真·听力题库 LLM 出题 + TTS——同样只在 Web 端 `/listen/practice` 暴露，CLI 的 `ib listen` 是静态资源浏览。
- 备考资源广场 B 站视频筛选——仅 Web 端 `/resources`。
- Reading 真题题库答题——仅 Web 端 `/reading/practice`。
- 注册/修改密码——走 Web 端，CLI 只负责登录身份。

> **[边界提醒]** CLI 与 Web **共享同一份业务数据**（MySQL 主存 + SQLite 缓存），但 CLI 不复用 LLM 出题、TTS、Whisper 这类依赖重型资源的服务。

## 二、安装与首次启动

### 2.1 系统要求

- Python 3.10+（已在 3.10.20 上验证）
- macOS / Linux（Linux 上 ffmpeg 需手动安装以支持 Whisper，CLI 端非必须）
- 磁盘 ≥ 200 MB（词库 + SQLite 缓存）
- MySQL 远程访问（如走 online 模式）

### 2.2 安装步骤

1. 克隆仓库并进入目录：
    ```
    cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
    ```

2. 创建虚拟环境并安装依赖：
    ```
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .
    ```

3. 首次运行会自动创建 `~/.ielts-buddy/` 目录、SQLite 缓存和默认配置：
    ```
    ib --version          # 确认安装
    ib auth login <username>   # 在线模式必须先登录
    ```

4. 检查数据库连通性：
    ```
    ib db-status show
    ```

### 2.3 配置文件位置

| 路径 | 用途 |
| --- | --- |
| `~/.ielts-buddy/config.toml` | 主配置（mode、daily_count、default_band、mysql_url） |
| `~/.ielts-buddy/session.json` | 当前登录的 username / user_id |
| `~/.ielts-buddy/ielts_buddy.db` | 本地 SQLite 缓存（CLI 与 Web 共享） |
| `~/.ielts-buddy/plan.json` | 学习计划 |
| `~/.ielts-buddy/sync_errors.log` | 同步异常日志（仅 online 模式） |
| `~/.ielts-buddy/backup_v3_<ts>.json` | 数据导出快照（`ib sync all` 产出） |

## 三、数据模式：local / online / fallback_sqlite

本项目数据层（v3 起）支持三种运行模式，三种状态由启动时探测决定、运行时自动切换。

| 模式 | 触发 | 读 | 写 | 适用场景 |
| --- | --- | --- | --- | --- |
| `online` | 默认 + MySQL 可达 | MySQL 主存 | MySQL 双写 + SQLite 缓存 | 多设备共享数据 |
| `fallback_sqlite` | MySQL 临时不可达 | 本地 SQLite | 本地 SQLite + 标 `pending_upload` | 断网期间继续学习，恢复后自动回切 |
| `local` | `--mode local` 或 `IELTS_BUDDY_MODE=local` | 本地 SQLite | 本地 SQLite（不上传） | 纯本地、不希望同步 |

### 3.1 模式优先级（从高到低）

```
1. --mode 参数（CLI 启动时）
2. $IELTS_BUDDY_MODE 环境变量
3. ~/.ielts-buddy/config.toml 的 [general].mode
4. 默认 local
```

### 3.2 三种启动方式示例

```bash
# 默认（online + 自动降级）
$ ib vocab random -n 5

# 强制本地模式
$ ib --mode local vocab random

# 通过环境变量
$ IELTS_BUDDY_MODE=local ib vocab quiz

# 自定义 MySQL
$ IELTS_BUDDY_WEB_DB_URL='mysql+pymysql://user:pwd@host:3306/db?charset=utf8mb4' ib sync all
```

### 3.3 边界

- **未登录 + online**：`SystemExit(1)` 阻断（保护 MySQL 中 `user_id=1` 系统种子用户不被污染）。
- **未登录 + local**：软提示 banner 后继续，数据默认落 `user_id=1`。
- **online → fallback_sqlite**：自动生效，写标 `pending_upload`，MySQL 恢复后 `ib db-status sync-now` 或后台 daemon 会推上去。

## 四、全局行为

### 4.1 Banner 与当前用户提示

每个子命令执行前，CLI 会在 stderr 打印一行 dim 风格的提示：

```bash
-- 当前用户: wanglipingresume (id=2, mode=online) --
```

在以下场景会被关闭或硬阻断：

- `IELTS_BUDDY_NO_BANNER=1`：CI 与老测试用，关掉 banner。
- `auth` 子命令自身负责显示身份，跳过 banner。
- **online 模式未登录**：banner 直接升为红字错误并 `SystemExit(1)`。

### 4.2 每日学习提醒

设置过 `ib plan set` 的账号，每次执行会看到一行：

```bash
-- 待复习: 18 | 建议新学: 12 --
```

读取 `~/.ielts-buddy/plan.json`，解析失败则静默跳过，不影响命令本身。

### 4.3 `--mode` 的进程级副作用

W10 之后，`--mode` 会临时写入 `os.environ['IELTS_BUDDY_MODE']`，子命令执行完后由 result_callback 还原。所以同一进程连发多个 `ib --mode X` 互不污染。

## 五、auth · 登录与身份

> **文件**: `src/ielts_buddy/commands/auth.py`
> **子命令**: login / whoami / logout

### 5.1 使用场景

- online 模式首次启动：必须先登录，否则所有写操作被拒。
- 切换账号：logout 后再 login。
- 脚本里需要知道当前用户是谁：`ib auth whoami`。

### 5.2 功能范围

登录基于统一 `users` 表（CLI 与 Web 共用），用户名需预先由管理员在 MySQL 创建。登录成功后写 `session.json`，后续命令从该文件读取身份。

### 5.3 边界

- CLI **不提供注册**——去 Web 端 `/register`。
- CLI **不提供修改密码**——去 Web 端 `/change-password` 或 `/forgot-password`。
- 登录失败原因只打印「认证失败」，不泄漏具体原因。

### 5.4 步骤

1. `ib auth login <username>` → 提示输入密码。
2. 成功后写入 `~/.ielts-buddy/session.json`。
3. `ib auth whoami` 验证身份。
4. `ib auth logout` 清除本地 session。

## 六、vocab · 词汇学习

> **文件**: `src/ielts_buddy/commands/vocab.py`
> **子命令**: random / quiz / review / search / list / info / add / edit / delete / list-personal / category / import / export
> **词库**: 4485 词（5 Band 拆 JSON）+ 526 词精选

### 6.1 random — 随机抽词

**场景**：通勤刷词、晨间热身。

**功能范围**：从指定 Band 抽 N 个词，展示音标 / 中文释义 / 例句 / 搭配 / 词源。可选 `--record` 自动落学习记录。

**边界**：不带 `--record` 时不写库，纯展示；带 `--record` 会触发艾宾浩斯复习排程（首次学习 → 1 天后）。

```bash
$ ib vocab random -n 5
$ ib vocab random -n 10 --band 7 --record
```

### 6.2 quiz — 测验（英译中 / 中译英）

**场景**：主动产出训练、考前自测。

**功能范围**：双向测验模式：`en2zh` 默认 / `zh2en` 反向。答对/答错自动记录。

**边界**：测验结果同时影响艾宾浩斯间隔。

```bash
$ ib vocab quiz -n 10
$ ib vocab quiz --mode zh2en -n 20 --band 7
```

### 6.3 review — 艾宾浩斯复习

详见 [§九](#review)。

### 6.4 search — 模糊搜索

**场景**：记不清拼写、按词根/中文释义反查。

**功能范围**：同时搜单词本体、释义、主题字段。返回前 20 条匹配。

```bash
$ ib vocab search "opportunity"
$ ib vocab search "机会"
```

### 6.5 list — 按 Band/Topic 分页浏览

```bash
$ ib vocab list --band 7 --topic environment --page 1 --per-page 20
```

### 6.6 info — 词库总览

各级别数量 + 主题分布柱状图。

### 6.7 个人词库：add / edit / delete / list-personal / category / import / export

**场景**：收录真题里遇到的生词、按自定义分类管理。

**边界**：个人词库与全局词库隔离，可与艾宾浩斯复习联动。

```bash
$ ib vocab add opportunity --meaning "机会" --band 7 --pos n
$ ib vocab list-personal --category 写作
$ ib vocab category create "阅读真题" --description "剑雅 16-19"
$ ib vocab export --category 写作 --fmt csv --output writing_words.csv
```

## 七、stats · 学习统计

> **文件**: `src/ielts_buddy/commands/stats.py`
> **子命令**: show / trend / progress / history

### 7.1 show — 概览

**场景**：每日打卡复盘、自我评估。

**输出**：今日新学 / 总学习量 / 总正确率 / streak 天数 / 个人词库分类概览。

### 7.2 trend — 每日趋势

默认 30 天，ASCII 柱状图直观展示每日学习量。

```bash
$ ib stats trend --days 14
```

### 7.3 progress — Band 进度

各 Band（5/6/7/8/9）掌握比例进度条。

### 7.4 history — 学习日志

每日答题明细，可指定天数。

### 7.5 边界

所有统计基于已记录到库的学习记录；纯 `vocab random` 不带 `--record` 时不算数。

## 八、plan · 学习计划

> **文件**: `src/ielts_buddy/commands/plan.py`
> **子命令**: show / set

### 8.1 set — 设置计划

**场景**：报名考试后第一次启动。

```bash
$ ib plan set --band 7 --daily 30
$ ib plan set --exam-date 2026-12-15
```

### 8.2 show — 展示

今日已学 / 计划量 / 考试倒计时 / 当前累计。

### 8.3 边界

- 考试日期格式 `YYYY-MM-DD`，非法会被拒绝。
- daily=0 时视为「不设目标」，banner 不再提示新学建议。

## 九、vocab review · 艾宾浩斯复习

vocab 子命令组中 `review` 是核心复习入口，与 random / quiz 共用同一数据池。

复习调度间隔：`0 → 1 → 2 → 4 → 7 → 15 → 30` 天，答对自动升级、答错自动降级。

### 9.1 使用步骤

1. `ib vocab review` 或 `ib vocab review -n 50`。
2. 系统抽取所有到期未复习的单词；按 Band 优先级排序。
3. 每题答完立即反馈 + 记录。
4. 结束打印本轮正确率与下一批到期日。

### 9.2 边界

- 仅复习已 `--record` 入库的词。
- 答错会立刻被重新加入 0 天复习池。
- online 模式下复习记录立即同步 MySQL，本地 SQLite 与 MySQL 都会保留。

## 十、write · 写作辅助

> **文件**: `src/ielts_buddy/commands/write.py`
> **子命令**: topics / templates / synonyms / vocab

### 10.1 topics — 浏览话题库

```bash
$ ib write topics
$ ib write topics --category technology
```

### 10.2 templates — 句型模板

```bash
$ ib write templates --type introduction
$ ib write templates --type conclusion
```

### 10.3 synonyms — 同义替换

```bash
$ ib write synonyms important
```

### 10.4 vocab — 话题高分词汇

```bash
$ ib write vocab "人工智能"
```

### 10.5 边界

所有数据来自内置 JSON（`src/ielts_buddy/data/`），不会随用户偏好更新。AI 化批改走 `grade`。

## 十一、speak · 口语话题

> **文件**: `src/ielts_buddy/commands/speak.py`
> **子命令**: topics / practice / vocab

### 11.1 topics — 浏览 Part 1/2/3 话题

```bash
$ ib speak topics --part 2
```

### 11.2 practice — 随机抽题练习

```bash
$ ib speak practice --part 2
```

### 11.3 vocab — 话题关键词汇

```bash
$ ib speak vocab "旅行"
```

### 11.4 边界

> **[边界]** 本命令组是**话题浏览与抽题**，不录音、不评分。需要录音打分请走 Web 的 `/speak/practice`（v3.7 P1 口语对练全链路：录音 → Whisper → LLM 评分 → 错词回收）。

## 十二、listen · 听力资源

> **文件**: `src/ielts_buddy/commands/listen.py`
> **子命令**: resources / detail / dictation

### 12.1 resources — 浏览资源

```bash
$ ib listen resources
$ ib listen resources --type podcast
```

### 12.2 detail — 单条详情

```bash
$ ib listen detail 3
```

### 12.3 dictation — 听写模式

```bash
$ ib listen dictation -n 20 -b 7
```

### 12.4 边界

> **[边界]** 本组仅消费 `src/ielts_buddy/data/listening_resources.json` 中的静态条目。v3.7 P2 之后新增的「真·听力题库（LLM 出题 + TTS 合成 + 单题模式）」只在 Web 端 `/listen/practice` 暴露。

## 十三、grade · AI 写作批改

> **文件**: `src/ielts_buddy/commands/grade.py`
> **子命令**: essay / file / history / diff
> **依赖**: LLM 服务（环境变量配置，详见 `docs/online_local_技术详解.md`）

### 13.1 essay — Task 2 批改（命令行直接给文本）

```bash
$ ib grade essay "Some people argue that technology makes people lazy. Discuss both views."
```

### 13.2 file — 从文件读

```bash
$ ib grade file ./essay.txt --topic technology
```

### 13.3 history — 历史反馈

```bash
$ ib grade history --limit 10
```

### 13.4 diff — 改写对比

```bash
$ ib grade diff 3
```

### 13.5 评分维度

- Task Response（任务回应）
- Coherence & Cohesion（连贯与衔接）
- Lexical Resource（词汇资源）
- Grammatical Range & Accuracy（语法多样性与准确性）

### 13.6 边界

- essay 文本最长 8000 字符，超出会被截断。
- LLM 调用失败会 retry 1 次，仍失败则报错退出；不会污染 history。
- 未配置 LLM 时会显式提示 `LLM_API_KEY 未设置`。

## 十四、exam · 模拟考试

> **文件**: `src/ielts_buddy/commands/exam.py`
> **子命令**: start / history

### 14.1 start — 开始限时模拟

```bash
$ ib exam start
$ ib exam start --time 30 --count 40 --band 7
```

### 14.2 history — 考试历史

```bash
$ ib exam history --count 20
```

### 14.3 边界

模拟考试答题纯本地行为，不依赖 LLM；完成后即时出分（按 Band 系数转换）。

## 十五、report · 网页报告

> **文件**: `src/ielts_buddy/commands/report.py`
> **子命令**: daily / build / serve

### 15.1 daily — 生成今日报告

```bash
$ ib report daily
$ ib report daily --date 2026-08-22
```

### 15.2 build — 全量构建

生成所有历史报告 + 首页 `index.html`，准备 GitHub Pages 部署。

### 15.3 serve — 本地预览

```bash
$ ib report serve --port 8080
```

### 15.4 边界

报告是只读快照，不写回数据库。

## 十六、email · 每日邮件

> **文件**: `src/ielts_buddy/commands/email.py`
> **子命令**: preview / send

### 16.1 preview

```bash
$ ib email preview --count 10
```

### 16.2 send

```bash
$ ib email send --count 10
```

### 16.3 边界

- SMTP 配置走环境变量（`SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / EMAIL_FROM / EMAIL_TO`）。
- 发送失败会被记录到 `~/.ielts-buddy/email_errors.log`。

## 十七、deploy · GitHub Pages 部署

> **文件**: `src/ielts_buddy/commands/deploy.py`
> **子命令**: setup / push / status

### 17.1 setup — 一次性配置

```bash
$ ib deploy setup https://github.com/<user>/<repo>.git
```

### 17.2 push — 推送报告

```bash
$ ib deploy push
```

### 17.3 status — 部署状态

```bash
$ ib deploy status
```

### 17.4 边界

需 `git` 在 PATH 中；首次 setup 后写入 `~/.ielts-buddy/deploy.json`。

## 十八、feishu · 飞书同步

> **文件**: `src/ielts_buddy/commands/feishu.py`
> **子命令**: sync / stats / setup / schema

### 18.1 setup — 初始化飞书多维表格

```bash
$ ib feishu setup
```

### 18.2 sync — 同步词汇

```bash
$ ib feishu sync --app-token <token> --table-id <id>
```

### 18.3 stats — 同步统计

```bash
$ ib feishu stats
```

### 18.4 schema — 查看表结构

### 18.5 边界

- 依赖飞书 OpenAPI 凭证（`FEISHU_APP_ID / FEISHU_APP_SECRET`）。
- --app-token / --table-id 可省略，从 `~/.ielts-buddy/feishu.json` 读取。

## 十九、sync · 数据同步

> **文件**: `src/ielts_buddy/commands/sync.py`
> **子命令**: vocab / records / stats / all / daemon

### 19.1 all — 一次性同步全部

```bash
$ ib sync all
```

把本地 SQLite 中 `pending_upload` 的记录推到 MySQL，再拉一次远端增量更新。输出 `backup_v3_<ts>.json` 快照。

### 19.2 子集同步

```bash
$ ib sync vocab
$ ib sync records
$ ib sync stats
```

### 19.3 daemon — 后台长驻

```bash
# 每 60 秒跑一次 sync all
$ nohup ib sync daemon --interval 60 > ~/.ielts-buddy/sync.log 2>&1 &
```

### 19.4 边界

- online 模式下推 / 拉是双向；fallback_sqlite 模式下只推本地未上传条目。
- 冲突解决：`updated_at` 较新者赢（last-write-wins）。

## 二十、db-status · 数据库健康

> **文件**: `src/ielts_buddy/commands/db_status.py`
> **子命令**: show / sync-now

### 20.1 show — 状态总览

```bash
$ ib db-status show
DB Mode: online
MySQL 可达: ✓
上次同步:
  pull: 2026-08-22T17:43:56+00:00
  push: 2026-08-22T17:35:43+00:00
pending_upload 计数:
  personal_vocab       0
  learning_records     0
  ...
```

### 20.2 sync-now — 立即同步一次

```bash
$ ib db-status sync-now
```

### 20.3 边界

仅在 online 模式下有意义；local 模式直接报「无远端」。

## 二十一、recommend · 智能推荐

> **文件**: `src/ielts_buddy/commands/recommend.py`
> **子命令**: show / weak / new

### 21.1 show — 今日推荐

```bash
$ ib recommend
```

### 21.2 weak — 薄弱环节

```bash
$ ib recommend weak --count 5
```

### 21.3 new — 新学推荐

```bash
$ ib recommend new --count 10 --band 7
```

### 21.4 边界

需要足够的学习记录（≥ 20 条）才有稳定推荐；冷启动时给保守建议。

## 二十二、course · 课程管理

> **文件**: `src/ielts_buddy/commands/course.py`
> **子命令**: list / show / download / ls / info

### 22.1 list — 列出课程

```bash
$ ib course list
```

### 22.2 show — 浏览课程内容

```bash
$ ib course show "太空探索"
```

### 22.3 download — 下载课程资源

```bash
$ ib course download "太空探索" --path ./courses
```

### 22.4 info — 元信息

### 22.5 边界

课程内容是知识卡片 `courses/<topic>/content.md`，不是学习数据；不参与 MySQL 同步。

## 二十三、错误排查

| 现象 | 可能原因 | 排查 |
| --- | --- | --- |
| online 模式启动即退 1 | 未登录 | `ib auth login <username>` |
| 认证失败 | 密码错 / 用户不在 MySQL users 表 | 去 Web `/login` 用同一套凭证验证；管理员创建用户 |
| MySQL 不可达 → 自动 fallback | 网络/DNS/凭证 | `ib db-status show` 看 `mysql_reachable`；检查 `IELTS_BUDDY_WEB_DB_URL` |
| grade essay 报 LLM 凭证缺失 | 未配置 LLM_API_KEY | export LLM_API_KEY / LLM_BASE_URL 等 |
| vocab search 0 结果 | 词不在 4485 词库 | 尝试 `ib vocab search` 反向（用中文查）；或 `ib vocab add` 入个人词库 |
| 邮件发送失败 | SMTP 配置缺失 | 检查 SMTP_* 环境变量；查看 `~/.ielts-buddy/email_errors.log` |
| 飞书 sync 401 | app_id / app_secret 失效 | `ib feishu setup` 重新配置 |

> **[重要]** 所有写入在 fallback_sqlite 模式下都打 `pending_upload` 标记；MySQL 恢复后不会自动推上去，**必须** 跑 `ib db-status sync-now` 或启 daemon。

## 二十四、配置文件与目录

### 24.1 config.toml 模板

```
[general]
daily_count = 50
default_band = 7
mode = "online"

[database]
mysql_url = ""
default_username = "anonymous"
user_id = 1
```

字段说明：

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `general.mode` | online | 默认数据模式 |
| `general.daily_count` | 50 | 每日新学目标（不写库时仅展示） |
| `general.default_band` | 7 | 默认词库 Band |
| `database.mysql_url` | "" | 留空走内置默认；非空则覆盖 |
| `database.default_username` | anonymous | 未登录时显示名 |
| `database.user_id` | 1 | 未登录时落库 user_id |

### 24.2 关键目录

```
~/.ielts-buddy/
├── config.toml                 # 主配置
├── session.json                # 当前登录身份
├── ielts_buddy.db              # SQLite 缓存(CLI 与 Web 共享)
├── plan.json                   # 学习计划
├── sync_errors.log             # 同步异常
├── email_errors.log            # 邮件发送异常
├── feishu.json                 # 飞书凭证
├── deploy.json                 # GitHub Pages 部署配置
└── backup_v3_<timestamp>.json # 数据快照
```

## 二十五、自动化与 daemon

### 25.1 sync daemon

```bash
$ nohup ib sync daemon --interval 60 > ~/.ielts-buddy/sync.log 2>&1 &
```

后台每 60 秒跑一次双向同步，适合长期挂机的开发机或 NAS。停掉用 `pkill -f 'ib sync daemon'`。

### 25.2 每日 9 点 + 21 点推送（cron）

```
# /etc/crontab 或 crontab -e
0  9 * * *  /path/to/.venv/bin/ib email send   --count 20
0 21 * * *  /path/to/.venv/bin/ib feishu sync
0 21 * * *  /path/to/.venv/bin/ib deploy push
```

### 25.3 边界

- daemon 是常驻线程，**不是**轮询守护进程；进程退出即停。
- 多实例冲突由 `sync_meta.last_push_at` + `updated_at` last-write-wins 自动兜底。
- cron 任务必须在 `.venv` 的 Python 解释器下运行，否则 `ib` 命令找不到。

文档同步于 2026-08-23 · 项目版本 v3.8 · Web 端操作手册见 `docs/manuals/web-manual/web-manual.html` · 项目地图见 `docs/project-maps/project-map/project-map.html`
