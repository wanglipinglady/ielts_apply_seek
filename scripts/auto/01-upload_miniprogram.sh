#!/usr/bin/env bash
# scripts/auto/01-upload_miniprogram.sh
# ------------------------------------------------------------------------------
# 用途：用微信开发者工具 CLI 自动上传小程序代码 + 提交审核（可选）
# 一次性配置：装好 @miniprogram/miniprogram-ci + 配置小程序代码上传密钥
# 之后每次跑就一行命令，不用打开开发者工具点 50 下按钮
#
# 前置（一次性配置）：
#   1. 装 Node.js（macOS: brew install node）
#   2. 在小程序后台：开发管理 → 开发设置 → 小程序代码上传 → 生成密钥
#      下载 miniprogram_private_key.pem + 记下 AppID
#   3. 在 CI 密钥管理或 ~/.bashrc 加：
#        export WECHAT_MINIPROGRAM_APPID="wx286309bc641b1d79"
#        export WECHAT_MINIPROGRAM_KEY_PATH="/Users/wangliping/.../private_key.pem"
#   4. 装 miniprogram-ci：
#        npm install -g @miniprogram/miniprogram-ci
#
# 用法：
#   ./scripts/auto/01-upload_miniprogram.sh                # 默认体验版
#   ./scripts/auto/01-upload_miniprogram.sh --review        # 体验版 + 提交审核
#   ./scripts/auto/01-upload_miniprogram.sh --version 1.0.1 # 指定版本号
# ------------------------------------------------------------------------------
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 默认参数
VERSION="${VERSION:-1.0.0}"
DESC="${DESC:-auto-uploaded by CI}"
REVIEW=false
QRCODE_PATH="${QRCODE_PATH:-$PROJECT_ROOT/docs/miniprogram/_assets/qrcode.png}"

# 解析参数
for arg in "$@"; do
  case "$arg" in
    --review) REVIEW=true ;;
    --version) shift; VERSION="$1"; shift ;;
    --desc) shift; DESC="$1"; shift ;;
    --qrcode) shift; QRCODE_PATH="$1"; shift ;;
    --help)
      echo "用法: $0 [--review] [--version V] [--desc D] [--qrcode PATH]"
      exit 0
      ;;
    *) echo "未知参数: $arg"; exit 1 ;;
  esac
done

# 检查环境变量
if [ -z "$WECHAT_MINIPROGRAM_APPID" ]; then
  echo "❌ 错误：WECHAT_MINIPROGRAM_APPID 未设置"
  echo "   在 ~/.bashrc 加：export WECHAT_MINIPROGRAM_APPID=wx286309bc641b1d79"
  exit 1
fi
if [ -z "$WECHAT_MINIPROGRAM_KEY_PATH" ]; then
  echo "❌ 错误：WECHAT_MINIPROGRAM_KEY_PATH 未设置"
  echo "   在 ~/.bashrc 加：export WECHAT_MINIPROGRAM_KEY_PATH=/path/to/private_key.pem"
  exit 1
fi

# 编译小程序产物（miniprogram-ci 内置，无需额外工具）
echo "📦 开始上传小程序..."
echo "   AppID: $WECHAT_MINIPROGRAM_APPID"
echo "   版本: $VERSION"
echo "   描述: $DESC"
echo "   项目目录: $PROJECT_ROOT/miniprogram"

miniprogram-ci upload \
  --pp "$PROJECT_ROOT/miniprogram" \
  --pkp "$WECHAT_MINIPROGRAM_KEY_PATH" \
  --appid "$WECHAT_MINIPROGRAM_APPID" \
  --uv "$VERSION" \
  --ud "$DESC" \
  --qrcode "$QRCODE_PATH" \
  --use

echo ""
echo "✅ 上传成功！"
echo "   二维码已保存到：$QRCODE_PATH"

if [ "$REVIEW" = true ]; then
  echo ""
  echo "📝 提交审核中..."
  miniprogram-ci submit-audit \
    --pkp "$WECHAT_MINIPROGRAM_KEY_PATH" \
    --appid "$WECHAT_MINIPROGRAM_APPID"
  echo "✅ 审核提交完成！请在微信公众平台查看进度。"
fi