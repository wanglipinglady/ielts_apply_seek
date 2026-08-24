IELTS Buddy · Web 端操作手册
  在浏览器里把雅思考了

FastAPI + uvicorn 起的 Web MVP，覆盖仪表盘、词汇学习、模拟考试、AI 批改、口语对练、真·听力题库、备考资源广场、Reading 真题题库 28 个页面。

v3.8 · 适用于 `python -m ielts_buddy.web --port 8000` · 验证于 2026-08-23

## 目录

1. [适用场景与边界](#scope)
2. [启动与首次访问](#install)
3. [数据模式与同步](#mode)
4. [鉴权与账号](#auth)
5. [仪表盘与统计](#dashboard)
6. [词汇：浏览 / 测验 / 复习](#vocab)
7. [个人词库](#personal)
8. [模拟考试](#exam)
9. [AI 写作批改](#grade)
10. [学习计划](#plan)
11. [文章翻译](#articles)
12. [写作辅助](#writing)
13. [听力资源](#listening)
14. [口语话题](#speak)
15. [错词本](#mistakes)
16. [口语对练（v3.7 P1）](#speak-practice)
17. [真·听力题库（v3.7 P2）](#listen-practice)
18. [备考资源广场（v3.8 P3.1）](#resources)
19. [Reading 真题题库（v3.8 P3.2）](#reading-practice)
20. [机考打字 / 番茄钟 / 学习日历](#tools)
21. [报告中心](#report)
22. [运维：健康检查](#healthz)
23. [错误排查](#troubleshoot)
24. [环境变量清单](#env)

## 一、适用场景与边界

### 1.1 适用场景

- **无终端环境学习**：手机/平板浏览器也能用，体验比 CLI 友好。
- **录音 + Whisper 转写 + LLM 评分**：口语对练（v3.7 P1）—— CLI 端做不到的。
- **LLM 真·听力题库**：单题模式 + TTS 合成（v3.7 P2），按 Set/题型组合刷题。
- **B 站备考资源筛选**：按学科 / 水平段 / 来源过滤 32 条种子资源（v3.8 P3.1）。
- **Reading 真题**：5 种题型的真题答题 + T/F/NG 判分（v3.8 P3.2）。
- **番茄钟 + 学习日历 + 机考打字**：阶段 6 工具集。
- **注册 / 修改密码 / 找回密码**：CLI 没有的入口都在 Web。

### 1.2 不在范围

- 全局词库 JSON 浏览与维护——CLI 的 `ib vocab info`。
- 飞书 / 邮件 / GitHub Pages 一键推送——CLI 专用。
- 写自定义课程卡片——CLI 的 `ib course download`。

> **[数据共享]** Web 与 CLI **共享同一份业务数据**。Web 端的学习记录、复习进度、错词都会立刻在 CLI 同步到，反之亦然。

## 二、启动与首次访问

### 2.1 启动命令

```bash
# 默认 online 模式 + 自动降级
$ python -m ielts_buddy.web --port 8000

# 强制本地 SQLite
$ IELTS_BUDDY_WEB_DB_MODE=sqlite python -m ielts_buddy.web --port 8000

# 自定义 MySQL
$ IELTS_BUDDY_WEB_DB_URL='mysql+pymysql://user:pwd@host:3306/db?charset=utf8mb4' python -m ielts_buddy.web --port 8000

# 关闭后台 sync 线程(便于本地纯 SQLite 调试)
$ IELTS_BUDDY_SYNC_INTERVAL_SEC=0 python -m ielts_buddy.web --port 8000
```

### 2.2 首次访问

1. 浏览器访问 `http://127.0.0.1:8000`。
2. 若未登录，左上角会重定向到 `/login`。
3. 首次部署需在 MySQL 中预先创建账号；或由管理员在 Web 后台手工注册。
4. 登录成功后自动跳转到 `/dashboard`。

### 2.3 关键端点

| 端点 | 用途 |
| --- | --- |
| `/` | 首页（欢迎 + 登录/学习入口） |
| `/login` | 登录页 |
| `/register` | 注册页 |
| `/change-password` | 登录后修改密码 |
| `/forgot-password` | 忘记密码（邮件令牌重置） |
| `/dashboard` | 个人仪表盘（今日待复习 + 推荐） |
| `/healthz` | 健康检查（JSON） |

## 三、数据模式与同步

Web 端和 CLI 共享同一套 v3 数据层（详见 CLI 手册 §三）。三种模式由 `IELTS_BUDDY_WEB_DB_MODE` 环境变量切换：

| 模式 | WEB_DB_MODE 取值 | 行为 |
| --- | --- | --- |
| `online`（默认） | `online` / `mysql` | MySQL 主存 + SQLite 缓存；后台 sync 线程 |
| `fallback_sqlite` | 同上但 MySQL ping 失败时自动 | 本地 SQLite 落盘 + `pending_upload` 标记 |
| `sqlite` | `sqlite` / `memory` | 纯本地 SQLite，不上传 |

### 3.1 关键配置

```
# 默认 MySQL URL（src/ielts_buddy/repositories/mysql_repo.py 内置）
# mysql+pymysql://remote_user:Pass@666@118.190.148.121:3306/ietls_learn_online?charset=utf8mb4

# 覆盖：
export IELTS_BUDDY_WEB_DB_URL='mysql+pymysql://u:p@h:3306/db?charset=utf8mb4'

# SQLite 文件位置（默认 ~/.ielts-buddy/web_data.db）
export IELTS_BUDDY_WEB_SQLITE_PATH=/tmp/web_data.db

# Sync 间隔（秒，0 = 关闭）
export IELTS_BUDDY_SYNC_INTERVAL_SEC=30
```

### 3.2 边界

- Web 端改任何业务数据都会立即写主存 + SQLite 缓存。
- online 模式下 sync 线程后台跑；fallback 期间攒 `pending_upload`，恢复后 sync 线程自动推上去。
- Web 启动期会异步跑：listening 题库 seed、prep_resources seed、reading 题库 seed、speaking/listening 过期音频清理。这些任务失败会打 warn 但不阻塞启动。

## 四、鉴权与账号

> **路由**: `src/ielts_buddy/web/routers/auth.py`
> **页面**: /login / /register / /change-password / /forgot-password

### 4.1 使用场景

- 注册新账号：`/register`（仅暴露给管理员邀请或自注册模式）。
- 登录：`/login`，登录成功跳 `/dashboard`。
- 忘记密码：`/forgot-password` → 邮箱接收令牌 → 重置页。
- 修改密码：`/change-password`（需登录）。

### 4.2 鉴权机制

- JWT Bearer token（`Authorization: Bearer <token>`），通过 `get_current_user` 依赖注入。
- 登录可选 `?remember=1`，延长 refresh 有效期。
- 登出：表单提交到 `POST /api/auth/logout`（同时清 cookie 与服务端 session）。

### 4.3 边界

- 登录失败统一返回「认证失败」，不泄漏用户存在性。
- 注册是否开放看 `config.ALLOW_REGISTER`；默认关闭，管理员手动添加。
- Web 的 `auth` 子路由与 CLI 的 `ib auth` 共享同一份 `users` 表。

## 五、仪表盘与统计

> **页面**: `/dashboard` `/stats`
> **路由**: `web/routers/pages.py` `web/routers/stats.py`

### 5.1 /dashboard

**场景**：每日打卡入口。

**功能范围**：今日学习摘要 + 待复习数 + Band 进度条 + 快捷入口（去学/去复习/去统计）。

### 5.2 /stats

**场景**：复盘学习数据。

**功能范围**：今日/累计/正确率/Streak/每日趋势图/各 Band 进度条/学习历史。

### 5.3 边界

统计基于已记录的 learning_records 与 personal_vocab；未 `--record` 的纯展示不计。

## 六、词汇：浏览 / 测验 / 复习

> **页面**: `/vocab/browse` `/study/random` `/study/quiz` `/study/review`

### 6.1 /vocab/browse

4485 词大词库按 Band/Topic 分页浏览，支持中英双语搜索。

### 6.2 /study/random

随机抽 N 个词（默认 10）逐张展示，可勾选「记入学习记录」加入艾宾浩斯队列。

**步骤**：选 Band → 选数量 → 一张一张看 → 翻页到结束。

### 6.3 /study/quiz

英译中 / 中译英双向测验（基于 `?mode=` 切换），答完即时判分并写 learning_records。

**步骤**：选 Band → 选模式 → 答题 → 看正确率 → 错词自动入个人词库「错词本」。

### 6.4 /study/review

艾宾浩斯复习，按 0/1/2/4/7/15/30 天间隔到期抽取。

**边界**：与 CLI `ib vocab review` 共用同一复习池；任一端答对都会升级间隔。

## 七、个人词库

> **页面**: `/personal`

### 7.1 场景

收录真题或外刊里遇到的生词；支持自定义分类（写作 / 阅读 / 听力）；可纳入艾宾浩斯复习。

### 7.2 功能范围

- CRUD：增/删/改/查。
- 分类管理：增删改。
- 导入导出：CSV / JSON。
- 批量操作：移到分类 / 批量删除。

### 7.3 边界

个人词库对所有用户隔离（`user_id` 强绑）；与全局词库独立。

## 八、模拟考试

> **页面**: `/exam`
> **API**: `/api/exam/start` `/api/exam/submit` `/api/exam/history`

### 8.1 场景

考前全真模拟：限时答题、自动判分、出 Band 报告。

### 8.2 功能范围

- 选 Band（5/6/7/8）+ 题目数 + 时间限制（默认 60 分钟）。
- 倒计时 + 自动提交。
- 提交后出分报告（按四维系数转换）。
- 历史回看：`/exam` 页底部。

### 8.3 边界

- 计时器用前端 setInterval；网络断开期间页面挂起。
- 自动提交落库后不可撤销。

## 九、AI 写作批改

> **页面**: `/grade`
> **API**: `/api/grade/essay` `/api/grade/task1` `/api/grade/feedback` `/api/grade/diff`

### 9.1 场景

Task 1（图表）/ Task 2（议论文）写作后即时打分与改写建议。

### 9.2 功能范围

- 支持直接粘贴文本 / 文件上传。
- 四维评分（Task Response / Coherence / Lexical / Grammar）+ 改写建议。
- 改写前后 diff 高亮对比。
- 历史评分记录保存与回看。

### 9.3 步骤

1. 进入 `/grade`。
2. 选 Task 1 或 Task 2。
3. 粘贴 / 上传文本 → 提交。
4. 等待 5-15 秒拿到 LLM 反馈。
5. 点 **查看改写** 看 diff。

### 9.4 边界

- 最长文本 8000 字符，超出会被截断。
- LLM 凭证缺失：`/grade` 提交按钮显式禁用 + 提示。
- LLM 失败会自动 retry 1 次；失败返回 502 + 原因。

## 十、学习计划

> **页面**: `/plan`

### 10.1 场景

报名考试后设定目标 + 倒计时 + 每日新学建议。

### 10.2 功能范围

- 目标 Band / 每日新学量 / 考试日期。
- 倒计时 + 累计学习量 + 已完成百分比。
- Banner 自动提醒（与 CLI 共享 plan.json）。

## 十一、文章翻译

> **页面**: `/articles`

### 11.1 场景

读外刊/剑雅原文时做生词分析与翻译对照。

### 11.2 功能范围

- 粘贴文章 → 自动标出生词 + 释义 + 词频。
- 段段翻译对照（LLM）。
- 生词一键加入个人词库。

### 11.3 边界

翻译依赖 LLM；未配置时仅做生词高亮。

## 十二、写作辅助

> **页面**: `/write`

### 12.1 场景

浏览话题库、句型模板、同义替换、话题高分词汇。

### 12.2 边界

所有内容来自内置 JSON（`src/ielts_buddy/data/`），AI 化批改走 `/grade`。

## 十三、听力资源

> **页面**: `/listen`

### 13.1 场景

浏览 32 条精选听力资源（podcast / 视频 / 真题音频）。

### 13.2 边界

> **[边界]** 本页是 **静态资源浏览**。v3.7 P2 之后新增的「LLM 真·听力题库」在 `/listen/practice`，互不替代。

## 十四、口语话题

> **页面**: `/speak`

### 14.1 场景

Part 1/2/3 话题浏览与抽题。

### 14.2 边界

> **[边界]** 本页只做话题浏览，**不录音、不评分**。需要录音打分请走 `/speak/practice`。

## 十五、错词本

> **页面**: `/mistakes`

### 15.1 场景

所有答错过的词自动汇总，按错次排序。

### 15.2 功能范围

- 列表 / 搜索 / 按错次排序。
- 批量加入个人词库。
- 按时间窗筛选。

## 十六、口语对练（v3.7 P1）

> **页面**: `/speak/practice`
> **链路**: 录音 → Whisper 转写 → LLM 评分 → 错词回收

### 16.1 场景

录音回答一道题，系统自动转写 + 按雅思口语维度打分 + 错词回收。

### 16.2 步骤

1. 进入 `/speak/practice`，抽取一道 Part 1/2/3 题目。
2. 点麦克风 → 浏览器 MediaRecorder 录音 → 结束。
3. 前端 POST `/api/speaking/practice/submit`（webm → 服务端 ffmpeg 转 wav）。
4. Whisper 转写（Apple Silicon Core ML 加速）。
5. LLM 按 4 个口语维度评分（流利度 / 词汇 / 语法 / 发音）。
6. 评分结果 + 错词入库 + 自动归入「错词本」。

### 16.3 边界

- 录音上限 5 分钟，超过会被截断。
- 音频 7 天后自动清理（`purge_all_expired_audio` 在 web 启动期跑）。
- 未启用麦克风权限：浏览器原生提示，不报错。
- Whisper 失败回退到 fake 服务（仍走完打分链路，但转写为空）。

## 十七、真·听力题库（v3.7 P2）

> **页面**: `/listen/practice`
> **链路**: LLM 出题 → TTS 合成 → 单题播放/作答/判分

### 17.1 场景

按 Set/题型/难度组合刷题；填空、地图、配对、单选、多选5 种题型。

### 17.2 步骤

1. 进入 `/listen/practice`，选 Section（easy/medium/hard/academic）。
2. 选 Set（每 Set 4 道题）。
3. 点 **开始**：后台 LLM 出题 → TTS 合成（可能 5-15s 阻塞）。
4. 听音频 → 填答案 / 选答案 → 提交。
5. 系统按 T/F/NG 规则或精确匹配判分 + 给出 explanation。

### 17.3 边界

- LLM 出题失败：返回 502，按钮回到可点状态。
- TTS 合成失败：fallback 到 text-only 模式（标红 `无音频`）。
- Set 内题量固定 4 题，跨 Set 不重复。

## 十八、备考资源广场（v3.8 P3.1）

> **页面**: `/resources`
> **API**: `/api/resources/list` `/featured` `/recommendation` `/by-up` `/ups`

### 18.1 场景

B 站优质雅思方法论资源合集。按学科（听/读/说/写/综合）/ 水平段（0-5 / 5-6 / 6.5-7 / 7+）/ 来源（官方 / 机构 / 第三方已核验 / 第三方未核验）筛选 32 条种子资源；顶置精选按 skill 各取 1 条；按 UP 主浏览。

### 18.2 三个 Tab

- **浏览全部**：筛选 + 排序（推荐分 / 人工排序 / 发布时间）。
- **顶置精选**：4 个 skill 各 1 条顶置。
- **按 UP 主**：先选 UP 主，再看他/她的全部资源。

### 18.3 边界

- 数据来自 `src/ielts_buddy/data/prep_resources_seed.json`，启动期自动 seed。
- 每条卡片提供「▶ B 站观看」「📌 加入计划」「🎯 立即训练」三个按钮，后者由 `related_action_url` 字段驱动。
- 跨用户共享：资源表不进 SYNC_TABLES（所有用户看到同一份）。

## 十九、Reading 真题题库（v3.8 P3.2）

> **页面**: `/reading/practice`
> **API**: `/api/reading/list` `/{id}` `/by-set` `/submit` `/attempts`

### 19.1 场景

按 Section（easy/medium/hard/academic）+ Set 选择一组阅读真题（每 Set 包含 3-4 passages + 多种题型）。

### 19.2 5 种题型

- `tfng`：True / False / Not Given 三态判分。
- `multiple_choice`：单选/多选。
- `matching`：段落匹配。
- `summary`：摘要填空。
- `sentence_completion`：补全句子。

### 19.3 步骤

1. 进入 `/reading/practice`。
2. 选 Section → 选 Set。
3. 系统展示 passage + 题目 → 填答案 → 提交。
4. 系统判分 + 给出 explanation。
5. attempt 入 `reading_attempts` 表（个人）。

### 19.4 边界

- T/F/NG 的归一化在前端做，答题文本会被 trim + 大小写归一。
- passage 题库共享（不进 SYNC_TABLES）；attempts 个人隔离。

## 二十、机考打字 / 番茄钟 / 学习日历

### 20.1 /typing — 机考打字

> **场景**: 练习雅思机考打字速度

提供范文文本，实时统计 WPM / 正确率，支持限时模式（5/10/15 分钟）。所有 attempt 入 `typing_history`。

### 20.2 /pomodoro — 番茄钟

> **场景**: 聚焦 25 分钟工作 + 5 分钟休息

前端 setInterval 倒计时；结束后写 `focus_sessions`；与日历 / 统计联动。

### 20.3 /calendar — 学习日历

> **场景**: 每日学习热力图

展示当月 / 当年的学习密度；点击日期进入当日统计详情。

## 二十一、报告中心

> **页面**: `/report`

### 21.1 场景

汇总视图：今日计划 + 学习趋势 + 错词列表 + Band 进度。

所有数据来自 stats_service，与 CLI `ib report` 共享同一视图模型。

## 二十二、运维：健康检查

### 22.1 /healthz

返回 JSON：

```
{
  "status": "ok",
  "app": "ielts-buddy-web",
  "version": "0.1.0",
  "prefer_mode": "online",
  "db_mode": "online",
  "mysql_reachable": true,
  "sync": {
    "last_pull_at": "2026-08-22T17:43:56+00:00",
    "last_push_at": "2026-08-22T17:35:43+00:00",
    "last_error": null,
    "last_error_at": null
  },
  "pending_upload_personal_vocab": 0
}
```

### 22.2 推荐监控项

- `status == "ok"`
- `mysql_reachable == true`
- `pending_upload_*` < 阈值（突然飙升说明 sync 异常）
- `sync.last_error == null`

## 二十三、错误排查

| 现象 | 可能原因 | 排查 |
| --- | --- | --- |
| 页面 401 | JWT 过期 / 未登录 | 重新 `/login`；检查 `IELTS_BUDDY_JWT_SECRET` 是否被改 |
| 页面 500「业务容器未初始化」 | lifespan 没完成 | 查启动日志的 `sync_meta_error` 字段 |
| /resources 等页面报「加载失败: HTTP 500」 | 数据序列化错（日期 / 类型不匹配） | 升级到最新代码（已修复 publish_date 类型问题）；看启动期有没有表不存在警告 |
| /listen/practice 出题超时 | LLM 慢 / 凭证失效 | 看 LLM_API_KEY 配置；查看 LLM 服务可达性 |
| /speak/practice 提交 500 | ffmpeg 未装 / Whisper 失败 | `which ffmpeg`；`bash scripts/setup_whisper.sh` |
| 启动期 `Table 'xxx' doesn't exist` | MySQL 没初始化 | `MYSQL_PASSWORD='Pass@666' python scripts/migrate_v3_mysql_schema.py` |

## 二十四、环境变量清单

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `IELTS_BUDDY_ENV` | production | 设为 dev 时启用调试 + 默认密码 |
| `IELTS_BUDDY_JWT_SECRET` | 临时（重启失效） | JWT 签名密钥 |
| `ADMIN_RESET_TOKEN` | dev-admin-token | 管理员重置 token |
| `IELTS_BUDDY_WEB_DB_MODE` | online | 数据模式（online / sqlite） |
| `IELTS_BUDDY_WEB_DB_URL` | "" | 自定义 MySQL URL |
| `IELTS_BUDDY_WEB_SQLITE_PATH` | ~/.ielts-buddy/web_data.db | SQLite 文件路径 |
| `IELTS_BUDDY_SYNC_INTERVAL_SEC` | 30 | SyncWorker 间隔；0 = 关闭 |
| `IELTS_BUDDY_LISTENING_AUTO_SEED` | 1 | 启动期 listening 题库种子 |
| `IELTS_BUDDY_READING_AUTO_SEED` | 1 | 启动期 reading 题库种子 |
| `LLM_API_KEY` / `LLM_BASE_URL` | — | LLM 接入凭证（grade / speaking / listening / reading） |
| `SMTP_*` | — | 邮件重置密码 / 每日报告 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | — | 飞书多维表格同步 |

文档同步于 2026-08-23 · 项目版本 v3.8 · CLI 端操作手册见 `docs/manuals/cli-manual/cli-manual.html` · 项目地图见 `docs/project-maps/project-map/project-map.html`
