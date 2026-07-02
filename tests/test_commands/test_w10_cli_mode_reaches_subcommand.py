"""W10 阶段：修复 --mode 在子命令执行期间被还原的 bug。

W9 的 _MODE_ENV_BACKUP + try/finally 错误地放在 cli() 函数体内。
click 调用顺序是 cli() → subcommand() → result_callback()，所以
try/finally 的 finally 在子命令执行**前**就触发了，os.environ 被还原成空。

W10 修复：
1. cli() 内只写 os.environ["IELTS_BUDDY_MODE"]
2. 还原逻辑放在 @cli.result_callback() 里
3. 用模块级 _MODE_STATE 暂存"是不是 cli() 自己加的"标记

W10 测试用 monkeypatch.AuthService.login 验证：
- 真实场景下（--mode online 传给 cli()），login 内部读到的 mode 应该是 online
- 子命令执行后 os.environ 应该被还原
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ielts_buddy.cli import cli, _MODE_STATE


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture(autouse=True)
def _tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("IELTS_BUDDY_HOME", str(tmp_path / ".ielts-buddy"))
    monkeypatch.delenv("IELTS_BUDDY_NO_BANNER", raising=False)
    monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)
    yield
    monkeypatch.delenv("IELTS_BUDDY_HOME", raising=False)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# =============================================================
# W10.1 真实场景：--mode online 走 MySQL 容器
# =============================================================


class TestW10CliModeReachesSubcommand:
    """核心 bug：--mode online 必须真的传到子命令（不是被 try/finally 清掉）。"""

    def test_mode_online_reaches_auth_login_via_env(
        self, runner, tmp_path, monkeypatch
    ):
        """--mode online + auth login：AuthService.login 内部读到的 mode 必须是 online。

        通过 mock AuthService.login，看其调用时的 mode。
        """
        captured: dict = {}

        def fake_login(self, username, **_):
            # 关键：这里 read env，看 cli() 是否在子命令执行期间保留了 env
            from ielts_buddy.core.config import Config, get_mode
            cfg = Config()
            captured["mode_seen_by_subcommand"] = get_mode(cfg)
            captured["env_seen_by_subcommand"] = os.environ.get("IELTS_BUDDY_MODE")
            captured["user_id"] = 690
            captured["username"] = username
            return {
                "user_id": 690,
                "username": username,
                "mode": captured["mode_seen_by_subcommand"],
            }

        with patch.object(
            __import__("ielts_buddy.services.auth_service", fromlist=["AuthService"])
            .AuthService,
            "login",
            fake_login,
        ):
            result = runner.invoke(cli, ["--mode", "online", "auth", "login", "zhangsan"])

        # 退出 0
        assert result.exit_code == 0, result.output
        # 关键断言：子命令看到的是 online，不是 local
        assert captured["mode_seen_by_subcommand"] == "online", (
            f"子命令看到的 mode 应该是 online，"
            f"实际是 {captured['mode_seen_by_subcommand']!r}。"
            f"这意味着 cli() 里的 env 在子命令执行前被还原了。"
        )
        assert captured["env_seen_by_subcommand"] == "online"

    def test_mode_local_reaches_auth_login(self, runner, monkeypatch):
        """--mode local 应该让 login 走 local（不连 MySQL）。"""
        captured: dict = {}

        def fake_login(self, username, **_):
            from ielts_buddy.core.config import Config, get_mode
            captured["mode"] = get_mode(Config())
            return {"user_id": 1, "username": username, "mode": "local"}

        with patch.object(
            __import__("ielts_buddy.services.auth_service", fromlist=["AuthService"])
            .AuthService,
            "login",
            fake_login,
        ):
            result = runner.invoke(cli, ["--mode", "local", "auth", "login", "lisi"])

        assert result.exit_code == 0, result.output
        assert captured["mode"] == "local"

    def test_no_mode_flag_uses_config(self, runner):
        """没传 --mode → 走 config / env / 默认。"""
        # 没设 env、没设 config → 兜底 local
        captured: dict = {}

        def fake_login(self, username, **_):
            from ielts_buddy.core.config import Config, get_mode
            captured["mode"] = get_mode(Config())
            return {"user_id": 1, "username": username, "mode": "local"}

        with patch.object(
            __import__("ielts_buddy.services.auth_service", fromlist=["AuthService"])
            .AuthService,
            "login",
            fake_login,
        ):
            result = runner.invoke(cli, ["auth", "login", "wangwu"])

        assert result.exit_code == 0, result.output
        assert captured["mode"] == "local"


# =============================================================
# W10.2 还原不污染后续测试
# =============================================================


class TestW10EnvRestore:
    """result_callback 必须真的还原 env，否则 W9 的 bug 会重现（污染下一条命令）。"""

    def test_env_restored_after_online(self, runner, monkeypatch):
        """--mode online 跑完一次，os.environ["IELTS_BUDDY_MODE"] 应该是 pop 掉。"""
        assert "IELTS_BUDDY_MODE" not in os.environ

        with patch.object(
            __import__("ielts_buddy.services.auth_service", fromlist=["AuthService"])
            .AuthService,
            "login",
            lambda self, username, **_: {
                "user_id": 1,
                "username": username,
                "mode": "local",
            },
        ):
            runner.invoke(cli, ["--mode", "online", "auth", "login", "user_a"])

        # env 应该被清掉（因为之前 env 没设，是 cli() 加的）
        assert "IELTS_BUDDY_MODE" not in os.environ, (
            f"CLI 应该 pop env，实际还剩 {os.environ.get('IELTS_BUDDY_MODE')!r}"
        )

    def test_env_restored_to_old_value(self, runner, monkeypatch):
        """原本 env=foo，--mode online 跑完，env 应该还原成 foo。"""
        monkeypatch.setenv("IELTS_BUDDY_MODE", "preexisting")

        with patch.object(
            __import__("ielts_buddy.services.auth_service", fromlist=["AuthService"])
            .AuthService,
            "login",
            lambda self, username, **_: {
                "user_id": 1,
                "username": username,
                "mode": "online",
            },
        ):
            runner.invoke(cli, ["--mode", "online", "auth", "login", "user_b"])

        # env 应该还原成 preexisting（不是 online）
        assert os.environ.get("IELTS_BUDDY_MODE") == "preexisting", (
            f"env 应该还原成 preexisting，实际 {os.environ.get('IELTS_BUDDY_MODE')!r}"
        )

    def test_mode_state_cleared_after_callback(self, runner, monkeypatch):
        """result_callback 跑完后，_MODE_STATE['set'] 应该是 False。"""
        with patch.object(
            __import__("ielts_buddy.services.auth_service", fromlist=["AuthService"])
            .AuthService,
            "login",
            lambda self, username, **_: {
                "user_id": 1,
                "username": username,
                "mode": "online",
            },
        ):
            runner.invoke(cli, ["--mode", "online", "auth", "login", "user_c"])

        # result_callback 之后 _MODE_STATE 应该是初始状态
        assert _MODE_STATE["set"] is False
        assert _MODE_STATE["added"] is False
        assert _MODE_STATE["old"] == ""

    def test_no_mode_does_not_touch_env(self, runner, monkeypatch):
        """不传 --mode → _MODE_STATE 不变，env 不动。"""
        monkeypatch.setenv("IELTS_BUDDY_MODE", "preexisting")
        _MODE_STATE.update({"set": False, "added": False, "old": ""})

        with patch.object(
            __import__("ielts_buddy.services.auth_service", fromlist=["AuthService"])
            .AuthService,
            "login",
            lambda self, username, **_: {
                "user_id": 1,
                "username": username,
                "mode": "local",
            },
        ):
            runner.invoke(cli, ["auth", "login", "user_d"])

        # env 没被改
        assert os.environ.get("IELTS_BUDDY_MODE") == "preexisting"
        # _MODE_STATE 也没动
        assert _MODE_STATE["set"] is False
