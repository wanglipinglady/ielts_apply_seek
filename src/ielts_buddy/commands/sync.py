"""sync 命令组：数据导出同步 + v3 MySQL↔SQLite 双向同步。"""

from __future__ import annotations

import sys
import threading
import time

import click
from rich.console import Console

from ielts_buddy.services.sync_service import SyncService

console = Console()


@click.group("sync")
def sync():
    """数据同步/导出命令（含 v3 MySQL↔SQLite 双向同步）"""


@sync.command()
def vocab():
    """导出词库（含掌握状态）"""
    svc = SyncService()
    path = svc.export_vocab()
    console.print(f"[green]词库已导出:[/green] {path}")


@sync.command()
def records():
    """导出学习记录"""
    svc = SyncService()
    path = svc.export_records()
    console.print(f"[green]学习记录已导出:[/green] {path}")


@sync.command()
def stats():
    """导出统计摘要"""
    svc = SyncService()
    path = svc.export_stats()
    console.print(f"[green]统计摘要已导出:[/green] {path}")


@sync.command("all")
def sync_all():
    """导出全部数据"""
    svc = SyncService()
    paths = svc.export_all()
    console.print("[green]全部数据已导出:[/green]")
    for name, path in paths.items():
        console.print(f"  {name}: {path}")


# =============================================================
# v3：MySQL↔SQLite 双向同步守护进程
# =============================================================


@sync.command("daemon")
@click.option("--interval", default=30, show_default=True,
              help="同步间隔（秒）")
def sync_daemon(interval: int):
    """v3：启动 MySQL↔SQLite 双向同步守护进程。

    按 ``--interval`` 秒间隔执行 push + pull。Ctrl+C 退出。

    使用场景：
      - CLI 端长期开启（如 ib sync daemon & 在后台跑）
      - Web 端一般不直接用——web 启动时已经自动开启 asyncio 版本

    注意：
      - 在线模式才生效；fallback_sqlite 模式下不会推送任何数据
      - 守护进程是 daemon 线程，主进程退出时自动结束
    """
    from ielts_buddy.commands.db_status import _build_container
    from ielts_buddy.services.sync import SyncWorker

    container = _build_container()
    worker = SyncWorker(container)
    stop_event = threading.Event()

    def _loop():
        console.print(f"[green]✓ 同步守护进程已启动（间隔 {interval}s），"
                      f"按 Ctrl+C 退出[/green]")
        while not stop_event.is_set():
            try:
                result = worker.sync_once()
                if result.total or result.errors:
                    console.print(f"[dim]{time.strftime('%H:%M:%S')} "
                                  f"sync: {result}[/dim]")
                    for err in result.errors:
                        console.print(f"  [red]{err}[/red]")
            except Exception as e:
                console.print(f"[red]sync 异常: {e}[/red]")
            if stop_event.wait(interval):
                break
        console.print("[yellow]同步守护进程已停止[/yellow]")

    t = threading.Thread(target=_loop, daemon=True, name="ib-sync-daemon")
    t.start()
    try:
        # 主线程挂住，daemon 线程在后台跑
        while not stop_event.is_set():
            stop_event.wait(60)
    except KeyboardInterrupt:
        console.print("\n[yellow]收到 Ctrl+C，正在停止守护进程...[/yellow]")
        stop_event.set()
        t.join(timeout=2)
        container.close()
        sys.exit(0)
