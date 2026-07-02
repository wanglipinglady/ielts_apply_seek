"""W6 阶段：auth CLI 命令测试

测试范围：
1. ib auth --help / 子命令 help
2. ib --help 中应出现 auth
3. ib auth login <username>：成功路径 + 退出码
4. ib auth login "" / "   "：空用户名 → Abort(exit 1)
5. ib auth whoami：未登录 → Abort(exit 1)；已登录 → exit 0 + 字段展示
6. ib auth logout：未登录 → exit 0 (友好提示)；已登录 → exit 0 + 文件被删
7. 启动时 banner：未登录 / 已登录 / auth 子命令不打 banner
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from ielts_buddy.cli import cli


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture(autouse=True)
def _tmp_home(tmp_path, monkeypatch):
    """每个测试使用隔离的 IELTS_BUDDY_HOME。"""
    home = tmp_path / ".ielts-buddy"
    monkeypatch.setenv("IELTS_BUDDY_HOME", str(home))
    # 清理可能影响测试的环境变量
    monkeypatch.delenv("IELTS_BUDDY_USER_ID", raising=False)
    monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)
    monkeypatch.delenv("MYSQL_URL", raising=False)
    yield home


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def home(_tmp_home) -> Path:
    return _tmp_home


def _write_session(home: Path, user_id: int = 1, username: str = "alice", mode: str = "local") -> None:
    """在隔离 HOME 中预先放置 session.json。"""
    home.mkdir(parents=True, exist_ok=True)
    (home / "session.json").write_text(
        json.dumps(
            {
                "user_id": user_id,
                "username": username,
                "mode": mode,
                "logged_in_at": "2026-07-02T17:30:00",
                "last_login_at": "2026-07-02T17:30:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# =============================================================
# 1) Help
# =============================================================


class TestAuthHelp:
    def test_auth_in_main_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "auth" in result.output

    def test_auth_group_help(self, runner):
        result = runner.invoke(cli, ["auth", "--help"])
        assert result.exit_code == 0
        assert "login" in result.output
        assert "whoami" in result.output
        assert "logout" in result.output

    def test_auth_login_help(self, runner):
        result = runner.invoke(cli, ["auth", "login", "--help"])
        assert result.exit_code == 0
        assert "USERNAME" in result.output

    def test_auth_whoami_help(self, runner):
        result = runner.invoke(cli, ["auth", "whoami", "--help"])
        assert result.exit_code == 0

    def test_auth_logout_help(self, runner):
        result = runner.invoke(cli, ["auth", "logout", "--help"])
        assert result.exit_code == 0


# =============================================================
# 2) login
# =============================================================


class TestAuthLogin:
    def test_login_success(self, runner, home):
        """ib auth login alice → 退出码 0 + 写 session.json + 写回 config"""
        result = runner.invoke(cli, ["auth", "login", "alice"])
        assert result.exit_code == 0, result.output
        assert "登录成功" in result.output
        assert "alice" in result.output
        assert "user_id=" in result.output
        # session.json 已写
        assert (home / "session.json").exists()
        data = json.loads((home / "session.json").read_text(encoding="utf-8"))
        assert data["username"] == "alice"

    def test_login_writes_back_user_id_to_config(self, runner, home):
        result = runner.invoke(cli, ["auth", "login", "bob"])
        assert result.exit_code == 0
        # config 应被写
        config_path = home / "config.toml"
        assert config_path.exists()
        import tomllib
        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)
        # 本地模式 user_repo.get_or_create 固定返回 1
        assert cfg["database"]["user_id"] == 1

    def test_login_empty_username_aborts(self, runner, home):
        """空用户名 → click.Abort → 退出码 1"""
        result = runner.invoke(cli, ["auth", "login", ""])
        assert result.exit_code != 0
        assert "登录失败" in result.output
        # session.json 不应被创建
        assert not (home / "session.json").exists()

    def test_login_whitespace_username_aborts(self, runner, home):
        result = runner.invoke(cli, ["auth", "login", "   "])
        assert result.exit_code != 0
        assert "登录失败" in result.output
        assert not (home / "session.json").exists()

    def test_login_local_mode_hint(self, runner, home):
        """local 模式应有提示"""
        result = runner.invoke(cli, ["auth", "login", "alice"])
        assert result.exit_code == 0
        assert "单机模式" in result.output


# =============================================================
# 3) whoami
# =============================================================


class TestAuthWhoami:
    def test_whoami_when_not_logged_in_aborts(self, runner, home):
        result = runner.invoke(cli, ["auth", "whoami"])
        assert result.exit_code != 0
        assert "未登录" in result.output
        assert "ib login" in result.output

    def test_whoami_when_logged_in(self, runner, home):
        _write_session(home, user_id=1, username="alice", mode="local")
        result = runner.invoke(cli, ["auth", "whoami"])
        assert result.exit_code == 0, result.output
        assert "当前登录信息" in result.output
        assert "alice" in result.output
        assert "user_id" in result.output
        assert "mode" in result.output

    def test_whoami_shows_corrupted_session_as_not_logged_in(self, runner, home):
        home.mkdir(parents=True, exist_ok=True)
        (home / "session.json").write_text("{not valid", encoding="utf-8")
        result = runner.invoke(cli, ["auth", "whoami"])
        # 损坏文件被 whoami 视为未登录
        assert result.exit_code != 0
        assert "未登录" in result.output


# =============================================================
# 4) logout
# =============================================================


class TestAuthLogout:
    def test_logout_when_logged_in(self, runner, home):
        _write_session(home)
        assert (home / "session.json").exists()
        # 用 CliRunner 喂 "y" 走确认
        result = runner.invoke(cli, ["auth", "logout"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "已登出" in result.output
        assert not (home / "session.json").exists()

    def test_logout_when_not_logged_in_is_idempotent(self, runner, home):
        assert not (home / "session.json").exists()
        result = runner.invoke(cli, ["auth", "logout"], input="y\n")
        assert result.exit_code == 0
        assert "无需登出" in result.output

    def test_logout_requires_confirmation(self, runner, home):
        _write_session(home)
        # 不喂输入 → click.Abort
        result = runner.invoke(cli, ["auth", "logout"], input="n\n")
        assert result.exit_code != 0
        # session.json 应仍在
        assert (home / "session.json").exists()


# =============================================================
# 5) 启动时 banner
# =============================================================


class TestCurrentUserBanner:
    """W6: cli 启动时的"当前用户"banner。

    conftest 默认 IELTS_BUDDY_NO_BANNER=1（关闭 banner）。
    这里临时清掉这个变量，强制走 banner 路径。
    """

    @pytest.fixture(autouse=True)
    def _enable_banner(self, monkeypatch):
        monkeypatch.delenv("IELTS_BUDDY_NO_BANNER", raising=False)

    def test_banner_when_not_logged_in(self, runner, home):
        """跑非 auth 子命令，未登录应出现 '未登录' 提示。"""
        # 选用 vocab --help：纯 help，不触达 DB
        result = runner.invoke(cli, ["vocab", "--help"])
        assert result.exit_code == 0
        assert "未登录" in result.output

    def test_banner_when_logged_in(self, runner, home):
        _write_session(home, username="alice", user_id=1, mode="local")
        result = runner.invoke(cli, ["vocab", "--help"])
        assert result.exit_code == 0
        assert "当前用户" in result.output
        assert "alice" in result.output

    def test_banner_skipped_for_auth_subcommands(self, runner, home):
        """跑 auth 子命令时不应打印 banner（自己负责）。"""
        # 测未登录下的 auth --help
        r1 = runner.invoke(cli, ["auth", "--help"])
        assert r1.exit_code == 0
        assert "未登录" not in r1.output

        # 测 whoami（未登录时它本身就会输出"未登录"）
        r2 = runner.invoke(cli, ["auth", "whoami"])
        assert r2.exit_code != 0
        assert "未登录" in r2.output
        # 仍不应出现 banner 前缀 "-- "
        # banner 是 "[dim]-- ... --[/dim]"，whoami 输出只是 "当前未登录  请..."
        # 主要看"未登录"只出现一次（即 whoami 的输出），不被 banner 重复
        assert r2.output.count("未登录") == 1
