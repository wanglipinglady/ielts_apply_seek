"""IELTS LEARNING SEEK -  CLI 入口"""

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
    """
    import os
    # auth 子命令自己会打印用户信息，避免重复
    # invoked 是 group 名（auth），不一定是子命令（login/logout/whoami）
    if invoked == "auth":
        return
    if os.environ.get("IELTS_BUDDY_NO_BANNER", "").strip() in ("1", "true", "yes"):
        return
    try:
        from ielts_buddy.core.config import get_app_dir
        from ielts_buddy.services.auth_service import AuthService

        session_path = get_app_dir() / "session.json"
        svc = AuthService(session_path=session_path)
        info = svc.whoami()
        svc.close()
        if info is None:
            # W7 阶段：未登录不阻断；显式提示数据归属
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


@click.group()
@click.version_option(version="0.1.0", prog_name="ielts-learning-seek")
@click.pass_context
def cli(ctx):
    """IELTS LEARNING SEEK - 雅思学习-不断求索"""
    if ctx.invoked_subcommand is not None:
        _show_daily_reminder()
        _show_current_user(ctx.invoked_subcommand)


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
