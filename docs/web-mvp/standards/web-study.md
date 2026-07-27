# 学习 / 复习页规范

> 适用：`/study/random` `/study/review` 两个页面 + `/api/study/answer` 端点。

## 1. URL

- 页面：`GET /study/random` `/study/review`
- 答题：`POST /api/study/answer`（form 表单）

未登录访问页面 → 302 → /login
未登录调答题 API → 401

## 2. 选词逻辑

### 2.1 随机学习

- 从 band 5/6/7/8/9 等概率随机选一个 band
- 从该 band 词库过滤掉 `learning_records` 里 user 已学过的 word
- 再从剩下的随机抽 1 个
- 全学完 → 显示"今日新词已学完 ✅ 休息一下，明天继续。"

### 2.2 复习

- 从 `learning_records` 取 `user_id=? AND next_review <= today`
- 按 `memory_level ASC, next_review ASC` 排序
- 选第 1 条
- 队列空 → 显示"今日复习已完成 🎉"

## 3. 答题端点

`POST /api/study/answer` 接收：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `word` | str | 单词原形 |
| `correct` | bool | "true" / "false"（form 表单值） |
| `mode` | str | `"random"` / `"review"` |

服务端：

1. `vocab.get_word(word)` 找不到 → 404
2. `_upsert_record(conn, user_id, word, correct, source="web")` 写入
3. 按 mode 选下一题，返回 `_study_card.html` 片段

## 4. 艾宾浩斯 0-6 等级

| Level | 间隔（天） | next_review |
| --- | --- | --- |
| 0 | 0 | 今天 |
| 1 | 1 | +1 天 |
| 2 | 2 | +2 天 |
| 3 | 4 | +4 天 |
| 4 | 7 | +7 天 |
| 5 | 15 | +15 天 |
| 6 | 30 | +30 天 |

答对：`level = min(level + 1, 6)`；答错：`level = max(level - 1, 0)`。

## 5. 数据库写入规范

- **唯一允许**走 `app.state.web_stats_conn`（`check_same_thread=False`）
- 字段：`user_id, word, word_data (JSON), memory_level, next_review, learn_count, correct_count, wrong_count, first_learned, last_reviewed, source`
- `source` 字段：web 端统一写 `"web"`，与 CLI 端 `"builtin"` / `"manual"` 区分
- `word_data` 存 `Word.model_dump_json()`，方便复习时反序列化回 Word 对象

## 6. 模板结构

### 6.1 完整页面（`pages/study_random.html` / `study_review.html`）
```html
{% extends "base.html" %}
{% block content %}
<section class="study-page">
  <h1>{标题}</h1>
  <p class="lede">{说明}</p>
  <div id="study-card">
    {% include "partials/_study_card.html" %}
  </div>
</section>
{% endblock %}
```

### 6.2 题卡 partial（`partials/_study_card.html`）
- 单词 + 音标 + 词性 + 释义（默认 hidden）
- "显示答案"按钮（原生 JS 切 hidden）
- "认识 ✓" / "不认识 ✗" 按钮（HTMX POST）
- 空队列显示"已完成"提示

### 6.3 HTMX 集成
```html
<form hx-post="/api/study/answer"
      hx-target="#study-card"
      hx-swap="outerHTML">
  <input type="hidden" name="word" value="...">
  <input type="hidden" name="mode" value="...">
  <button name="correct" value="true">认识 ✓</button>
  <button name="correct" value="false">不认识 ✗</button>
</form>
```

## 7. 测试覆盖

| 场景 | 期望 |
| --- | --- |
| 未登录访问页面 | 302 → /login |
| 未登录调 API | 401 |
| 答一题 | learning_records +1 |
| 连答 5 题 | learning_records 5 条 |
| 复习空队列 | 页面"今日复习已完成" |
| 复习有 1 题到期 | 页面展示该词 |
| 答对复习题 | memory_level +1 |
| 答对 5 题 → dashboard 摘要更新 | 摘要数字准确 |
| 多用户：A 答 1 题 | B 的 learning_records 仍 0 |
| 词库找不到的 word | 404 |

## 8. 已知限制（MVP 范围）

- 复习只显示 1 题（无多题缓存）
- 答错不立即加入"错题本"（T-04 实现）
- 无收藏夹入口（T-04 实现）
- 无难度自适应（T-08 实现）

## 9. 后续优化建议

1. **多题缓存**：进入复习时拉 20 题到 client cookie，答完一题从队列取下一题（避免 HTMX 请求次数）
2. **错题本**：review_service 已有 `vocab_categories` (mistakes / favorites)，加按钮调 `/api/study/{star,mark_mistake}`
3. **键盘快捷键**：`J` = 不认识 / `K` = 认识 / `Space` = 显示答案
4. **音效**：答对/答错播不同声音（Web Audio API）
5. **学习统计**：每题答完累加 `session_count`，session 结束弹统计
