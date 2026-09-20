# 自动推送到 GitHub · 使用指南

> **目的**：把"写完代码 → 手动 `git add/commit/push` → 等待网络"这套繁琐流程封装成一个命令，
> 让 8 周赛事期间的所有代码改动可以一键 =「走 chat 流」自动落到 GitHub。
>
> **适用读者**：本项目所有协作者 + 新会话的 TRAE Agent
>
> **创建日期**：2026-09-20（剩 27 天到提报截止 2026-10-17）
>
> **配套脚本**：`scripts/auto/08-auto_git_push.sh`

---

## 1. 一句话总结

```bash
./scripts/auto/08-auto_git_push.sh                # 全部默认：add + commit + push
./scripts/auto/08-auto_git_push.sh "docs: W7 复盘" # 自定义 message
./scripts/auto/08-auto_git_push.sh --dry-run       # 只预览不真跑
./scripts/auto/08-auto_git_push.sh --no-push       # 只本地 commit 不 push
```

跑完 = 一行命令自动完成 `git add -A` → `git commit` → `git push origin master`。

---

## 2. 一次性配置（约 10 分钟）

### 2.1 选一种认证方式

| 方式 | 适用场景 | 配置步骤 |
|---|---|---|
| **SSH（推荐）** | 长期使用，不想每次输入 Token | 1. `ssh-keygen -t ed25519 -C "your_email@example.com"` <br>2. `cat ~/.ssh/id_ed25519.pub` → 复制 <br>3. GitHub → Settings → SSH and GPG keys → New SSH key → 粘贴 <br>4. `ssh-add --apple-use-keychain ~/.ssh/id_ed25519`（macOS 记住密码） |
| **HTTPS + PAT** | 临时使用，跨机器 | 1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token <br>2. 勾选 `repo` + `workflow` <br>3. 生成后**只显示一次**，立刻复制保存 <br>4. push 时弹窗用 Token 作为密码 |

### 2.2 配置 git 用户信息（项目级即可）

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
git config user.name  "你的名字"
git config user.email "your_email@example.com"
```

### 2.3 把脚本加入 PATH（可选）

如果想直接 `auto-push` 调用而不是长长的相对路径：

```bash
echo 'export PATH="$PATH:/Users/wangliping/Public/selfProgram/ielts_apply_seek/scripts/auto"' >> ~/.zshrc
source ~/.zshrc

# 之后可以
auto-push "feat: 添加错词本页面"
```

---

## 3. 使用场景速查

### 场景 A：常规开发后推送

```bash
# 1. 改完代码
# 2. 跑脚本
./scripts/auto/08-auto_git_push.sh

# 输出：
# 📋 当前仓库状态：
#  M src/ielts_buddy/web/main.py
#  M docs/miniprogram/W9/README.md
#
# 📦 添加所有改动...
# 📝 提交：chore: 自动更新 src (2026-09-20)
# 🚀 推送到 origin/master ...
# ✅ 推送成功！
#    Commit: a1b2c3d
#    Branch: master
#    Remote: origin/master
```

### 场景 B：自定义 commit message

```bash
./scripts/auto/08-auto_git_push.sh "feat(miniprogram): 接入微信 AI SKILL"
```

### 场景 C：先预览再决定是否真推

```bash
./scripts/auto/08-auto_git_push.sh --dry-run
# 会打印"会执行什么"但不真跑，适合批量改动前的检查
```

### 场景 D：只本地 commit 不 push

```bash
./scripts/auto/08-auto_git_push.sh --no-push
# 适合：网络不好时先 commit，等网络恢复再手动 git push origin master
```

### 场景 E：在 dev 分支上工作

```bash
./scripts/auto/08-auto_git_push.sh --branch dev "feat: 实验性功能"
```

---

## 4. 内置安全护栏

| 护栏 | 触发条件 | 行为 |
|---|---|---|
| **敏感文件拒绝** | 工作区有 `.env` / `*.pem` / `id_rsa` / `id_ed25519` / `.DS_Store` / `secrets.*` | 直接拒绝并打印文件清单，不会 commit 任何文件 |
| **空提交退出** | 工作区无改动 | 直接退出码 0，不产生空 commit |
| **远端同步检查** | 本地与 origin 不同步 | 警告但不阻塞，由用户决定如何 rebase |
| **失败不留脏 commit** | push 失败 | 自动 abort commit（`set -e` + `git commit` 之前不修改 HEAD） |

如果需要 **临时豁免敏感文件护栏**（比如真的需要提交 `miniprogram_private_key.pem`），先把它移出工作区再 commit，或临时改 `SENSITIVE_RE` 变量。

---

## 5. 常见错误与解决

### 5.1 `Failed to connect to github.com port 443`

**原因**：网络无法访问 GitHub（典型情况：环境无外网、VPN 未开、DNS 污染）。

**解决**：

```bash
# 1. 测试连通性
curl -sS -o /dev/null -w "%{http_code}\n" --max-time 10 https://github.com
# 返回 200/301 = OK，返回 000 = 不通

