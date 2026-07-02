"""W6 阶段：AuthService 单元测试

测试范围：
1. 构造与 mode 校验（local/online/None）
2. login() 完整流程：写 session.json + 写回 config + 关闭容器
3. whoami() 各种状态：未登录 / 已登录 / 文件损坏 / 字段缺失
4. logout() 存在与不存在的语义
5. get_current_user_id / require_login
6. session.json 字段（user_id / username / mode / logged_in_at / last_login_at）
7. 容器复用（container 注入时不创建/关闭）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ielts_buddy.services.auth_service import (
    AuthService,
    NotLoggedInError,
)


# =============================================================
# Fake 容器：复刻 user_repo 协议
# =============================================================


class FakeUserRepository:
    """测试用 UserRepository：默认行为跟 SQLiteUserRepository 类似。"""

    def __init__(
        self,
        default_id: int = 1,
        fail_update: bool = False,
        fail_ensure: bool = False,
    ) -> None:
        self.default_id = default_id
        self.fail_update = fail_update
        self.fail_ensure = fail_ensure
        self.update_calls: list[int] = []
        self.ensure_calls: list[int] = []
        self.closed = False

    def get_or_create(self, username: str) -> int:
        return self.default_id

    def get_by_id(self, user_id: int) -> dict | None:  # noqa: ARG002
        return None

    def update_last_login(self, user_id: int) -> None:
        self.update_calls.append(user_id)
        if self.fail_update:
            raise RuntimeError("simulated update_last_login failure")

    def list_users(self) -> list[dict]:
        return []

    def ensure_system_categories(self, user_id: int) -> None:
        self.ensure_calls.append(user_id)
        if self.fail_ensure:
            raise RuntimeError("simulated ensure_system_categories failure")

    # 容器识别：container.user 即可被 AuthService 拿到
    @property
    def user(self):  # noqa: D401 - 协议兼容
        raise NotImplementedError("应通过 container.user 访问")


class FakeContainer:
    def __init__(self, user_repo: FakeUserRepository) -> None:
        self.user = user_repo
        self.closed = False

    def close(self) -> None:
        self.closed = True


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture
def session_path(tmp_path: Path) -> Path:
    return tmp_path / "session.json"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


@pytest.fixture
def config(config_path: Path):
    """用 config_path 构造 Config，让 _writeback_user_id 写到隔离文件。"""
    from ielts_buddy.core.config import Config

    return Config(config_path=config_path)


@pytest.fixture
def fake_container() -> FakeContainer:
    return FakeContainer(FakeUserRepository(default_id=1))


# =============================================================
# 1) 构造与 mode 校验
# =============================================================


class TestConstruction:
    def test_construct_with_container_does_not_open_db(self, fake_container):
        """注入 container 时，AuthService 不应自己再开容器。"""
        svc = AuthService(container=fake_container, mode="local")
        # 没调过 _get_container 之前，container 仍是我们注入的那个
        assert svc._container is fake_container

    def test_construct_rejects_invalid_mode(self):
        with pytest.raises(ValueError, match="未知 mode"):
            AuthService(mode="hybrid")

    def test_construct_accepts_local_and_online(self, tmp_path):
        sp = tmp_path / "session.json"
        AuthService(mode="local", session_path=sp)
        AuthService(mode="online", session_path=sp)

    def test_default_session_path_is_app_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("IELTS_BUDDY_HOME", str(tmp_path / "home"))
        svc = AuthService()
        assert svc._session_path == tmp_path / "home" / "session.json"


# =============================================================
# 2) login() 完整流程
# =============================================================


class TestLogin:
    def test_login_writes_session(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        result = svc.login("alice")

        assert result["username"] == "alice"
        assert result["user_id"] == 1
        assert result["mode"] == "local"
        assert result["is_new"] is False

        assert session_path.exists()
        data = json.loads(session_path.read_text(encoding="utf-8"))
        assert data["user_id"] == 1
        assert data["username"] == "alice"
        assert data["mode"] == "local"
        assert "logged_in_at" in data
        assert "last_login_at" in data

    def test_login_calls_update_and_ensure(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        svc.login("alice")
        assert fake_container.user.update_calls == [1]
        assert fake_container.user.ensure_calls == [1]

    def test_login_closes_injected_container(self, session_path, fake_container):
        """AuthService 不会 close 注入的 container（owns_container=False）。"""
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        svc.login("alice")
        assert fake_container.closed is False

    def test_login_closes_self_managed_container(self, session_path):
        """未注入 container 时，AuthService 内部建容器，login 后关闭。"""
        svc = AuthService(mode="local", session_path=session_path)
        try:
            svc.login("alice")
        finally:
            # 隔离 HOME 已经在 conftest 设了，这里只确保 close 至少能跑过
            pass
        # self._owns_container=True 路径下 login 会 close；
        # 关闭后 self._container 被重置为 None
        assert svc._container is None

    def test_login_empty_username_raises(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        with pytest.raises(ValueError, match="username 不能为空"):
            svc.login("")
        with pytest.raises(ValueError, match="username 不能为空"):
            svc.login("   ")

    def test_login_writes_back_user_id_to_config(
        self, session_path, config, fake_container
    ):
        """login 成功后应把真实 user_id 写回 config.database.user_id。"""
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
            config=config,
        )
        svc.login("alice")
        # config 应被写回
        assert config.get("database.user_id") == 1
        # 配置文件也应持久化
        assert config.path.exists()
        import tomllib
        with open(config.path, "rb") as f:
            saved = tomllib.load(f)
        assert saved["database"]["user_id"] == 1

    def test_login_uses_user_repo_id_not_input(
        self, session_path, fake_container
    ):
        """login 返回的 user_id 来自 user_repo.get_or_create，不是入参。"""
        fake_container.user.default_id = 42
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        result = svc.login("bob")
        assert result["user_id"] == 42
        data = json.loads(session_path.read_text(encoding="utf-8"))
        assert data["user_id"] == 42

    def test_login_tolerates_update_last_login_failure(
        self, session_path, fake_container
    ):
        fake_container.user.fail_update = True
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        # 不应抛；只 warn
        result = svc.login("alice")
        assert result["user_id"] == 1
        # session 仍要写
        assert session_path.exists()

    def test_login_tolerates_ensure_system_categories_failure(
        self, session_path, fake_container
    ):
        fake_container.user.fail_ensure = True
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        result = svc.login("alice")
        assert result["user_id"] == 1
        assert session_path.exists()


# =============================================================
# 3) whoami()
# =============================================================


class TestWhoami:
    def test_whoami_no_session(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        assert svc.whoami() is None

    def test_whoami_with_session(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        svc.login("alice")
        info = svc.whoami()
        assert info is not None
        assert info["username"] == "alice"
        assert info["user_id"] == 1
        assert info["mode"] == "local"

    def test_whoami_corrupted_json_returns_none(self, session_path):
        session_path.write_text("{not valid json", encoding="utf-8")
        svc = AuthService(
            mode="local", session_path=session_path, container=FakeContainer(FakeUserRepository())
        )
        assert svc.whoami() is None

    def test_whoami_non_dict_json_returns_none(self, session_path):
        session_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        svc = AuthService(
            mode="local", session_path=session_path, container=FakeContainer(FakeUserRepository())
        )
        assert svc.whoami() is None

    def test_whoami_does_not_touch_container(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        # 没 login，container 不应被打开或关闭
        svc.whoami()
        assert fake_container.closed is False


# =============================================================
# 4) logout()
# =============================================================


class TestLogout:
    def test_logout_existing_session_returns_true(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        svc.login("alice")
        assert session_path.exists()
        assert svc.logout() is True
        assert not session_path.exists()

    def test_logout_no_session_returns_false(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        assert svc.logout() is False


# =============================================================
# 5) get_current_user_id / require_login
# =============================================================


class TestHelpers:
    def test_get_current_user_id_when_logged_in(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        svc.login("alice")
        assert svc.get_current_user_id() == 1

    def test_get_current_user_id_when_not_logged_in(
        self, session_path, fake_container
    ):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        assert svc.get_current_user_id() is None

    def test_require_login_returns_session(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        svc.login("alice")
        s = svc.require_login()
        assert s["username"] == "alice"

    def test_require_login_raises_when_not_logged_in(
        self, session_path, fake_container
    ):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        with pytest.raises(NotLoggedInError, match="ib login"):
            svc.require_login()


# =============================================================
# 6) session.json 字段完整性
# =============================================================


class TestSessionSchema:
    def test_session_has_all_required_fields(self, session_path, fake_container):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        svc.login("alice")
        data = json.loads(session_path.read_text(encoding="utf-8"))
        for key in ("user_id", "username", "mode", "logged_in_at", "last_login_at"):
            assert key in data, f"missing {key}"

    def test_session_logged_in_at_is_iso_string(
        self, session_path, fake_container
    ):
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        svc.login("alice")
        data = json.loads(session_path.read_text(encoding="utf-8"))
        # 至少包含日期与时间，能用 datetime.fromisoformat 解析
        from datetime import datetime
        datetime.fromisoformat(data["logged_in_at"])  # 不抛就 OK
        datetime.fromisoformat(data["last_login_at"])

    def test_session_user_id_is_int(self, session_path, fake_container):
        fake_container.user.default_id = 7
        svc = AuthService(
            mode="local",
            session_path=session_path,
            container=fake_container,
        )
        svc.login("alice")
        data = json.loads(session_path.read_text(encoding="utf-8"))
        assert isinstance(data["user_id"], int)
        assert data["user_id"] == 7

    def test_session_parent_dir_created(self, tmp_path, fake_container):
        """session.json 父目录不存在时应被创建。"""
        nested = tmp_path / "deep" / "nested" / "session.json"
        svc = AuthService(
            mode="local", session_path=nested, container=fake_container
        )
        svc.login("alice")
        assert nested.exists()


# =============================================================
# 7) 容器注入与生命周期
# =============================================================


class TestContainerLifecycle:
    def test_owns_container_flag(self, fake_container):
        """传了 container -> owns_container=False；不传 -> owns_container=True。"""
        s1 = AuthService(container=fake_container)
        s2 = AuthService()
        assert s1._owns_container is False
        assert s2._owns_container is True

    def test_close_closes_only_owned_container(self, fake_container):
        s1 = AuthService(container=fake_container)
        s2 = AuthService()
        s1.close()
        assert fake_container.closed is False
        # s2 没建过容器，close 不应抛
        s2.close()

    def test_close_handles_broken_container(self):
        class Broken:
            @property
            def user(self):
                return FakeUserRepository()

            def close(self):
                raise RuntimeError("boom")

        s = AuthService(container=Broken())
        # 不应向上抛
        s.close()
