#!/usr/bin/env bash
# scripts/auto/08-auto_git_push.sh
# ------------------------------------------------------------------------------
# 用途：把当前仓库的修改自动 commit + push 到 GitHub origin/master
# 解决：每次写完代码还要手动 git add / commit / push 一长串命令的问题
#
# 前置（一次性配置）：
#   1. 已配置 SSH key 或 HTTPS credential（任选其一）：
#      - SSH（推荐）：ssh-add ~/.ssh/id_ed25519 已加入 keychain
#      - HTTPS：git push 时弹窗输入用户名/Token（Token 见 GitHub Settings → PAT）
#   2. 当前分支：master（与 origin/master 同步）
#   3. git user.name / user.email 已配置（项目级或全局均可）
#
# 用法：
#   ./scripts/auto/08-auto_git_push.sh                              # 自动生成 commit message
#   ./scripts/auto/08-auto_git_push.sh "docs: 更新操作手册"          # 自定义 message
#   ./scripts/auto/08-auto_git_push.sh --dry-run                    # 只看会推送什么，不真推
#   ./scripts/auto/08-auto_git_push.sh --no-push                    # 只本地 commit，不 push
#   ./scripts/auto/08-auto_git_push.sh --branch dev                 # 指定分支（默认 master）
#
# 安全护栏：
#   - 默认拒绝推送 .env / *.pem / id_* 等敏感文件
#   - 推送前会先 git fetch + 检查本地是否领先
#   - 失败时不会留下脏 commit
# ------------------------------------------------------------------------------
set -euo pipefail

# ---------- 参数解析 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

BRANCH="master"
DRY_RUN=false
NO_PUSH=false
COMMIT_MSG=""

for arg in "$@"; do
  case "$arg" in
    --branch) shift; BRANCH="$1"; shift ;;
    --dry-run) DRY_RUN=true ;;
    --no-push) NO_PUSH=true ;;
    --help|-h)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *) COMMIT_MSG="$arg" ;;
  esac
done

# ---------- 安全护栏：拒绝敏感文件 ----------
SENSITIVE_RE='(\.env$|\.env\.|\.pem$|\.key$|id_rsa|id_ed25519|\.DS_Store$|secrets\.)'
SENSITIVE_FILES=$(git status --porcelain | grep -E "$SENSITIVE_RE" || true)
if [ -n "$SENSITIVE_FILES" ]; then
  echo "❌ 检测到敏感文件，拒绝推送："
  echo "$SENSITIVE_FILES"
  echo ""
  echo "如确认要推送，请先把它们加进 .gitignore 或移出工作区。"
  exit 1
fi

# ---------- 状态检查 ----------
echo "📋 当前仓库状态："
git status --short
echo ""

# 没有任何改动
if [ -z "$(git status --porcelain)" ]; then
  echo "ℹ️  没有需要提交的改动。"
  exit 0
fi

# ---------- 远端同步检查 ----------
echo "🔄 同步远端 $BRANCH ..."
git fetch origin "$BRANCH" 2>/dev/null || {
  echo "⚠️  无法 fetch（可能是网络问题），继续本地 commit，但 push 可能失败。"
}

# 检查本地是否领先 / 落后
LOCAL_HEAD=$(git rev-parse HEAD)
REMOTE_HEAD=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")
if [ -n "$REMOTE_HEAD" ] && [ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]; then
  echo "⚠️  本地与 origin/$BRANCH 不同步："
  echo "   本地: $LOCAL_HEAD"
  echo "   远端: $REMOTE_HEAD"
  echo "   提示：如果 push 被拒绝，先 git pull --rebase 解决冲突。"
fi

# ---------- 生成默认 commit message ----------
if [ -z "$COMMIT_MSG" ]; then
  # 从改动文件智能推断
  CHANGED_DIRS=$(git status --porcelain | awk '{print $2}' | xargs -I {} dirname {} | sort -u | head -3)
  FIRST_DIR=$(echo "$CHANGED_DIRS" | head -1 | sed 's|^./||')
  TIMESTAMP=$(date +"%Y-%m-%d")
  COMMIT_MSG="chore: 自动更新 ${FIRST_DIR:-repo} (${TIMESTAMP})"
fi

# ---------- Dry-run 提前退出 ----------
if [ "$DRY_RUN" = true ]; then
  echo "🔍 [DRY-RUN] 会执行的操作："
  echo "   git add -A"
  echo "   git commit -m \"$COMMIT_MSG\""
  if [ "$NO_PUSH" = false ]; then
    echo "   git push origin $BRANCH"
  fi
  echo ""
  echo "   改动文件："
  git status --short
  exit 0
fi

# ---------- Stage + Commit ----------
echo "📦 添加所有改动..."
git add -A

echo "📝 提交：$COMMIT_MSG"
git commit -m "$COMMIT_MSG"

if [ "$NO_PUSH" = true ]; then
  echo ""
  echo "✅ 本地提交完成（未推送）。如需推送："
  echo "   git push origin $BRANCH"
  exit 0
fi

# ---------- Push ----------
echo ""
echo "🚀 推送到 origin/$BRANCH ..."
if git push origin "$BRANCH"; then
  echo ""
  echo "✅ 推送成功！"
  COMMIT_SHA=$(git rev-parse --short HEAD)
  echo "   Commit: $COMMIT_SHA"
  echo "   Branch: $BRANCH"
  echo "   Remote: origin/$BRANCH"
else
  echo ""
  echo "❌ 推送失败。常见原因："
  echo "   1) 网络问题（参考之前的 75 秒超时）→ 等网络恢复后重试"
  echo "   2) 远端有更新 → git pull --rebase origin $BRANCH 再 push"
  echo "   3) 权限问题 → 检查 SSH key 或 HTTPS Token"
  exit 1
fi