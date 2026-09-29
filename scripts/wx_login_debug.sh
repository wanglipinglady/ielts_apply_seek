#!/usr/bin/env bash
# WX_LOGIN_DEBUG.sh — 微信登录 400 错误诊断脚本
# 用法：bash wx_login_debug.sh
# 跑完后把整个输出发给 AI

set +e

echo "============================================================"
echo "1. 后端日志（最近 30 行，找 code2session 错误）"
echo "============================================================"
sudo journalctl -u ielts-web -n 30 --no-pager | tail -30
echo ""

echo "============================================================"
echo "2. .env 里微信配置（重点看 SECRET 是否占位符）"
echo "============================================================"
grep -E "WECHAT|APPID|SECRET" /opt/ielts_apply_seek/.env 2>&1
echo ""

echo "============================================================"
echo "3. 手动测 code2session（模拟微信服务端）"
echo "============================================================"
source /opt/ielts_apply_seek/.venv/bin/activate

# 从 .env 读 APPID 和 SECRET
APPID=$(grep "^IELTS_BUDDY_WECHAT_APPID=" /opt/ielts_apply_seek/.env | cut -d= -f2)
SECRET=$(grep "^IELTS_BUDDY_WECHAT_SECRET=" /opt/ielts_apply_seek/.env | cut -d= -f2)

echo "APPID='$APPID' (长度: ${#APPID})"
echo "SECRET='$SECRET' (长度: ${#SECRET})"
echo ""

# 检查 SECRET 是否是占位符
if [[ "$SECRET" == "在这里粘贴你的AppSecret" ]] || [[ -z "$SECRET" ]]; then
    echo "❌ SECRET 是占位符或空！"
    echo "    必须去公众平台生成 AppSecret，然后填到这里"
    echo ""
    echo "生成 AppSecret 步骤："
    echo "  1. https://mp.weixin.qq.com → 登录"
    echo "  2. 开发管理 → 开发设置 → 开发者凭证"
    echo "  3. 点「生成」（需要管理员扫码）"
    echo "  4. 复制 32 位字符"
    echo "  5. 替换 /opt/ielts_apply_seek/.env 里的占位符"
    echo ""
elif [[ ${#SECRET} -lt 30 ]]; then
    echo "⚠️ SECRET 长度异常（${#SECRET} 字符），正常应该是 32 位"
    echo ""
else
    echo "✅ SECRET 长度看起来正常"
fi
echo ""

# 测试 code2session（用 test_code 触发错误）
python3 << PYEOF
import requests
import os

APPID = "$APPID"
SECRET = "$SECRET"

print(f"APPID='$APPID'")
print(f"SECRET='{SECRET[:10]}...' (隐藏前 10 字符后)")
print("")

if not APPID or not SECRET:
    print("❌ APPID 或 SECRET 为空，无法测试")
    print("    请检查 .env 配置")
else:
    url = (
        f"https://api.weixin.qq.com/sns/jscode2session"
        f"?appid={APPID}&secret={SECRET}"
        f"&js_code=test_code_xxx&grant_type=authorization_code"
    )
    
    print(f"调用: {url.replace(SECRET, 'SECRET')}")
    
    try:
        resp = requests.get(url, timeout=10)
        print(f"\nHTTP {resp.status_code}")
        print(f"Body: {resp.text}")
        
        data = resp.json()
        if data.get("errcode") == 40013:
            print("\n❌ errcode=40013: invalid appid（AppID 错）")
        elif data.get("errcode") == 40125:
            print("\n❌ errcode=40125: invalid appsecret（AppSecret 错）")
        elif data.get("errcode") == 40029:
            print("\n✅ errcode=40029: invalid code（但 AppID+Secret 对）")
            print("   → 说明 AppID 和 Secret 配置正确，问题在 wx.login() 拿的 code")
        elif data.get("errcode") == 0:
            print("\n✅ errcode=0: 成功（但 test_code 应该无效才对）")
        else:
            print(f"\n⚠️ 其他错误: {data}")
    except Exception as e:
        print(f"\n❌ 调用失败: {e}")
PYEOF

echo ""
echo "============================================================"
echo "4. 验证后端是否能从环境变量读到配置"
echo "============================================================"
python3 << PYEOF
import os

# 模拟 uvicorn 启动时的读取
os.environ.setdefault("IELTS_BUDDY_WEB_DB_MODE", "online")
# 真实读 .env 文件
env_path = "/opt/ielts_apply_seek/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key] = val

from ielts_buddy.web.config import WECHAT_APPID, WECHAT_SECRET, WECHAT_DEV_ALLOW_MOCK

print(f"WECHAT_APPID loaded: '{WECHAT_APPID}' (长度: {len(WECHAT_APPID)})")
print(f"WECHAT_SECRET loaded: '{WECHAT_SECRET[:10]}...' (长度: {len(WECHAT_SECRET)})")
print(f"WECHAT_DEV_ALLOW_MOCK: {WECHAT_DEV_ALLOW_MOCK}")

if not WECHAT_APPID:
    print("\n❌ APPID 没读到！.env 配置有问题")
if not WECHAT_SECRET:
    print("\n❌ SECRET 没读到！.env 配置有问题")
PYEOF

echo ""
echo "============================================================"
echo "5. 直接测试 /api/wx/login 端点"
echo "============================================================"
curl -s -X POST https://ielts.wanglipingresume.com/api/wx/login \
  -H "Content-Type: application/json" \
  -d '{"code":"test_code"}' | python3 -m json.tool

echo ""
echo "============================================================"
echo "诊断完成"
echo "============================================================"
<!-- v1 -->