# 2. 不通时的应急：
./scripts/auto/08-auto_git_push.sh --no-push    # 先本地 commit
# 等网络恢复后：
git push origin master                         # 手动 push
```

### 5.2 `non-fast-forward`（拒绝推送）

**原因**：远端有更新，本地落后。

**解决**：

```bash
git pull --rebase origin master
./scripts/auto/08-auto_git_push.sh             # 再跑一次
```

### 5.3 `Permission denied (publickey)`

**原因**：SSH key 没加到 ssh-agent。

**解决**：

```bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519   # macOS
# 或重新走 2.1 的 SSH 配置步骤
```

### 5.4 误把 `.DS_Store` 提交了

**原因**：macOS 自动生成。

**解决**：

```bash
# 已经在 .gitignore 但可能之前 commit 过
git rm --cached .DS_Store
./scripts/auto/08-auto_git_push.sh "chore: 移除误提交的 .DS_Store"
```

---

## 6. 与其他工具的配合

### 6.1 配合 CLAUDE.md "5 条铁律"

`08-auto_git_push.sh` 只触发 commit/push，**不会**自动：
- 跑测试 → 提交前手动 `pytest`
- 修改 service / schema → 走 PR 流程
- 跳过 CI → 让 CI 自己挂

### 6.2 配合 `.github/workflows/ci.yml`

每次 push 后会自动触发：
1. `contract-tests`（多端共享契约守门）
2. `monitoring-tests`（告警/自愈）
3. `full-tests`（全量）

任一挂掉 → PR 不会合入 → 需要本地修完再 push。

### 6.3 配合 `scripts/auto/` 其他 7 个脚本

| 脚本 | 联动方式 |
|---|---|
| `01-upload_miniprogram.sh` | 先 `08-auto_git_push` 推代码到 GitHub，再跑 01 上传体验版 |
| `02_seed_user_posts.py` | 生成文案后 `08-auto_git_push` 推到 docs |
| `06_pack_submission.py` | 打包前 `08-auto_git_push` 确保最新代码已落库 |

---

## 7. 给 TRAE 新会话的首轮 prompt 模板

如果开新会话只想用推送功能，把这段贴进新对话：

```markdown
# 任务：使用自动推送脚本

## 项目路径
/Users/wangliping/Public/selfProgram/ielts_apply_seek

## 必读文档（先 Read）
1. `docs/miniprogram/W9/08-自动推送GitHub指南.md` — 完整使用说明
2. `scripts/auto/08-auto_git_push.sh` — 脚本本体

## 工作模式
- 改完代码后，调用：
  `./scripts/auto/08-auto_git_push.sh "你的 commit message"`
- 默认分支 master，认证走 SSH
- 如果遇到网络问题（github.com:443 超时），改用 `--no-push` 先本地 commit

## 约束
- 不要修改敏感文件护栏（`.env`、`.pem` 等）
- 每次 push 前确保本地测试通过
```

---

## 8. 维护

| 维护项 | 频率 | 负责人 |
|---|---|---|
| 检查网络可达性 | 每次推送失败时 | 自动诊断 |
| 更新脚本 | 流程变更时 | 项目维护者 |
| 更新本指南 | 新增使用场景时 | 项目维护者 |

---

**最后更新**：2026-09-20
**配套脚本**：[`scripts/auto/08-auto_git_push.sh`](../../../scripts/auto/08-auto_git_push.sh)
**关联文档**：[`scripts/auto/README.md`](../../../scripts/auto/README.md) · [`CLAUDE.md`](../../../CLAUDE.md)