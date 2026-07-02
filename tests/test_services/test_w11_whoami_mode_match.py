"""W11 阶段：whoami 必须校验 session.mode == 当前 mode。

W11 真实 bug：
- 用户 A 用 --mode online auth login → session 写 {user_id: A, mode: online}
- 用户 B 用 --mode online auth login → session 覆盖写 {user_id: B, mode: online}
- A 跑 ib vocab list-personal → whoami 返回 B 的 user_id → 查不到 A 的数据
- 同理：online 登录后切 local 跑业务 → whoami 返回 online user_id，但 service 走 SQLite → 错位

修复：whoami 内部比较 data["mode"] != self._mode 时返回 None。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ielts_buddy.services.auth_service import AuthService


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture
def session_path(tmp_path: Path) -> Path:
    return tmp_path / "session.json"


def _write_session(
    path: Path, *, user_id: int, username: str, mode: str
) -> None:
    path.write_text(
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


class _DummyContainer:
    """测试用空 container，AuthService 不会真正打开容器。"""

    def close(self) -> None:  # noqa: D401 - protocol compat
        pass


# =============================================================
# W11.1 核心：whoami 校验 mode
# =============================================================


class TestWhoamiModeMatch:
    """whoami 在 session.mode ≠ self._mode 时返回 None。"""

    def test_session_local_current_local(self, session_path):
        """session 是 local + 当前 mode=local → 返回 session。"""
        _write_session(
            session_path, user_id=1, username="alice", mode="local"
        )
        svc = AuthService(
            session_path=session_path, mode="local", container=_DummyContainer()
        )
        info = svc.whoami()
        assert info is not None
        assert info["user_id"] == 1
        assert info["username"] == "alice"
        assert info["mode"] == "local"

    def test_session_online_current_online(self, session_path):
        """session 是 online + 当前 mode=online → 返回 session。"""
        _write_session(
            session_path, user_id=692, username="wangliping", mode="online"
        )
        svc = AuthService(
            session_path=session_path, mode="online", container=_DummyContainer()
        )
        info = svc.whoami()
        assert info is not None
        assert info["user_id"] == 692
        assert info["mode"] == "online"

    def test_session_online_current_local_returns_none(self, session_path):
        """session 是 online + 当前 mode=local → 返回 None（视为未登录）。"""
        _write_session(
            session_path, user_id=692, username="wangliping", mode="online"
        )
        svc = AuthService(
            session_path=session_path, mode="local", container=_DummyContainer()
        )
        info = svc.whoami()
        assert info is None, (
            f"切到 local 后 whoami 应该返回 None（避免 SQLite 用 online 的 user_id），"
            f"实际返回 {info!r}"
        )

    def test_session_local_current_online_returns_none(self, session_path):
        """session 是 local + 当前 mode=online → 返回 None。"""
        _write_session(
            session_path, user_id=1, username="alice", mode="local"
        )
        svc = AuthService(
            session_path=session_path, mode="online", container=_DummyContainer()
        )
        info = svc.whoami()
        assert info is None

    def test_no_session_returns_none(self, session_path):
        """session 文件不存在 → 返回 None。"""
        svc = AuthService(
            session_path=session_path, mode="local", container=_DummyContainer()
        )
        info = svc.whoami()
        assert info is None

    def test_session_with_corrupted_json_returns_none(self, session_path):
        """session 文件损坏 → 返回 None。"""
        session_path.write_text("not a valid json", encoding="utf-8")
        svc = AuthService(
            session_path=session_path, mode="local", container=_DummyContainer()
        )
        info = svc.whoami()
        assert info is None


# =============================================================
# W11.2 CLI 端到端验证
# =============================================================


class TestCLIModeSwitchIsolation:
    """CLI 端到端：online 登录后切 local → whoami 应该是未登录。"""

    def test_online_login_then_local_whoami(self, tmp_path, monkeypatch):
        """模拟用户操作：online 登录 → local 跑 whoami → 未登录。"""
        from click.testing import CliRunner
        from ielts_buddy.cli import cli

        monkeypatch.setenv("IELTS_BUDDY_HOME", str(tmp_path / ".ielts-buddy"))
        monkeypatch.delenv("IELTS_BUDDY_NO_BANNER", raising=False)
        monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)

        runner = CliRunner()
        home = tmp_path / ".ielts-buddy"
        home.mkdir(parents=True, exist_ok=True)
        # 提前写一份 online 模式的 session
        _write_session(
            home / "session.json", user_id=692, username="wangliping", mode="online"
        )

        # 跑 auth whoami 但不传 --mode → 默认 local → 应该看到"未登录"
        result = runner.invoke(cli, ["auth", "whoami"])
        # 应当是"当前未登录"提示
        assert "未登录" in result.output or "online" not in result.output.lower()

    def test_online_login_then_local_banner_says_unlogged(
        self, tmp_path, monkeypatch
    ):
        """online 登录后切 local 跑 vocab → banner 显示'未登录'，不显示 online user。"""
        from click.testing import CliRunner
        from ielts_buddy.cli import cli

        monkeypatch.setenv("IELTS_BUDDY_HOME", str(tmp_path / ".ielts-buddy"))
        monkeypatch.delenv("IELTS_BUDDY_NO_BANNER", raising=False)
        monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)

        runner = CliRunner()
        home = tmp_path / ".ielts-buddy"
        home.mkdir(parents=True, exist_ok=True)
        _write_session(
            home / "session.json", user_id=692, username="wangliping", mode="online"
        )

        # 跑 vocab --help 看 banner：online session 切到 local 后应该显示'未登录'
        result = runner.invoke(cli, ["vocab", "--help"])
        # banner 出现'未登录'（不是'当前用户'）
        assert "未登录" in result.output, (
            f"切到 local 后 banner 应该显示'未登录'，实际 output:\n{result.output}"
        )
        # 不应再显示 online 用户名
        assert "wangliping" not in result.output
