# 阶段 3 人工验收清单

**前置**：所有 87 个 web 自动化测试已通过（`PYTHONPATH=src python -m pytest tests/test_web/ -q`）。

## 1. 启动

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
PYTHONPATH=src python -m ielts_buddy.web.main --port 8000
```

预期 stdout：`Uvicorn running on http://127.0.0.1:8000`

⚠️ 如果提示 `JWT_SECRET 未设置` 是正常（dev 用临时密钥）；生产请设置 `IELTS_BUDDY_JWT_SECRET`。

## 2. 注册 + 登录

1. 浏览器打开 http://127.0.0.1:8000/register
2. 填写 email（如 `test@x.com`）+ 密码（≥8 位）→ 点"注册"
3. 应自动跳转 /dashboard，右上角看到 `test@x.com` 用户徽章
4. 顶部导航应有 4 个链接：Dashboard / 随机学习 / 复习 / 统计

## 3. 随机学习

1. 点击顶部"随机学习" → 跳 `/study/random`
2. 应看到一张单词卡：单词 + 音标 + 词性
3. 点击"显示答案"按钮 → 释义出现
4. 点"认识 ✓"或"不认识 ✗"：
   - 页面局部刷新到下一题（不重新加载整页）
   - DevTools Network 看 `POST /api/study/answer` 返回 200，response 是 HTML 片段
5. 答 5 题后，dashboard 页面应能看到"今日新学"+"今日复习"≥1

## 4. 复习

1. 此时 `/study/review` 页面：显示"今日复习已完成 🎉"（因为之前答对题已设置 next_review=未来）
2. 想验证复习逻辑，手工改一条记录的 `next_review` 为今天：
   ```bash
   sqlite3 ~/.ielts-buddy/web_data.db
   UPDATE learning_records SET next_review = date('now') WHERE word = '某个你刚学过的词';
   ```
3. 刷新 `/study/review`，应看到该词出现
4. 答对后该词 memory_level 升 1，next_review 推到 1 天后；再访问 `/study/review` 应该看不到它了

## 5. 统计

1. 点击顶部"统计" → 跳 `/stats`
2. 摘要卡片：今日新学 ≥1、累计复习次数 = 答的总题数
3. 记忆等级分布：L0 / L1 有数（取决于正确率）
4. 各 Band 掌握进度：表格 + 进度条

## 6. 多用户隔离

1. 退出（右上角"登出"）→ 跳 /login
2. 用另一个邮箱注册新用户 → 答 1 题
3. 切回原用户 → `/stats` 应该**看不到**第二个用户的答题
4. 数据库验证：
   ```bash
   sqlite3 ~/.ielts-buddy/web_data.db "SELECT user_id, word, memory_level FROM learning_records"
   # 应该看到两行，user_id 不同
   ```

## 7. 异常路径

| 场景 | 预期 |
| --- | --- |
| 未登录直接访问 `/study/random` | 302 → `/login` |
| 答完一题后 `correct=true`，但 word 词库不存在（POST 直接改） | 404 |
| `mode` 传未知值 | 400 |
| refresh token 过期后访问 | 401 + 清 cookie |

## 8. 自动化复测

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
PYTHONPATH=src python -m pytest tests/test_web/ -v
# 期望：87 passed
```

## 9. 已知限制（不在 MVP 范围）

- 答错/答对有简单统计，但**无错题本入口**（阶段 4 加）
- 复习只显示一题，**无多题缓存**（重做会再抽同一题）
- 学习 / 复习 / 统计 页面**无国际化切换**（i18n 阶段 4+）
- 数据库是 web_data.db（SQLite），**生产应切 MySQL**（阶段 4+ 重构 Service 后）
- 无 CSRF 保护（cookie 是 SameSite=Lax，dev 安全；生产需要加 CSRF token）

## 10. 验收完成

如果 1-8 都通过：
- 在 `docs/web-mvp/manual-verify-phase-3.md` 末尾的签字区写上日期 + 你的名字
- 提 PR / 合并到主分支
- 下一阶段（剩余任务见 `remaining-tasks.md`）
