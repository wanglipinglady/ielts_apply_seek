# scripts/auto/ — 8 个零介入自动化脚本

> 目的：把 W2–W8 期间 50% 的可自动任务全部脚本化，让你**只介入5 个时点**（买域名 / 提交审核 / 短信核验 / 真机扫码 / 提报签字）。

## 一次性配置（约 30 分钟）

| # | 脚本 | 一次性配置 | 时间 |
|---|------|------------|------|
| 1 | `01-upload_miniprogram.sh` | 装 Node + miniprogram-ci + 配 `WECHAT_MINIPROGRAM_APPID` + `WECHAT_MINIPROGRAM_KEY_PATH` | 10 分钟 |
| 2 | `02_seed_user_posts.py` | 无（自动生成 Markdown 文案） | 0 |
| 3 | `03_subscription_push.sh` | 申请订阅消息模板 + 配环境变量 + `crontab -e` 加一行 | 10 分钟 |
| 4 | `04_weekly_report.py` | `pip install matplotlib reportlab` | 2 分钟 |
| 5 | `05_ux_audit.py` | 无（默认扫 `/var/log/ielts-buddy/`）| 0 |
| 6 | `06_pack_submission.py` | 无（按需跑）| 0 |
| 7 | `07_weekly_risk_recheck.py` | 无（每周一 CI 自动跑）| 0 |
| 8 | `.github/workflows/weekly-recheck.yml` | 推送到 GitHub 后自动生效 | 0 |

---

## 8 个脚本用途一览

| 脚本 | 跑的命令 | 跑的时间 | 产出 |
|------|---------|----------|------|
| **01-upload_miniprogram** | `./01-upload_miniprogram.sh --review` | W5 上线日（9/22） | 上传 + 提交审核 |
| **02-seed_user_posts** | `python 02_seed_user_posts.py --review-only` | W5 上线后 | 5 篇平台文案 Markdown |
| **03-subscription_push** | 自动（crontab 每日 21:00）| W5 起每天 | 推送订阅消息 |
| **04-weekly_report** | `python 04_weekly_report.py` | W7（10/12） | PDF 数据周报 |
| **05-ux_audit** | `python 05_ux_audit.py` | W7（10/12） | 体验问题清单 Markdown |
| **06-pack_submission** | `python 06_pack_submission.py --members "姓名"` | W8（10/17） | submission_package.zip |
| **07-weekly_risk_recheck** | 自动（CI 每周一 9:00）| 每周一 | 风险触发报告 |

---

## 详细配置说明

### 1. `01-upload_miniprogram.sh` · 微信开发者工具 CLI 上传

**前置依赖**：

```bash
# 装 Node.js（macOS）
brew install node

# 装 miniprogram-ci
npm install -g @miniprogram/miniprogram-ci

# 在小程序后台生成上传密钥
# 路径：开发管理 → 开发设置 → 小程序代码上传 → 启用 + 生成密钥
# 下载 private_key.pem 文件

# 加环境变量（一次性）
echo 'export WECHAT_MINIPROGRAM_APPID="wx286309bc641b1d79"' >> ~/.zshrc
echo 'export WECHAT_MINIPROGRAM_KEY_PATH="/Users/wangliping/path/to/private_key.pem"' >> ~/.zshrc
source ~/.zshrc
```

**使用**：

```bash
./01-upload_miniprogram.sh                    # 默认 1.0.0 体验版
./01-upload_miniprogram.sh --review           # 提交审核
./01-upload_miniprogram.sh --version 1.0.1   # 指定版本号
```

### 2. `02_seed_user_posts.py` · 拉新文案生成

```bash
# 默认 5 篇轮询三大平台
python 02_seed_user_posts.py

# 只生成知乎
python 02_seed_user_posts.py --platform zhihu --count 3

# 只生成不发布（推荐）
python 02_seed_user_posts.py --review-only
```

输出在 `docs/miniprogram/_assets/seed_posts/`，每篇 Markdown 带占位符 `[待填写：...]`，你手动填真实内容后登录平台发布。

### 3. `03_subscription_push.sh` · 每日 21:00 复习提醒

**前置**：

