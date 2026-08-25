# vocab SKILL · 雅思词库搭子（v1.0）

> 微信 AI 开发模式 SKILL · 2026-08-24
> 注册上限 30 个 SKILL，本文件占 1 个

## 一、能力描述

英语干中学内置 4485 个 Band 5-9 词汇 + 526 个精选词。本 SKILL 把"词库搭子"原子化，支持按 Band 5-9 / Topic 筛选词库、随机抽词、提交测验答案并写入艾宾浩斯复习系统、查询错词本。

## 二、原子接口

### list_vocab · 列词库

输入 Schema（JSON）：
```json
{"band": 7, "topic": "education", "page": 1, "per_page": 20}
```

输出 Schema：
```json
{
  "words": [{"word":"opportunity","phonetic":"...","meaning":"机会","pos":"n.","band":7,"topic":"education"}],
  "total": 1132, "page": 1, "per_page": 20, "total_pages": 57
}
```

后端：`GET /api/wx/study/vocab/list`

### random_vocab · 随机抽词

输入：`{"band": 7, "count": 10}` → 输出：`{"words": [...], "count": 10}`

后端：`POST /api/wx/study/vocab/random`

### submit_quiz · 提交测验答案

输入：`{"word":"opportunity", "user_answer":"机会", "correct":true, "mode":"en2zh"}`

输出：`{"word":"...", "is_correct":true, "memory_level":1, "next_review_at":"2026-08-25"}`

后端：`POST /api/wx/study/vocab/quiz/submit`

## 三、典型用例

1. 用户问"雅思7分教育类的高频词有哪些" → `list_vocab(band=7, topic="education")`
2. 用户说"给我抽5个Band 8的词练习" → `random_vocab(band=8, count=5)`
3. 用户答对一个词 → `submit_quiz(word, user_answer, correct, mode)`

## 四、错误处理

| 场景 | 返回 | 处理 |
|------|------|------|
| 未登录 | 401 | 提示"请先登录" |
| 词不存在 | 404 | 提示"不在词库" |
| 服务异常 | 500 | 提示"稍后再试" |

## 五、依赖关系

- 后端路由：`src/ielts_buddy/web/routers/wx_study.py`
- 数据库：v3.9 users + words + learning_records
- SKILL 注册：miniprogram/SKILL/vocab/