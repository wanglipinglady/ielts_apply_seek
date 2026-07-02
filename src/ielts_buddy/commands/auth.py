"""auth 命令组：用户登录 / 查看 / 登出。

W6 阶段：
- ib login <username>：调用 AuthService.login，session 写入 ~/.ielts-buddy/session.json
- ib whoami：显示当前 session
- ib logout：删除 session.json
"""

from __future__ import annotations

import click
from rich.console import Console

from ielts_buddy.services.auth_service import AuthService

console = Console()


@click.group("auth")
def auth():
    """用户登录与会话管理"""


@auth.command()
@click.argument("username")
@click.option(
    "-m",
    "--mode",
    type=click.Choice(["local", "online"]),
    default=None,
    help="数据源模式（默认走 config）",
)
def login(username: str, mode: str | None):
    """登录并保存会话到本地"""
    try:
        svc = AuthService(mode=mode)
        result = svc.login(username)
    except ValueError as e:
        console.print(f"[red]登录失败: {e}[/red]")
        raise click.Abort() from e
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]登录失败: {e}[/red]")
        raise click.Abort() from e

    mode_label = result["mode"]
    uid = result["user_id"]
    console.print(
        f"[green]登录成功[/green]  "
        f"user_id=[bold cyan]{uid}[/bold cyan]  "
        f"username=[bold]{result['username']}[/bold]  "
        f"mode=[yellow]{mode_label}[/yellow]"
    )
    if mode_label == "local":
        console.print(
            "[dim]提示：单机模式下 user_id 始终为 1，username 仅作展示。[/dim]"
        )


@auth.command("whoami")
def whoami_cmd():
    """显示当前登录信息"""
    svc = AuthService()
    info = svc.whoami()
    if info is None:
        console.print("[yellow]当前未登录[/yellow]  请先执行 `ib login <username>`")
        raise click.Abort()

    console.print("[bold]当前登录信息[/bold]")
    console.print(f"  user_id       : [cyan]{info.get('user_id')}[/cyan]")
    console.print(f"  username      : [green]{info.get('username')}[/green]")
    console.print(f"  mode          : [yellow]{info.get('mode')}[/yellow]")
    console.print(f"  logged_in_at  : [dim]{info.get('logged_in_at')}[/dim]")
    console.print(f"  last_login_at : [dim]{info.get('last_login_at')}[/dim]")


@auth.command()
@click.confirmation_option(prompt="确认登出？")
def logout():
    """登出（删除本地 session.json）"""
    svc = AuthService()
    if svc.logout():
        console.print("[green]已登出[/green]")
    else:
        console.print("[dim]当前未登录，无需登出[/dim]")
