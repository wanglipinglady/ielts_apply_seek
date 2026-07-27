# MVP 整体人工验证清单

> 5 个页面（登录 + Dashboard + 随机学习 + 复习 + 统计）端到端人工验收。
> 自动化已通过（`pytest tests/test_web/ -v` → **87 passed**）；本清单只覆盖自动化无法验证的项。
>
> 分阶段清单见：
> - [`manual-verify-phase-1.md`](manual-verify-phase-1.md)（仅认证）
> - [`manual-verify-phase-3.md`](manual-verify-phase-3.md)（仅学习闭环）

## 0. 启动服务

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
PYTHONPATH=src \
  IELTS_BUDDY_WEB_SQLITE_PATH=$(mktemp -d)/web_data.db \
  python -m ielts_buddy.web.main --port 8000
```

预期 stdout：
- `Uvicorn running on http://127.0.0.1:8000`
- 顶部 `UserWarning: JWT_SECRET 未设置...`（dev 正常；生产必设 `IELTS_BUDDY_JWT_SECRET`）

`/tmp/web_data.db` 路径可选，默认是 `~/.ielts-buddy/web_data.db`，dev 推荐临时文件。

---

## 1. 5 个页面端到端（必须）

按下面顺序逐项打勾；任一项 ❌ 立即停，定位修复后从头跑。

### 1.1 登录 / 注册（页面 1+2）

- [ ] 浏览器打开 `http://127.0.0.1:8000/`
- [ ] 顶部 nav 应显示"登录 / 注册"（未登录态）
- [ ] 点"注册"，填写 `e2e-a@x.com` + 8 位以上密码 → 提交
- [ ] 预期自动跳 `/dashboard`，右上角徽章显示 `e2e-a@x.com`
- [ ] DevTools → Application → Cookies 看到 `ib_refresh`：
  - `HttpOnly` ✓
  - `Path=/api/auth` ✓
  - `SameSite=Lax` ✓
  - `Secure` ✗（dev，正常；生产 HTTPS 应为 ✓）
- [ ] 点"登出" → 跳回 `/`
- [ ] 再访问 `/dashboard` → 跳 `/login`
- [ ] 登录 `e2e-a@x.com` / 正确密码 → 跳 `/dashboard`
- [ ] 故意输错密码 → 看到错误提示（不区分"用户不存在 / 密码错"，规避邮箱枚举）

### 1.2 Dashboard（页面 3）

- [ ] 登录后 `/dashboard` 看到：
  - 欢迎语 `欢迎，e2e-a@x.com`
  - 4 张摘要卡片：今日新学 / 今日复习 / 待复习 / 连续天数
  - 3 个跳转链接：随机学习 / 复习 / 完整统计

### 1.3 随机学习（页面 4）

- [ ] 点"开始今日学习" → 跳 `/study/random`
- [ ] 看到单词卡：单词 + 音标 + 词性
- [ ] 点"显示答案"按钮 → 释义（中文）出现
- [ ] 点"认识 ✓"：
  - 页面**局部刷新**到下一题（不重载整页）
  - DevTools Network 看到 `POST /api/study/answer` → 200，response 是 HTML 片段
  - URL 仍是 `/study/random`（HTMX 局部替换）
- [ ] 连点 5 题"认识" → `/dashboard` 摘要卡"今日新学" ≥ 5
- [ ] 数据库验证：
  ```bash
  sqlite3 /tmp/web_data.db "SELECT user_id, word, memory_level, next_review FROM learning_records"
  # 应看到 5 行，user_id 是 e2e-a@x.com 对应的 id，memory_level=1
  ```

### 1.4 复习（页面 5 之一）

- [ ] 此刻 `/study/review`：
  - 顶部"待复习 0 个词"（因为刚才 5 题答对，next_review 推到 +1 天）
  - 卡片区显示"今日复习已完成 🎉"

