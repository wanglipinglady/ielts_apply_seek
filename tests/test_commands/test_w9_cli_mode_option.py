"""W9 阶段：CLI --mode 选项测试

测试范围：
1. --mode local / --mode online 出现在 --help
2. --mode online 强制走 online 模式（未登录 → 阻断）
3. --mode local 强制走 local 模式（未登录 → 软提示）
4. --mode 优先级 > $IELTS_BUDDY_MODE 环境变量 > config.toml
5. --mode 非法值 → Click 自动报错
6. --mode 不影响 auth 子命令
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from ielts_buddy.cli import cli


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


@pytest.fixture
def home(tmp_path) -> Path:
    p = tmp_path / ".ielts-buddy"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _set_mode(home: Path, mode: str) -> None:
    config_path = home / "config.toml"
    config_path.write_text(
        f'[general]\nmode = "{mode}"\n\n[database]\nmysql_url = ""\n',
        encoding="utf-8",
    )


# =============================================================
# W9.1 --mode 选项存在性
# =============================================================


class TestW9ModeOptionHelp:
    """--mode 选项要在 --help 里能看到。"""

    def test_mode_in_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--mode" in result.output
        # 描述里至少提到 local 和 online
        assert "local" in result.output.lower()
        assert "online" in result.output.lower()

    def test_mode_choices_local_online(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert "[local" in result.output
        assert "online]" in result.output


# =============================================================
# W9.2 --mode 强制覆盖 config / env
# =============================================================


class TestW9ModeOverrides:
    """--mode 优先级最高，必须覆盖 env 和 config。"""

    def test_mode_local_overrides_env_online(self, runner, home, monkeypatch):
        """env=online + --mode local → 实际 local（未登录软提示）。"""
        _set_mode(home, "local")
        monkeypatch.setenv("IELTS_BUDDY_MODE", "online")
        result = runner.invoke(cli, ["--mode", "local", "vocab", "--help"])
        assert result.exit_code == 0, result.output
        # local + 未登录：软提示 banner
        assert "未登录" in result.output
        assert "user_id=1" in result.output
        # 不能出现 online 阻断提示
        assert "在线模式需要先登录" not in result.output

    def test_mode_online_overrides_config_local(self, runner, home):
        """config=local + --mode online → 实际 online（未登录阻断）。"""
        _set_mode(home, "local")
        result = runner.invoke(cli, ["--mode", "online", "vocab", "--help"])
        assert result.exit_code == 1, result.output
        assert "在线模式需要先登录" in result.output

    def test_mode_online_overrides_env_local(self, runner, home, monkeypatch):
        """env=local + --mode online → 实际 online。"""
        monkeypatch.setenv("IELTS_BUDDY_MODE", "local")
        result = runner.invoke(cli, ["--mode", "online", "vocab", "--help"])
        assert result.exit_code == 1, result.output
        assert "在线模式需要先登录" in result.output

    def test_no_mode_flag_falls_through_to_config(self, runner, home):
        """没传 --mode → 走 config / env / 默认。"""
        _set_mode(home, "online")
        result = runner.invoke(cli, ["vocab", "--help"])
        # config=online 生效，未登录应被阻断
        assert result.exit_code == 1, result.output
        assert "在线模式需要先登录" in result.output


# =============================================================
# W9.3 --mode 非法值由 Click 拦截
# =============================================================


class TestW9ModeValidation:
    """--mode 非法值应该被 Click Choice 拦截。"""

    def test_mode_invalid_value(self, runner):
        result = runner.invoke(cli, ["--mode", "postgresql", "vocab", "--help"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "postgresql" in result.output

    def test_mode_case_insensitive(self, runner):
        """--mode LOCAL（大写）应该被接受（case_sensitive=False）。"""
        result = runner.invoke(cli, ["--mode", "LOCAL", "vocab", "--help"])
        # 即使 Click 接受了大小写，actual mode 应该是 lowercased
        # local + 未登录：exit 0 + 软提示
        assert result.exit_code == 0, result.output
        assert "未登录" in result.output


# =============================================================
# W9.4 --mode 不影响 auth 子命令
# =============================================================


class TestW9AuthBypass:
    """--mode online + 未登录时 auth 子命令不受 W8 阻断逻辑影响。"""

    def test_auth_help_with_mode_online(self, runner):
        result = runner.invoke(cli, ["--mode", "online", "auth", "--help"])
        assert result.exit_code == 0, result.output
        assert "在线模式需要先登录" not in result.output

    def test_auth_logout_with_mode_online(self, runner):
        result = runner.invoke(cli, ["--mode", "online", "auth", "logout"], input="y\n")
        # 未登录 logout 答 y 后 exit 0，不应被 W8 阻断
        assert result.exit_code == 0, result.output
        assert "在线模式需要先登录" not in result.output
