"""生成强随机密钥（用于 .env）。

**用途**：替换已泄露的 ``IELTS_BUDDY_JWT_SECRET`` 和 ``IELTS_BUDDY_ADMIN_RESET_TOKEN``。

**为何需要**：你的 .env 中 ``IELTS_BUDDY_JWT_SECRET`` 之前已被 git 追踪并推送到 GitHub。
虽然现在已 .gitignore + ``git rm --cached``，但**历史 commit 里仍然能看到密钥**。

唯一的彻底修复是：**轮换密钥**（生成新的，废弃旧的）。

用法：
    python -m ielts_buddy.web.tools.regen_secrets
"""
from __future__ import annotations

import secrets
import sys


def main() -> int:
    print("=" * 60)
    print("生成强随机密钥（请复制到 .env，覆盖旧值）")
    print("=" * 60)
    print()
    print("# === IELTS_BUDDY_JWT_SECRET（≥ 32 字符）===")
    jwt_secret = secrets.token_urlsafe(48)
    print(f"IELTS_BUDDY_JWT_SECRET={jwt_secret}")
    print(f"  长度: {len(jwt_secret)} 字符")
    print()
    print("# === IELTS_BUDDY_ADMIN_RESET_TOKEN ===")
    admin_token = secrets.token_urlsafe(32)
    print(f"IELTS_BUDDY_ADMIN_RESET_TOKEN={admin_token}")
    print(f"  长度: {len(admin_token)} 字符")
    print()
    print("=" * 60)
    print("⚠️  重要：轮换 JWT_SECRET 后，所有现有 token 会失效，")
    print("    用户需要重新登录。这是正常且必要的安全措施。")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())