- [ ] 想验证复习逻辑：手动改一条记录的 `next_review` 为今天：
  ```bash
  sqlite3 /tmp/web_data.db \
    "UPDATE learning_records SET next_review = date('now') WHERE word = '你刚学过的某个词'"
  ```

- [ ] 刷新 `/study/review`：
  - 顶部"待复习 1 个词"
  - 看到该词
  - 答对后该词 `memory_level` 升 1，`next_review` 推到 +1 天
  - 再次访问 `/study/review` → 又显示"已完成"

### 1.5 完整统计（页面 5 之二）

- [ ] 点"查看完整统计" → 跳 `/stats`
- [ ] 看到 4 段：
  - 摘要：8 张卡（今日新学 / 复习 / 总学词数 / 累计正确 / 错误 / 正确率 / 已掌握 / 待复习）
  - 记忆等级分布：L0 / L1 表格 + 进度条
  - 各 Band 掌握进度：5 行（Band 5-9）
  - 最近 7 天：表格（首行是今天）

---

## 2. 异常路径

| 场景 | 预期 |
|---|---|
| 未登录访问 `/dashboard` | 302 → `/login` |
| 未登录访问 `/study/random` | 302 → `/login` |
| 未登录访问 `/stats` | 302 → `/login` |
| 未登录 `POST /api/study/answer` | 401 |
| 未登录 `GET /api/stats/summary` | 401 |
| 直接调 `POST /api/study/answer` 用词库里不存在的 word | 404 |
| `mode` 传未知值（手工改 form） | 400 |
| refresh cookie 过期 | `/api/auth/refresh` → 401 + 清 cookie |

---

## 3. 多用户隔离

- [ ] 登出（右上角"登出"）→ 跳 `/`
- [ ] 注册新用户 `e2e-b@x.com` → 答 2 题
- [ ] 登出 → 登录 `e2e-a@x.com` → `/stats`：
  - 看不到 B 用户的任何数据
  - "总学词数"是 A 自己的（5）而不是 7

- [ ] 数据库交叉验证：
  ```bash
  sqlite3 /tmp/web_data.db \
    "SELECT user_id, COUNT(*) FROM learning_records GROUP BY user_id"
  # 应看到两行：e2e-a 是 5，e2e-b 是 2
  ```

- [ ] CLI 侧验证隔离（不影响 Web 端用户表）：
  ```bash
  PYTHONPATH=src python -m ielts_buddy.cli user list
  # 应该看不到 e2e-a@x.com / e2e-b@x.com —— 物理隔离
  ```

---

## 4. CLI 业务回归（确保 Web 改造没破坏后端）

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
PYTHONPATH=src python -m pytest tests/test_services tests/test_commands tests/test_repositories -q
# 预期：~1009 passed, ~31 failed（失败均为 pre-existing，与 Web 无关）
```

已知 pre-existing 失败：
- `test_grading_service.py`：LLM 真实调用，沙箱无外网
- `test_email_service.py`：`'day_num' is undefined` 模板字段
- `test_auth_cli.py` / `test_auth_service.py`：`tomllib`（Python 3.10 没这库，3.11+ 才有）

**判定标准**：除上述 pre-existing 失败外**没有新增**失败。

---

## 5. JWT 安全属性

DevTools → Application → Cookies → `ib_refresh`：

| 属性 | 期望 | 实际 |
|---|---|---|
| `HttpOnly` | ✓ | |
| `Path` | `/api/auth` | |
| `SameSite` | `Lax` | |
| `Secure` | ✗（dev） | |

prod 必设：
```bash
IELTS_BUDDY_ENV=prod python -m ielts_buddy.web.main
# 缺 JWT_SECRET → RuntimeError，预期启动失败
```

---

## 6. 验收通过

5 个页面 + 异常路径 + 多用户隔离 + CLI 回归全部 ✅ 后：
1. 在工单 / 群里回复"MVP 人工验证通过"
2. 提 PR 合并到主分支
3. 下一阶段进入 `remaining-tasks.md` 里的 P0 任务

如果任一项失败，把现象 + 复现步骤发回。