```bash
# 在小程序后台：订阅消息 → 申请「复习提醒」模板
# 记录模板 ID 形如：k9xxxxxxxxxxxxxx-

echo 'export WECHAT_MINIPROGRAM_SECRET="你的 AppSecret"' >> ~/.zshrc
echo 'export SUBSCRIBE_TEMPLATE_ID="k9xxxxxxxxxxxxxx-"' >> ~/.zshrc
echo 'export API_BASE_URL="https://api.your-domain.cn"' >> ~/.zshrc
source ~/.zshrc

# 配 crontab
crontab -e
# 加这一行（每天北京时间 21:00）：
0 21 * * * /path/to/01-upload_miniprogram/../03_subscription_push.sh >> /var/log/ielts-subscription.log 2>&1
```

**手动测试**：

```bash
./03_subscription_push.sh --dry-run
```

### 4. `04_weekly_report.py` · W7 周报 PDF

```bash
# 装依赖
pip install --break-system-packages matplotlib reportlab

# 跑（自动读 DB）
python 04_weekly_report.py

# 指定周
python 04_weekly_report.py --week 2026-W36

# 自定义 DB URL
python 04_weekly_report.py --db-url 'mysql+pymysql://user:pwd@host:3306/db'
```

输出 `docs/miniprogram/_assets/weekly_report_<week>.pdf`

### 5. `05_ux_audit.py` · 体验问题扫描

```bash
# 默认扫 /var/log/ielts-buddy/
python 05_ux_audit.py

# 自定义日志目录
python 05_ux_audit.py --log-dir /var/log/nginx

# 指定起始日期
python 05_ux_audit.py --since 2026-09-01
```

输出 `docs/miniprogram/_assets/ux_audit_<date>.md`

### 6. `06_pack_submission.py` · W8 提报打包

```bash
# 提前准备：
# - 01_id_card_<姓名>.jpg 放到 docs/miniprogram/W8/submission/
# - 06_authorization_<姓名>.pdf 放到 docs/miniprogram/W8/submission/（模板从官方下载）
# - 05_description.pdf 由 AI 生成后放到 docs/miniprogram/W8/submission/

# 打包
python 06_pack_submission.py --members "张三,李四"
```

输出 `docs/miniprogram/W8/submission/submission_package.zip` + `README.md`（含缺失清单）

### 7. `07_weekly_risk_recheck.py` · 风险 recheck

```bash
# 默认上周
python 07_weekly_risk_recheck.py

# 指定周
python 07_weekly_risk_recheck.py --week 2026-W36
```

输出 `docs/miniprogram/_assets/risk_recheck_<year>_W<week>.md`

### 8. `weekly-recheck.yml` · GitHub Actions 周一自动跑

**触发**：每周一 UTC 01:00 (= 北京时间 09:00) 自动跑一次

**跑什么**：
1. 跑 `07_weekly_risk_recheck.py` 生成本周风险报告
2. 跑契约测试确保 schema 没被破坏
3. 上传报告为 artifact

**手动触发**：GitHub → Actions → Weekly Auto Recheck → Run workflow

---

## 配合 CLAUDE.md "5 条铁律"

这些脚本都**只读 + 写文档/配置**，**不修改 service / schema**：

| 脚本 | 是否改 service | 是否改 schema | 是否安全 |
|------|----------------|----------------|----------|
| 01-upload | ❌ | ❌ | ✅ 安全 |
| 02-seed | ❌ | ❌ | ✅ 安全 |
| 03-subscription | ❌ | ❌ | ✅ 安全（仅推送）|
| 04-weekly | ❌ | ❌ | ✅ 安全（只读） |
| 05-ux | ❌ | ❌ | ✅ 安全（只读）|
| 06-pack | ❌ | ❌ | ✅ 安全（只打包）|
| 07-risk | ❌ | ❌ | ✅ 安全（只读）|
| 08-CI | ❌ | ❌ | ✅ 安全（只跑测试）|

---

## 后续扩展

8 周赛事期间如有新需求，可在 `scripts/auto/` 下加新脚本，遵循：
- 编号递增 `NN_<name>.sh` / `.py`
- 顶部 docstring 写清楚用途 + 前置 + 用法
- 加入本 README 一览表
- 提交 PR 自动触发 CI

---

**最后更新**：2026-08-24
**配套文档**：[CLAUDE.md 多端共享契约铁律](../../CLAUDE.md) · [W1 总览](../../docs/miniprogram/W1/00-W1总览.md)