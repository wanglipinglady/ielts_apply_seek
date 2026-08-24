#!/usr/bin/env bash
# scripts/auto/03_subscription_push.sh
# ------------------------------------------------------------------------------
# 用途：每天 21:00 推送「今日复习待办」微信订阅消息（用户留存核心）
# 一次性配置：crontab 加一行
# 收益：8 周内用户每日拉活，不用手动触发
#
# 前置（一次性配置）：
#   1. 在微信小程序后台：订阅消息 → 申请「复习提醒」模板（一次性永久模板）
#      模板 ID 形如：k9xxxxxxC4Vxxxxxx_xxxxx-
#   2. 在小程序代码里埋点：用户首次复习时询问是否订阅（用户授权一次）
#   3. 把模板 ID 加到环境变量（见下方）
#   4. 跑这个脚本，先手动测试一次
#   5. crontab 加一行（见脚本末尾注释）
#
# 用法：
#   ./scripts/auto/03_subscription_push.sh                # 推送今日
#   ./scripts/auto/03_subscription_push.sh --dry-run      # 只打印不发
# ------------------------------------------------------------------------------
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ---- 配置区（一次性设置）----

# 微信小程序 AppID
export WECHAT_MINIPROGRAM_APPID="${WECHAT_MINIPROGRAM_APPID:-wx286309bc641b1d79}"

# 微信小程序 AppSecret（仅服务端使用，切勿外传）
export WECHAT_MINIPROGRAM_SECRET="${WECHAT_MINIPROGRAM_SECRET:-请填入}"

# 订阅消息模板 ID（从小程序后台获取）
export SUBSCRIBE_TEMPLATE_ID="${SUBSCRIBE_TEMPLATE_ID:-请填入模板 ID}"

# 后端 API base URL（备案下来后的域名）
export API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"

# ---- 解析参数 ----
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --help)
      echo "用法: $0 [--dry-run]"
      exit 0
      ;;
    *) echo "未知参数: $arg"; exit 1 ;;
  esac
done

# ---- 校验环境 ----
if [ "$WECHAT_MINIPROGRAM_SECRET" = "请填入" ]; then
  echo "❌ 错误：WECHAT_MINIPROGRAM_SECRET 未设置"
  echo "   在 ~/.bashrc 加：export WECHAT_MINIPROGRAM_SECRET=xxx"
  exit 1
fi
if [ "$SUBSCRIBE_TEMPLATE_ID" = "请填入模板 ID" ]; then
  echo "❌ 错误：SUBSCRIBE_TEMPLATE_ID 未设置"
  echo "   在小程序后台：订阅消息 → 模板管理 → 获取模板 ID"
  exit 1
fi

# ---- 主流程 ----
TODAY=$(date +%Y-%m-%d)
echo "📨 [$TODAY] 开始推送订阅消息..."

# 1. 从后端取「今日待复习」用户列表
echo "   1) 获取今日待复习用户列表..."
USERS_JSON=$(curl -sf "$API_BASE_URL/api/admin/subscribe/today-reviewers" || echo '{"users":[]}')
USER_COUNT=$(echo "$USERS_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('users',[])))")
echo "      共 $USER_COUNT 个用户"

if [ "$USER_COUNT" = "0" ]; then
  echo "⚠️ 今日无待复习用户，跳过"
  exit 0
fi

# 2. 取 access_token
echo "   2) 获取微信 access_token..."
ACCESS_TOKEN=$(curl -sf \
  "https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=$WECHAT_MINIPROGRAM_APPID&secret=$WECHAT_MINIPROGRAM_SECRET" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

if [ -z "$ACCESS_TOKEN" ]; then
  echo "❌ 错误：获取 access_token 失败"
  exit 1
fi

# 3. 逐个用户推送
echo "   3) 推送中..."
if [ "$DRY_RUN" = true ]; then
  echo "      (--dry-run 模式，跳过真实推送)"
  exit 0
fi

echo "$USERS_JSON" | python3 <<EOF
import os, sys, json, urllib.request

users = json.loads('''$USERS_JSON''').get('users', [])
template_id = '$SUBSCRIBE_TEMPLATE_ID'
access_token = '$ACCESS_TOKEN'

success, fail = 0, 0
for u in users:
    payload = {
        "touser": u['openid"],
        "template_id": template_id,
        "data": {
            "thing1": {"value": f"今日待复习 {u['due_count']} 词"},
            "time2": {"value": "$TODAY 21:00"},
            "thing3": {"value": "点击开始今日复习"}
        }
    }
    req = urllib.request.Request(
        f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={access_token}",
        data=json.dumps(payload).encode('utf-8')
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            if body.get('errcode') == 0:
                success += 1
            else:
                print(f"  ❌ {u['openid'][:8]}... errcode={body.get('errcode')} {body.get('errmsg')}")
                fail += 1
    except Exception as e:
        print(f"  ❌ {u['openid'][:8]}... 网络错误: {e}")
        fail += 1

print(f"📊 推送完成：成功 {success}, 失败 {fail}")
EOF

echo "✅ 全部推送完成"

# ---- crontab 配置（一次性）----
# 在终端执行：crontab -e
# 加一行：
#   0 21 * * * /Users/wangliping/Public/selfProgram/ielts_apply_seek/scripts/auto/03_subscription_push.sh >> /var/log/ielts-subscription.log 2>&1
# 保存退出
# 验证：crontab -l