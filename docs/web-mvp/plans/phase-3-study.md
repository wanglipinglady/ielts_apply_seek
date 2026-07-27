# 阶段 3：随机学习 + 复习（Web 端复用 VocabService / ReviewService）

## 目标
实现 MVP 剩余两个核心页面：
- `/study/random`：从词库随机抽词，用户点击"认识 / 不认识"，记录到 learning_records
- `/study/review`：从待复习队列抽词，同样记录

两页都用 HTMX 局部刷新"答完显示下一题"，避免整页刷新带来的体验割裂。

## 改动文件

### 新增
- `src/ielts_buddy/web/routers/study.py` —— `/study/random` `/study/review` 两个页面 + HTMX 局部端点
- `src/ielts_buddy/web/templates/pages/study_random.html` —— 随机学习主页面（HTMX）
- `src/ielts_buddy/web/templates/pages/study_review.html` —— 复习主页面（HTMX）
- `src/ielts_buddy/web/templates/partials/_study_card.html` —— 单题卡（HTMX 加载的片段）
- `tests/test_web/test_study_api.py` —— 随机学习 + 复习的端到端测试

### 修改
- `src/ielts_buddy/web/services.py` —— 复用已有 `get_review_service`，再加 `get_learn_service`（借壳 VocabService 拼装单词）
- `src/ielts_buddy/web/main.py` —— 包含 study router
- `src/ielts_buddy/web/static/css/app.css` —— 新增 study card 样式
- `src/ielts_buddy/web/templates/base.html` —— 顶部导航加"学习"和"复习"链接

## 设计要点

### 复用 Service 的"借壳"模式
Web 端不能在 `ReviewService.__init__` 里走 `Config`（会读 CLI 的 config.toml）。
沿用 `services.py:107-115` 已有的 `_make_review_service`：
- 用 `__new__` 跳过 `__init__`
- 直接赋 `self._container = container`（lifespan 阶段开的）
- `self._repo = container.learning`
- `self._user_id = user_id`

这样零侵入，不动 services/ 层代码。

### VocabService 的复用
`VocabService` 是无状态的（按 `lru_cache` 共享单例），不需要借壳；
直接 `get_vocab_service()` 拿，用 `random_words(count, band)` 抽词。

### HTMX 局部刷新
- 主页面带一个 `<div id="study-card">` 占位
- 首次进入：从服务端 `GET /study/random` 直接返回带卡片的整页（无 HTMX 触发）
- 答完一题：用 `hx-post="/api/study/answer"` + `hx-target="#study-card"` + `hx-swap="outerHTML"`
  服务端返回新的 `_study_card.html` 片段
- 队列空：返回"今日任务完成 ✅"片段

### 多用户隔离
每次 Depends `get_current_user` → `user_id`，所有 SQL 都带 `user_id=?`，物理隔离。

### 选词策略
- 随机学习：优先选"今天还没学过的新词"（learning_records 中没有的），band 5-7 随机
- 复习：`ReviewService.get_due_words(limit=20)` 拿

## 自动化验收

`tests/test_web/test_study_api.py`：
1. `test_random_page_unauthenticated_redirects` —— 302 → /login
2. `test_random_page_renders_with_word` —— 200 + 含一个 word + 音标 + 中文释义
3. `test_random_answer_correct_records` —— POST 答对，DB 中 learning_records 增加一行
4. `test_random_answer_wrong_records` —— 答错：memory_level=0, next_review=today
5. `test_random_answer_increments_session_count` —— 多答几题，会话计数增加
6. `test_review_page_shows_due_word` —— DB 中预置到期词，/study/review 展示
7. `test_review_empty_due` —— 无到期词，提示"今日复习已完成"
8. `test_review_answer_advances_level` —— 答对，memory_level +1
9. `test_study_user_isolation` —— A 答词，B 看不到 A 的记录
10. `test_random_no_more_new_words` —— 学完所有词，提示"今日已学完 N 词"

## 人工验收

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
PYTHONPATH=src python -m ielts_buddy.web.main --port 8000
# 浏览器：注册 → 登录 → 进 /study/random
# 看到单词 → 点"认识" → 局部刷新到下一题
# 数据库（web_data.db）：sqlite3 ~/.ielts-buddy/web_data.db "SELECT * FROM learning_records"
```

## 风险点
- VocabService 加载 master JSON 体积较大（~10MB），启动慢——已 `lru_cache` 共享单例
- 答对的 memory_level 不能超过 6（REVIEW_INTERVALS 长度 7）

## 收尾标准
- [ ] 所有自动化用例通过
- [ ] 浏览器实际跑通"随机学习 5 题 + 复习 3 题"
- [ ] docs/web-mvp/records/2026-07-25-03-study.md 写好
- [ ] docs/web-mvp/retros/ 加新复盘
