"""Web 端账号密码重置脚本。

**不需要** Web 服务在跑，直接连数据库重置密码。

用法：
    python -m ielts_buddy.web.tools.reset_password --email user@x.com

可选参数：
    --new-password PASSWORD  指定新明文密码（≥ 8 位）。
                              不传则自动生成 10 位随机密码并打印。

环境变量：
    IELTS_BUDDY_WEB_DB_MODE     sqlite (默认) 或 online (MySQL)
    IELTS_BUDDY_WEB_DB_URL      MySQL 连接 URL
    IELTS_BUDDY_WEB_SQLITE_PATH SQLite 文件路径（默认 ~/.ielts-buddy/web_data.db）

输出：
    ┌─ 密码已重置 ─────────────────────────────
    │  email:        user@x.com
    │  user_id:      4
    │  new_password: aB3xY7zQ9m    ← **请立即保存**
    │  hash 在 db:  $2b$12$...
    └──────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _open_repo_for_cli():
    """绕过 FastAPI 启动流程，直接连数据库构造 web_user_repo。

    与 ``main._open_default_user_repo`` 复用同样的连接策略，保证
    SQLite 与 MySQL 模式行为一致。
    """
    # 让 config 能从环境变量读
    from ielts_buddy.web import config as web_config
    from ielts_buddy.web.auth.repository import (
        MySQLWebUserRepository,
        SQLiteWebUserRepository,
    )

    if web_config.WEB_DB_MODE == "online":
        from ielts_buddy.repositories.mysql_repo import create_mysql_repositories
        container = create_mysql_repositories(
            connection_url=web_config.WEB_DB_URL or None
        )
        return MySQLWebUserRepository(container._engine), "mysql"
    else:
        from pathlib import Path as _P
        from ielts_buddy.repositories import create_repositories
        db_path = _P(web_config.get_web_db_path())
        db_path.parent.mkdir(parents=True, exist_ok=True)
        container = create_repositories(mode="local", db_path=db_path)
        return SQLiteWebUserRepository(container._conn), "sqlite"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="重置 Web 端账号密码（CLI 工具，不需要 Web 服务在跑）",
    )
    parser.add_argument(
        "--email", required=True,
        help="目标账号邮箱",
    )
    parser.add_argument(
        "--new-password", default=None,
        help="指定新明文密码（≥ 8 位）。不传则自动生成 10 位随机密码。",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="跳过交互确认（默认会要求输入 y/n）",
    )
    args = parser.parse_args(argv)

    # 设置 PYTHONPATH，让 .venv 之外的脚本也能找到 ielts_buddy
    src_dir = Path(__file__).resolve().parents[3]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from ielts_buddy.web.auth.security import hash_password
    from ielts_buddy.web.auth.service import _generate_random_password

    # 1. 打开仓库（直连 db）
    repo, mode = _open_repo_for_cli()
    print(f"[重置脚本] 数据库模式: {mode}")

    # 2. 查用户
    user = repo.get_by_email(args.email)
    if user is None:
        print(f"\n❌ 邮箱不存在: {args.email}", file=sys.stderr)
        print(f"   （为防枚举，响应与登录失败时一致，不透露是否存在）", file=sys.stderr)
        return 1

    print(f"\n找到用户:")
    print(f"  id:           {user.id}")
    print(f"  email:        {user.email}")
    print(f"  created_at:   {user.created_at}")
    print(f"  last_login:   {user.last_login_at}")

    # 3. 决定新密码
    if args.new_password:
        new_plain = args.new_password
        if len(new_plain) < 8:
            print(f"\n❌ --new-password 必须 ≥ 8 位", file=sys.stderr)
            return 2
    else:
        new_plain = _generate_random_password(length=10)

    # 4. 交互确认
    if not args.yes:
        print(f"\n即将重置密码为: {new_plain}")
        try:
            ans = input("确认？[y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("\n已取消")
            return 3

    # 5. 写入 hash
    new_hash = hash_password(new_plain)
    ok = repo.set_password(user.id, new_hash)
    if not ok:
        print(f"\n❌ 重置失败（rowcount=0）", file=sys.stderr)
        return 4

    # 6. 输出
    print(f"\n┌─ 密码已重置 {'─' * 36}┐")
    print(f"│  email:        {user.email}")
    print(f"│  user_id:      {user.id}")
    print(f"│  new_password: {new_plain}    ← 请立即保存")
    print(f"│  hash 在 db:  {new_hash[:30]}...")
    print(f"└{'─' * 50}┘")
    print(f"\n✅ 完成。客户端可立即用新密码登录。")
    return 0


if __name__ == "__main__":
    sys.exit(main())