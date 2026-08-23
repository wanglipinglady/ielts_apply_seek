"""db-status 命令组（v3）：展示 MySQL↔SQLite 同步状态。"""
from __future__ import annotations

import asyncio
import click
from rich.console import Console
from rich.table import Table

from ielts_buddy.repositories import create_repositories
from ielts_buddy.repositories.fallback_repo import create_fallback_container
from ielts_buddy.services.sync import SyncWorker

console = Console()


def _build_container():
    """CLI 端构造一个 FallbackContainer（按当前 mode）。"""
    from ielts_buddy.core.config import get_app_dir, get_db_path, get_mode, Config
    from pathlib import Path

    cfg = Config()
    mode = get_mode(cfg)
    sqlite_path = Path(get_db_path())

    # 统一 mysql_url（MySQL 模式下 Config.get_mysql_url() 返回的就是 URL）
    mysql_url = cfg.get("database.mysql_url", "") if mode == "online" else ""
    prefer_mode = "online" if mode == "online" else "sqlite"

    return create_fallback_container(
        sqlite_db_path=sqlite_path,
        mysql_url=mysql_url,
        prefer_mode=prefer_mode,
    )


@click.group("db-status")
def db_status():
    """v3 数据库状态命令：展示 MySQL↔SQLite 同步情况。"""


@db_status.command("show")
def show():
    """展示当前 backend 状态 + 上次同步时间 + pending_upload 计数。"""
    container = _build_container()

    try:
        # 强制 ping MySQL 更新可达性
        container.try_mysql()

        info = {
            "current_mode": container.current_mode,
            "mysql_reachable": container.mysql_reachable,
            "online_attached": container.online is not None,
        }

        # 从 sync_meta 读上次同步时间
        sqlite_conn = container.offline._conn
        cur = sqlite_conn.execute(
            "SELECT last_pull_at, last_push_at, last_error, last_error_at "
            "FROM sync_meta WHERE id=1"
        )
        row = cur.fetchone()
        if row:
            info["last_pull_at"] = row[0] or "(never)"
            info["last_push_at"] = row[1] or "(never)"
            info["last_error"] = row[2] or ""
            info["last_error_at"] = row[3] or ""

        # 各表 pending_upload 计数
        info["pending_upload"] = {}
        for tbl in [
            "personal_vocab", "learning_records", "vocab_categories",
            "vocab_category_words", "exam_sessions", "grade_history",
            "articles",
        ]:
            try:
                cur = sqlite_conn.execute(
                    f"SELECT COUNT(*) FROM {tbl} WHERE sync_status='pending_upload'"
                )
                info["pending_upload"][tbl] = cur.fetchone()[0]
            except Exception:
                info["pending_upload"][tbl] = "(schema missing)"

        # 渲染
        console.print(f"\n[bold]DB Mode:[/bold] {info['current_mode']}")
        console.print(f"[bold]MySQL 可达:[/bold] "
                      f"{'✓' if info['mysql_reachable'] else '✗'}")
        console.print(f"[bold]MySQL container:[/bold] "
                      f"{'attached' if info['online_attached'] else 'None'}")
        console.print()
        console.print("[bold]上次同步:[/bold]")
        console.print(f"  pull: {info.get('last_pull_at', '?')}")
        console.print(f"  push: {info.get('last_push_at', '?')}")
        if info.get("last_error"):
            console.print(f"  [red]last_error:[/red] {info['last_error']}")
            console.print(f"  [red]last_error_at:[/red] {info.get('last_error_at')}")
        console.print()

        t = Table(title="pending_upload 计数")
        t.add_column("表", style="cyan")
        t.add_column("行数", justify="right")
        for tbl, cnt in info["pending_upload"].items():
            t.add_row(tbl, str(cnt))
        console.print(t)

    finally:
        container.close()


@db_status.command("sync-now")
def sync_now():
    """立即触发一次同步。"""
    container = _build_container()
    try:
        worker = SyncWorker(container)
        result = worker.sync_once()
        console.print(f"\n[bold]同步结果:[/bold] {result}")
        if result.errors:
            for err in result.errors:
                console.print(f"  [red]{err}[/red]")
    finally:
        container.close()


__all__ = ["db_status"]