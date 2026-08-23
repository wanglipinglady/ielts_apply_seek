#!/usr/bin/env python3
"""IELTS Buddy · v3 用户合并 + schema 升级迁移脚本。

执行内容：
  1. 在 MySQL 上执行 schema 升级（users 表加列 + 新增 user_id_mapping）
  2. 把 web_users 已有账号合并到 users 表（按 email 本地部分作为 username）
  3. 写入 user_id_mapping 映射表
  4. web_users 行标记 is_migrated=1 + users_id

特性：
  - 幂等：重复执行不会重复迁移（检查 user_id_mapping 是否已有）
  - 可回滚：迁移前会自动 SELECT 备份到 ~/.ielts-buddy/backup_v3_*.json
  - 报告：每个 web_users 行的最终 users_id

用法：
  python scripts/migrate_v3_users_merge.py --check      # 仅检查环境，不执行
  python scripts/migrate_v3_users_merge.py --execute    # 实际执行
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import pymysql

# ===== 默认配置（与 mysql_repo.py 一致）=====
DEFAULT_HOST = "118.190.148.121"
DEFAULT_PORT = 3306
DEFAULT_USER = "remote_user"
DEFAULT_PASSWORD = "Pass@666"
DEFAULT_DB = "ietls_learn_online"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="IELTS Buddy v3 用户合并迁移")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--password", default=None,
                   help="MySQL 密码（推荐走 MYSQL_PASSWORD 环境变量）")
    p.add_argument("--database", default=DEFAULT_DB)
    p.add_argument("--check", action="store_true", help="仅检查环境，不修改")
    p.add_argument("--execute", action="store_true", help="实际执行迁移")
    p.add_argument("--backup-dir", default="~/.ielts-buddy",
                   help="备份文件目录")
    return p.parse_args()


def get_password(args) -> str:
    pwd = args.password or ""
    if not pwd:
        import os
        pwd = os.environ.get("MYSQL_PASSWORD", "")
    if not pwd:
        print("✗ 未提供 MySQL 密码。请用 --password 或环境变量 MYSQL_PASSWORD",
              file=sys.stderr)
        sys.exit(2)
    return pwd


def connect(args, pwd: str):
    return pymysql.connect(
        host=args.host, port=args.port, user=args.user, password=pwd,
        database=args.database, charset="utf8mb4", autocommit=False,
    )


def check_environment(cur) -> dict:
    """检查环境，返回当前状态字典。"""
    state = {}

    # 1. users 表是否存在
    cur.execute("SHOW TABLES LIKE 'users'")
    state["users_exists"] = cur.fetchone() is not None

    # 2. web_users 表是否存在
    cur.execute("SHOW TABLES LIKE 'web_users'")
    state["web_users_exists"] = cur.fetchone() is not None

    # 3. user_id_mapping 表是否存在
    cur.execute("SHOW TABLES LIKE 'user_id_mapping'")
    state["mapping_exists"] = cur.fetchone() is not None

    # 4. users 现有列
    if state["users_exists"]:
        cur.execute("SHOW COLUMNS FROM users")
        state["users_columns"] = [r[0] for r in cur.fetchall()]

    # 5. web_users 现有列
    if state["web_users_exists"]:
        cur.execute("SHOW COLUMNS FROM web_users")
        state["web_users_columns"] = [r[0] for r in cur.fetchall()]

    # 6. 现有数据量
    if state["users_exists"]:
        cur.execute("SELECT COUNT(*) FROM users")
        state["users_count"] = cur.fetchone()[0]
    if state["web_users_exists"]:
        cur.execute("SELECT COUNT(*) FROM web_users")
        state["web_users_count"] = cur.fetchone()[0]
    if state["mapping_exists"]:
        cur.execute("SELECT COUNT(*) FROM user_id_mapping")
        state["mapping_count"] = cur.fetchone()[0]

    # 7. web_users 已迁移数量
    if state["web_users_exists"] and "is_migrated" in state["web_users_columns"]:
        cur.execute("SELECT COUNT(*) FROM web_users WHERE is_migrated=1")
        state["already_migrated"] = cur.fetchone()[0]
    else:
        state["already_migrated"] = 0

    return state


def backup_state(cur, backup_dir: Path) -> Path:
    """把当前 users / web_users / user_id_mapping 全量备份成 JSON。"""
    backup_dir = backup_dir.expanduser()
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = backup_dir / f"backup_v3_{ts}.json"

    data = {
        "users": [],
        "web_users": [],
        "user_id_mapping": [],
        "captured_at": ts,
    }

    # users
    cur.execute("SELECT id, username, email, password_hash, display_name, "
                "created_at, last_login_at FROM users")
    for r in cur.fetchall():
        data["users"].append({
            "id": r[0], "username": r[1], "email": r[2],
            "password_hash": r[3], "display_name": r[4],
            "created_at": str(r[5]) if r[5] else None,
            "last_login_at": str(r[6]) if r[6] else None,
        })

    # web_users
    if True:
        cur.execute("SHOW COLUMNS FROM web_users")
        cols = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT * FROM web_users")
        for row in cur.fetchall():
            data["web_users"].append(dict(zip(cols, [
                str(v) if isinstance(v, datetime) else v
                for v in row
            ])))

    # user_id_mapping
    cur.execute("SHOW TABLES LIKE 'user_id_mapping'")
    if cur.fetchone():
        cur.execute("SELECT * FROM user_id_mapping")
        data["user_id_mapping"] = list(cur.fetchall())

    out.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    return out


def upgrade_schema(cur):
    """Step 1: 升级 schema（幂等）。"""
    print("\n[Step 1] 升级 schema")

    # 1.1 users 加列（若缺失）
    cur.execute("""SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'users'""")
    existing = {r[0] for r in cur.fetchall()}

    if "email" not in existing:
        print("  + users.email (VARCHAR(255) NULL)")
        cur.execute("ALTER TABLE users ADD COLUMN email VARCHAR(255) NULL AFTER username")
    else:
        print("  ✓ users.email 已存在")

    if "password_hash" not in existing:
        print("  + users.password_hash (VARCHAR(255) NULL)")
        cur.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL AFTER email")
    else:
        print("  ✓ users.password_hash 已存在")

    if "display_name" not in existing:
        print("  + users.display_name (VARCHAR(64) NULL)")
        cur.execute("ALTER TABLE users ADD COLUMN display_name VARCHAR(64) NULL AFTER password_hash")
    else:
        print("  ✓ users.display_name 已存在")

    # 1.2 users.email 唯一键（MySQL 8.0 允许多次 ADD UNIQUE，会自动跳过已存在的）
    try:
        cur.execute("ALTER TABLE users ADD UNIQUE KEY uk_users_email (email)")
        print("  + users.uk_users_email (UNIQUE)")
    except pymysql.MySQLError as e:
        if "Duplicate key name" in str(e):
            print("  ✓ users.uk_users_email 已存在")
        else:
            raise

    # 1.3 web_users 加列
    cur.execute("""SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'web_users'""")
    existing = {r[0] for r in cur.fetchall()}

    if "is_migrated" not in existing:
        print("  + web_users.is_migrated (TINYINT(1))")
        cur.execute("ALTER TABLE web_users "
                    "ADD COLUMN is_migrated TINYINT(1) NOT NULL DEFAULT 0 "
                    "AFTER last_login_at")
    else:
        print("  ✓ web_users.is_migrated 已存在")

    if "users_id" not in existing:
        print("  + web_users.users_id (BIGINT NULL)")
        cur.execute("ALTER TABLE web_users "
                    "ADD COLUMN users_id BIGINT NULL AFTER is_migrated")
    else:
        print("  ✓ web_users.users_id 已存在")

    # 1.4 web_users 索引
    try:
        cur.execute("ALTER TABLE web_users "
                    "ADD INDEX idx_web_users_migrated (is_migrated, users_id)")
        print("  + web_users.idx_web_users_migrated")
    except pymysql.MySQLError as e:
        if "Duplicate key name" in str(e):
            print("  ✓ web_users.idx_web_users_migrated 已存在")
        else:
            raise

    # 1.5 新增 user_id_mapping 表
    cur.execute("""SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'user_id_mapping'""")
    if cur.fetchone():
        print("  ✓ user_id_mapping 表已存在")
    else:
        print("  + user_id_mapping 表")
        cur.execute("""
            CREATE TABLE user_id_mapping (
                web_user_id     BIGINT          NOT NULL,
                users_id        BIGINT          NOT NULL,
                created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (web_user_id),
                KEY idx_uim_users (users_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='web_users.id ↔ users.id 映射'
        """)


def derive_username(email: str) -> str:
    """从 email 推导 username：取 @ 前的本地部分；截断到 64 字符。"""
    local = email.split("@", 1)[0]
    return local[:64] if local else "user"


def is_username_taken(cur, username: str, exclude_user_id: int = 0) -> bool:
    cur.execute("SELECT 1 FROM users WHERE username=%s AND id<>%s LIMIT 1",
                (username, exclude_user_id))
    return cur.fetchone() is not None


def migrate_web_users(cur) -> list[dict]:
    """Step 2: 把 web_users 数据合并到 users 表。

    返回迁移报告（每行：web_user_id, email, users_id, username, action）。
    action 取值:
      - created     新建 users 行
      - linked      已有同名 username 用户，关联上 email/password
      - skipped     已迁移过
    """
    print("\n[Step 2] web_users → users 合并")

    # 拿所有 web_users 行
    cur.execute("""SELECT id, email, password_hash, created_at, last_login_at,
                          is_migrated, users_id
                   FROM web_users ORDER BY id""")
    rows = cur.fetchall()
    report = []

    for web_id, email, pwd_hash, created_at, last_login_at, is_mig, users_id in rows:
        # 已迁移过：检查 users_id 是否还指向有效用户
        if is_mig and users_id is not None:
            cur.execute("SELECT username, email FROM users WHERE id=%s", (users_id,))
            existing = cur.fetchone()
            if existing:
                report.append({
                    "web_user_id": web_id, "email": email,
                    "users_id": users_id, "username": existing[0],
                    "action": "skipped",
                })
                continue

        # 需要真合并
        base_username = derive_username(email)
        username = base_username
        suffix = 1
        # 重名则加后缀
        while is_username_taken(cur, username):
            suffix += 1
            candidate = f"{base_username}_{suffix}"[:64]
            if candidate == username:  # 已经尝试到原样了，避免死循环
                candidate = f"{base_username}_{suffix}_{web_id}"[:64]
            username = candidate

        # 查 users 里是否已有同 email 用户（用户先在 web 注册过、又在 CLI 登录过）
        cur.execute("SELECT id, username FROM users WHERE email=%s", (email,))
        existing_user = cur.fetchone()

        if existing_user:
            uid, existing_username = existing_user
            # 把 password_hash 写回（CLI 没密码时覆盖为空）
            cur.execute("""UPDATE users SET password_hash=%s,
                                          last_login_at=COALESCE(%s, last_login_at)
                           WHERE id=%s""", (pwd_hash, last_login_at, uid))
            action = "linked"
        else:
            # 创建 users 行
            cur.execute("""INSERT INTO users (username, email, password_hash,
                                              created_at, last_login_at)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (username, email, pwd_hash, created_at, last_login_at))
            uid = cur.lastrowid
            existing_username = username
            action = "created"

        # 写映射表
        cur.execute("""INSERT IGNORE INTO user_id_mapping (web_user_id, users_id)
                       VALUES (%s, %s)""", (web_id, uid))

        # 回填 web_users
        cur.execute("""UPDATE web_users SET is_migrated=1, users_id=%s
                       WHERE id=%s""", (uid, web_id))

        report.append({
            "web_user_id": web_id, "email": email,
            "users_id": uid, "username": existing_username,
            "action": action,
        })

    return report


def print_report(report: list[dict]):
    if not report:
        print("  (无数据)")
        return
    print(f"  共 {len(report)} 行：")
    for r in report:
        print(f"    web_user_id={r['web_user_id']:>3} | "
              f"email={r['email']:<40} | → users_id={r['users_id']:>3} "
              f"username={r['username']:<25} | {r['action']}")


def main() -> int:
    args = parse_args()
    if not (args.check or args.execute):
        print("✗ 必须指定 --check 或 --execute", file=sys.stderr)
        return 2

    pwd = get_password(args)
    conn = connect(args, pwd)
    cur = conn.cursor()

    try:
        print(f"→ 连接 {args.user}@{args.host}:{args.port}/{args.database}")
        cur.execute("SELECT VERSION()")
        print(f"✓ MySQL 版本: {cur.fetchone()[0]}")

        state = check_environment(cur)
        print("\n[当前状态]")
        for k, v in state.items():
            print(f"  {k}: {v}")

        if args.check:
            print("\n[仅检查模式，未做任何修改]")
            return 0

        # 备份
        backup = backup_state(cur, Path(args.backup_dir))
        print(f"\n[备份] 已保存到 {backup}")

        # Step 1
        upgrade_schema(cur)
        conn.commit()

        # Step 2
        report = migrate_web_users(cur)
        conn.commit()

        print("\n[迁移报告]")
        print_report(report)

        # 校验
        print("\n[校验]")
        cur.execute("SELECT COUNT(*) FROM users")
        new_users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_id_mapping")
        mappings = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM web_users WHERE is_migrated=1")
        migrated = cur.fetchone()[0]
        print(f"  users 行数: {new_users}")
        print(f"  user_id_mapping 行数: {mappings}")
        print(f"  web_users.is_migrated=1 行数: {migrated}")

        print("\n✓ 迁移完成")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"\n✗ 失败，已回滚: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())