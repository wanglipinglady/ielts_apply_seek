#!/usr/bin/env python3
"""IELTS Buddy · MySQL 初始化执行器

作用：
  1. 测试与 118.190.148.121:3306 的连通性
  2. 选中 ietls_learn_online 库（不存在则提示手动 CREATE DATABASE）
  3. 执行 scripts/init_mysql.sql 中的所有 DDL / 种子数据
  4. 验证：列出所有表 + 关键种子行

用法：
  pip install pymysql cryptography
  python scripts/init_mysql.py                       # 走默认连接
  python scripts/init_mysql.py --password "Pass@666" # 显式传密码
  python scripts/init_mysql.py --check-only          # 只检查，不执行 DDL
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import pymysql
except ImportError:
    print("缺少 pymysql，请先：pip install pymysql cryptography", file=sys.stderr)
    sys.exit(2)


# ---- 默认连接信息（与 init_mysql.sql 头部一致） ----
DEFAULT_HOST = "118.190.148.121"
DEFAULT_PORT = 3306
DEFAULT_USER = "remote_user"
DEFAULT_DB = "ietls_learn_online"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="IELTS Buddy MySQL 初始化")
    p.add_argument("--host", default=DEFAULT_HOST, help=f"主机 (默认 {DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口 (默认 {DEFAULT_PORT})")
    p.add_argument("--user", default=DEFAULT_USER, help=f"用户名 (默认 {DEFAULT_USER})")
    p.add_argument("--password", default=None, help="密码（推荐走环境变量 MYSQL_PASSWORD）")
    p.add_argument("--database", default=DEFAULT_DB, help=f"目标库 (默认 {DEFAULT_DB})")
    p.add_argument("--check-only", action="store_true", help="只检查连通性，不执行 DDL")
    p.add_argument("--sql-file", default=None, help="指定 SQL 文件路径（默认同目录 init_mysql.sql）")
    return p.parse_args()


def split_sql_statements(sql: str) -> list[str]:
    """拆分 SQL 文件为单条语句（处理注释、SET 语句、语句结束分号）。

    这里只做最简拆分：
      - 删除 -- 单行注释
      - 删除 /* */ 多行注释
      - 按 ; 切分
      - 跳过空语句
    """
    # 删注释
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    # 切分
    parts = [p.strip() for p in sql.split(";")]
    return [p for p in parts if p]


def test_connection(host: str, port: int, user: str, password: str, database: str) -> pymysql.Connection:
    """测试连通性并返回连接。"""
    print(f"→ 测试连接 {user}@{host}:{port}/{database} ...")
    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            charset="utf8mb4",
            connect_timeout=5,
            autocommit=False,
        )
    except pymysql.MySQLError as e:
        print(f"✗ 连接失败：{e}", file=sys.stderr)
        print("\n排查方向：", file=sys.stderr)
        print(f"  1. 网络可达？ ping {host}", file=sys.stderr)
        print(f"  2. 端口开放？ telnet {host} {port}", file=sys.stderr)
        print(f"  3. 凭据正确？ 用户 {user} 密码是否匹配", file=sys.stderr)
        print(f"  4. 库存在？ SHOW DATABASES 是否含 {database}", file=sys.stderr)
        sys.exit(1)

    with conn.cursor() as cur:
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        print(f"✓ 连接成功，MySQL 版本：{version}")

        cur.execute("SHOW DATABASES LIKE %s", (database,))
        if cur.fetchone() is None:
            print(f"✗ 库 '{database}' 不存在", file=sys.stderr)
            print(f"  请先在 MySQL 中执行：CREATE DATABASE {database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
                  file=sys.stderr)
            sys.exit(1)
        print(f"✓ 库 '{database}' 存在")

    conn.select_db(database)
    return conn


def run_sql_file(conn: pymysql.Connection, sql_path: Path) -> None:
    """读取 SQL 文件并逐条执行。"""
    print(f"\n→ 执行 {sql_path.name} ...")
    sql = sql_path.read_text(encoding="utf-8")
    statements = split_sql_statements(sql)
    print(f"  共 {len(statements)} 条语句")

    success = 0
    failed = []
    with conn.cursor() as cur:
        for i, stmt in enumerate(statements, 1):
            # 取前 70 字符做日志（去掉换行）
            preview = " ".join(stmt.split())[:70]
            try:
                cur.execute(stmt)
                success += 1
            except pymysql.MySQLError as e:
                failed.append((i, preview, str(e)))
                print(f"  [{i:02d}] ✗ {preview} ...  错误：{e}")
                # 失败立即停止（避免后续语句依赖失败的结果）
                conn.rollback()
                print(f"\n✗ 执行中断，已回滚", file=sys.stderr)
                sys.exit(1)

        conn.commit()
    print(f"✓ 全部 {success} 条语句执行成功")


def verify(conn: pymysql.Connection) -> None:
    """验证：表结构 + 种子数据。"""
    print("\n→ 验证结果：")
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        # 1. 表清单
        cur.execute("SHOW TABLES")
        tables = [list(row.values())[0] for row in cur.fetchall()]
        expected = {
            "users", "learning_records", "personal_vocab", "vocab_categories",
            "vocab_category_words", "exam_sessions", "grade_history",
            "vocab_cache", "cache_meta",
        }
        actual = set(tables)
        missing = expected - actual
        print(f"  表数量：{len(tables)}（期望 9）")
        if missing:
            print(f"  ✗ 缺失表：{missing}", file=sys.stderr)
            sys.exit(1)
        print(f"  ✓ 全部 9 张表已创建")

        # 2. 种子分类
        cur.execute("SELECT id, user_id, name, is_system FROM vocab_categories")
        cats = cur.fetchall()
        seed = [c for c in cats if c["user_id"] == 0]
        print(f"  种子分类数量：{len(seed)}（期望 2）")
        if len(seed) != 2:
            print(f"  ✗ 种子分类数量不对：{cats}", file=sys.stderr)
            sys.exit(1)
        names = {c["name"] for c in seed}
        assert names == {"favorites", "mistakes"}, f"种子名称错误：{names}"
        print(f"  ✓ 种子分类齐全：{names}")

        # 3. 缓存元数据
        cur.execute("SELECT * FROM cache_meta")
        meta = cur.fetchall()
        print(f"  cache_meta 行数：{len(meta)}（期望 2）")
        assert len(meta) == 2, f"cache_meta 行数错误：{len(meta)}"

        # 4. users 表初始为空
        cur.execute("SELECT COUNT(*) AS cnt FROM users")
        cnt = cur.fetchone()["cnt"]
        print(f"  users 表当前行数：{cnt}（期望 0）")
        assert cnt == 0, f"users 表不应有数据，当前 {cnt} 行"

    print("\n✓ 全部验证通过！数据库已就绪。")


def main() -> int:
    args = parse_args()

    # 密码优先走环境变量
    password = args.password or ""
    if not password:
        import os
        password = os.environ.get("MYSQL_PASSWORD", "")
    if not password:
        print("错误：未提供密码。请用 --password 或设置环境变量 MYSQL_PASSWORD",
              file=sys.stderr)
        return 2

    # 定位 SQL 文件
    sql_path = Path(args.sql_file) if args.sql_file else (
        Path(__file__).resolve().parent / "init_mysql.sql"
    )
    if not sql_path.exists():
        print(f"✗ SQL 文件不存在：{sql_path}", file=sys.stderr)
        return 2

    # 1. 连通性
    conn = test_connection(args.host, args.port, args.user, password, args.database)

    try:
        if args.check_only:
            print("\n✓ 仅检查模式，跳过 DDL 执行")
            return 0

        # 2. 执行 DDL
        run_sql_file(conn, sql_path)

        # 3. 验证
        verify(conn)

        print("\n" + "=" * 60)
        print("下一步：在 ielts-buddy 项目里")
        print("  pip install pymysql cryptography sqlalchemy")
        print("  # 等 W1~W3 完成代码后，再用 ib --mode remote 测试")
        print("=" * 60)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
