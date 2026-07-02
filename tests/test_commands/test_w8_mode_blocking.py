"""W8 阶段：MySQL 模式 + 未登录 阻断集成测试

测试范围：
1. local 模式 + 未登录 → 软提示 banner，继续（不阻断）= W7 既有行为
2. online 模式 + 未登录 → SystemExit(1) + 红字提示
3. online 模式 + 已登录 → 正常通过
4. local 模式 + 已登录 → 正常通过
5. auth 子命令不受 W8 阻断逻辑影响（未登录时也能跑 login / whoami / logout）

注：
- online 模式不需要真的连 MySQL。AuthService 在 _show_current_user 里
  只调用 whoami()（纯本地 session.json IO），不触发容器创建。
- Banner/阻断信息通过 Console(stderr=True) 写到进程 stderr。CliRunner
  默认 mix_stderr=True 会把 stderr 合并到 result.output，因此可以直接
  在 result.output 里断言；但为了稳健起见，W8 测试同时检查 result.output
  和 capsys.readouterr().err。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from ielts_buddy.cli import cli


def _err_text(result, capsys) -> str:
    """合并 CliRunner output 和 capsys 捕获的 stderr。"""
    out = result.output or ""
    err = capsys.readouterr().err or ""
    return out + "\n" + err


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture(autouse=True)
def _tmp_home(tmp_path, monkeypatch):
    """每个测试使用隔离的 IELTS_BUDDY_HOME。

    conftest 默认关掉 banner + IELTS_BUDDY_NO_BANNER=1。W8 测试要观察
    banner / 阻断行为，必须显式打开。
    """
    monkeypatch.setenv("IELTS_BUDDY_HOME", str(tmp_path / ".ielts-buddy"))
    monkeypatch.delenv("IELTS_BUDDY_NO_BANNER", raising=False)
    yield
    monkeypatch.delenv("IELTS_BUDDY_HOME", raising=False)


@pytest.fixture(autouse=True)
def _clean_mode_env(monkeypatch):
    """清掉可能污染的 mode 环境变量。"""
    monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)
    yield
    monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)


@pytest.fixture
def runner() -> CliRunner:
    # Click 8.3+ 默认 stdout + stderr 合并到 result.output，可以直接断言。
    return CliRunner()


@pytest.fixture
def home(tmp_path) -> Path:
    """临时数据目录。"""
    p = tmp_path / ".ielts-buddy"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _set_mode(home: Path, mode: str) -> None:
    """写一份 config.toml 到 home，general.mode = mode。"""
    config_path = home / "config.toml"
    config_path.write_text(
        f'[general]\nmode = "{mode}"\n\n[database]\nmysql_url = ""\n',
        encoding="utf-8",
    )


def _write_session(home: Path, *, username: str, user_id: int, mode: str) -> None:
    """写一份 session.json 模拟已登录。"""
    session_path = home / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "user_id": user_id,
                "username": username,
                "mode": mode,
                "logged_in_at": "2026-07-02T00:00:00",
                "last_login_at": "2026-07-02T00:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# =============================================================
# W8 核心：mode 决定是否阻断
# =============================================================


class TestW8ModeBasedBlocking:
    """W8: 未登录 + mode 决定是否阻断。"""

    def test_local_not_logged_in_soft_prompt(self, runner, home, capsys):
        """local 模式 + 未登录 → 软提示 banner，命令继续 (exit 0)。"""
        _set_mode(home, "local")
        result = runner.invoke(cli, ["vocab", "--help"])
        text = _err_text(result, capsys)
        assert result.exit_code == 0, text
        assert "未登录" in text
        assert "user_id=1" in text

    def test_online_not_logged_in_blocks(self, runner, home, capsys):
        """online 模式 + 未登录 → SystemExit(1)，红字提示。"""
        _set_mode(home, "online")
        result = runner.invoke(cli, ["vocab", "--help"])
        text = _err_text(result, capsys)
        assert result.exit_code == 1, text
        assert "在线模式需要先登录" in text
        assert "ib auth login" in text

    def test_online_logged_in_passes(self, runner, home, capsys):
        """online 模式 + 已登录 → 正常通过。"""
        _set_mode(home, "online")
        _write_session(home, username="alice", user_id=2, mode="online")
        result = runner.invoke(cli, ["vocab", "--help"])
        text = _err_text(result, capsys)
        assert result.exit_code == 0, text
        assert "当前用户" in text
        assert "alice" in text

    def test_local_logged_in_passes(self, runner, home, capsys):
        """local 模式 + 已登录 → 正常通过（user_id 由 session 决定，不走默认 1）。"""
        _set_mode(home, "local")
        _write_session(home, username="bob", user_id=3, mode="local")
        result = runner.invoke(cli, ["vocab", "--help"])
        text = _err_text(result, capsys)
        assert result.exit_code == 0, text
        assert "当前用户" in text
        assert "bob" in text
        assert "id=3" in text


class TestW8AuthSubcommandBypass:
    """W8: auth 子命令自身不受阻断（用户得能跑 login / whoami / logout）。"""

    def test_auth_help_unlogged_online(self, runner, home, capsys):
        """online 模式 + 未登录时 auth --help 不被 W8 阻断。"""
        _set_mode(home, "online")
        result = runner.invoke(cli, ["auth", "--help"])
        text = _err_text(result, capsys)
        assert result.exit_code == 0, text
        assert "在线模式需要先登录" not in text

    def test_auth_whoami_unlogged_online(self, runner, home, capsys):
        """online 模式 + 未登录时 auth whoami 不被 W8 阻断。"""
        _set_mode(home, "online")
        result = runner.invoke(cli, ["auth", "whoami"])
        text = _err_text(result, capsys)
        # whoami 未登录时本身 exit 非 0
        assert "在线模式需要先登录" not in text
        # 应该是 auth whoami 自己的"当前未登录"输出
        assert "未登录" in text

    def test_auth_logout_unlogged_online(self, runner, home, capsys):
        """online 模式 + 未登录时 auth logout 不被 W8 阻断。

        注：auth logout 有 @click.confirmation_option，CliRunner 需要 input="y" 才会真正执行。
        """
        _set_mode(home, "online")
        result = runner.invoke(cli, ["auth", "logout"], input="y\n")
        text = _err_text(result, capsys)
        # logout 未登录 + 用户答 y → exit 0（logout 内部会打印"当前未登录，无需登出"）
        assert result.exit_code == 0, text
        assert "在线模式需要先登录" not in text


class TestW8ModeSource:
    """W8: mode 来源测试（验证 _show_current_user 用了正确的 mode 解析）。"""

    def test_env_mode_overrides_config(self, runner, home, monkeypatch, capsys):
        """IELTS_BUDDY_MODE 环境变量优先级 > config.toml。"""
        _set_mode(home, "local")  # config 写 local
        monkeypatch.setenv("IELTS_BUDDY_MODE", "online")  # env 覆盖
        result = runner.invoke(cli, ["vocab", "--help"])
        text = _err_text(result, capsys)
        # env=online 生效 → 未登录应被阻断
        assert result.exit_code == 1, text
        assert "在线模式需要先登录" in text

    def test_default_mode_is_local(self, runner, home, monkeypatch, capsys):
        """没设 mode → 兜底 local，未登录软提示。"""
        # 显式删 env
        monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)
        # 删 config，让 get_mode 走兜底
        # 注意：Config 默认就是 local，所以 home 里没有 config 也算 local
        result = runner.invoke(cli, ["vocab", "--help"])
        text = _err_text(result, capsys)
        assert result.exit_code == 0, text
        assert "未登录" in text
