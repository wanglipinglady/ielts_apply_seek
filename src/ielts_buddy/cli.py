"""IELTS LEARNING SEEK -  CLI 入口"""

import os

import click
from rich.console import Console

from ielts_buddy.commands.deploy import deploy
from ielts_buddy.commands.email import email
from ielts_buddy.commands.exam import exam
from ielts_buddy.commands.feishu import feishu
from ielts_buddy.commands.grade import grade
from ielts_buddy.commands.recommend import recommend
from ielts_buddy.commands.listen import listen
from ielts_buddy.commands.plan import plan
from ielts_buddy.commands.report import report
from ielts_buddy.commands.speak import speak
from ielts_buddy.commands.stats import stats
from ielts_buddy.commands.sync import sync
from ielts_buddy.commands.vocab import vocab
from ielts_buddy.commands.write import write
from ielts_buddy.commands.course import course
from ielts_buddy.commands.auth import auth


def _show_daily_reminder():
    """显示每日学习提醒（仅在设置了学习计划时显示）"""
    try:
        from ielts_buddy.core.config import get_app_dir

        plan_path = get_app_dir() / "plan.json"
        if not plan_path.exists():
            return

        from ielts_buddy.services.plan_service import PlanService
        from ielts_buddy.services.stats_service import StatsService

        plan_svc = PlanService()
        plan_data = plan_svc.get_plan()
        if plan_data is None:
            return

        stats_svc = StatsService()
        due = stats_svc.due_count()
        today = stats_svc.today_stats()
        stats_svc.close()

        suggested = max(0, plan_data.daily_new - today["new_words"])
        parts = []
        if due > 0:
            parts.append(f"待复习: {due}")
        if suggested > 0:
            parts.append(f"建议新学: {suggested}")

        if parts:
            console = Console(stderr=True)
            console.print(f"[dim]-- {' | '.join(parts)} --[/dim]")
    except Exception:
        pass  # 静默失败，不影响正常使用


def _show_current_user(invoked: str) -> None:
    """在每个子命令前显示当前用户；auth 子命令自身负责显示所以跳过。

    静默失败：不连 DB、不创建容器，仅读 ~/.ielts-buddy/session.json。

    默认情况下 banner 总是输出。W6 引入的 banner 会污染老 CLI 测试的
    output 断言，所以新增了显式开关：

    - IELTS_BUDDY_NO_BANNER=1   关闭 banner（CI / 老测试用）
    - 默认（变量未设）         开启 banner（终端用户）

    W8 阶段升级：未登录 + online 模式 → SystemExit(1) 阻断（保护 MySQL 的
    system seed user_id=1 不被匿名用户污染）；未登录 + local 模式 → 软提示
    banner 后继续（W7 既有行为）。
    """
    import os
    import sys
    # auth 子命令自己会打印用户信息，避免重复
    # invoked 是 group 名（auth），不一定是子命令（login/logout/whoami）
    if invoked == "auth":
        return
    if os.environ.get("IELTS_BUDDY_NO_BANNER", "").strip() in ("1", "true", "yes"):
        return
    try:
        from ielts_buddy.core.config import Config, get_app_dir, get_mode
        from ielts_buddy.services.auth_service import AuthService

        cfg = Config()
        mode = get_mode(cfg)
        session_path = get_app_dir() / "session.json"
        svc = AuthService(session_path=session_path, config=cfg, mode=mode)
        info = svc.whoami()
        svc.close()
        if info is None:
            # W8：未登录 + online 模式 → 硬退出（保护 MySQL 的 user_id=1）
            if mode == "online":
                console = Console(stderr=True)
                console.print(
                    "[red]在线模式需要先登录。执行 `ib auth login <username>` 后重试。[/red]"
                )
                sys.exit(1)
            # W7 既有：未登录 + local 模式 → 软提示 banner，继续
            console = Console(stderr=True)
            console.print(
                "[dim]-- 未登录：数据默认保存到 user_id=1 --"
                "（执行 `ib login <username>` 登录后切换）--[/dim]"
            )
            return
        console = Console(stderr=True)
        console.print(
            f"[dim]-- 当前用户: {info.get('username')} "
            f"(id={info.get('user_id')}, mode={info.get('mode')}) --[/dim]"
        )
    except Exception:
        pass  # 静默失败


# _MODE_STATE 在 W10 替代 W9 的 _MODE_ENV_BACKUP 机制。
# click result_callback 没有 ctx 参数，只能用模块级 dict 暂存。
# pytest 用 CliRunner 跑测试时，每个 CliRunner.invoke() 在子进程里完成，
# 模块级 dict 不会跨测试污染（每个 pytest 测试都是独立 CliRunner.invoke，
# 各自完成 env 设置 + result_callback 还原）。
_MODE_STATE = {"set": False, "added": False, "old": ""}


@click.group()
@click.version_option(version="0.1.0", prog_name="ielts-learning-seek")
@click.option(
    "--mode",
    type=click.Choice(["local", "online"], case_sensitive=False),
    default=None,
    help="数据源模式（local=SQLite / online=MySQL）。"
    "优先级：--mode > $IELTS_BUDDY_MODE > config.toml > 默认 local。",
)
@click.pass_context
def cli(ctx, mode: str | None):
    """IELTS LEARNING SEEK - 雅思学习-不断求索"""
    # W10：--mode 写到 os.environ，让 get_mode() 命中。
    # 还原由 @cli.result_callback() 在子命令执行完后做（click 调用顺序：
    # cli() → subcommand() → result_callback()，所以 try/finally 不能写在
    # cli() 内——finally 会在子命令执行前就触发）。
    if mode is not None:
        if "IELTS_BUDDY_MODE" not in os.environ:
            _MODE_STATE["set"] = True
            _MODE_STATE["added"] = True
        else:
            _MODE_STATE["set"] = True
            _MODE_STATE["added"] = False
            _MODE_STATE["old"] = os.environ["IELTS_BUDDY_MODE"]
        os.environ["IELTS_BUDDY_MODE"] = mode
    if ctx.invoked_subcommand is not None:
        _show_daily_reminder()
        _show_current_user(ctx.invoked_subcommand)


@cli.result_callback()
def _mode_env_restore(result, **kwargs):
    """W10：在子命令执行完后还原 IELTS_BUDDY_MODE，避免污染进程级 env。"""
    # click 8.x result_callback 没有 ctx 参数，只能从 result 拿到 sub_ctx。
    # 业务子命令 return 的是 exit code（int），不是 ctx。
    # 折中：sub_ctx 在 click 内部有 but 不能从 result 拿到。
    # 改成查模块级 dict 暂存模式状态。
    if not _MODE_STATE["set"]:
        return
    if _MODE_STATE["added"]:
        os.environ.pop("IELTS_BUDDY_MODE", None)
    else:
        os.environ["IELTS_BUDDY_MODE"] = _MODE_STATE["old"]
    _MODE_STATE["set"] = False
    _MODE_STATE["added"] = False
    _MODE_STATE["old"] = ""


cli.add_command(vocab)
cli.add_command(stats)
cli.add_command(plan)
cli.add_command(sync)
cli.add_command(email)
cli.add_command(write)
cli.add_command(speak)
cli.add_command(report)
cli.add_command(listen)
cli.add_command(grade)
cli.add_command(deploy)
cli.add_command(exam)
cli.add_command(feishu)
cli.add_command(recommend)
cli.add_command(course)
cli.add_command(auth)


if __name__ == "__main__":
    cli()
