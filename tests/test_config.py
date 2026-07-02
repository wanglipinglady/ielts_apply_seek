"""测试配置管理"""

from __future__ import annotations

from pathlib import Path

import pytest

from ielts_buddy.core.config import (
    Config, DEFAULT_CONFIG, VALID_MODES, _serialize_toml, _toml_value,
    get_mode, get_mysql_url, get_user_id,
)


class TestTomlValue:
    """测试 TOML 值序列化"""

    def test_bool_true(self):
        assert _toml_value(True) == "true"

    def test_bool_false(self):
        assert _toml_value(False) == "false"

    def test_int(self):
        assert _toml_value(42) == "42"

    def test_float(self):
        assert _toml_value(3.14) == "3.14"

    def test_str(self):
        assert _toml_value("hello") == '"hello"'

    def test_list(self):
        result = _toml_value([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_list_of_strings(self):
        result = _toml_value(["a", "b"])
        assert result == '["a", "b"]'

    def test_empty_list(self):
        assert _toml_value([]) == "[]"


class TestSerializeToml:
    """测试 TOML 序列化"""

    def test_simple_dict(self):
        data = {"general": {"daily_count": 50, "default_band": 7}}
        result = _serialize_toml(data)
        assert "[general]" in result
        assert "daily_count = 50" in result
        assert "default_band = 7" in result

    def test_mixed_data(self):
        data = {"version": 1, "section": {"key": "value"}}
        result = _serialize_toml(data)
        assert "version = 1" in result
        assert "[section]" in result
        assert 'key = "value"' in result


class TestConfig:
    """测试配置管理器"""

    def test_default_config(self, tmp_path: Path):
        cfg = Config(config_path=tmp_path / "config.toml")
        assert cfg.get("general.daily_count") == 50
        assert cfg.get("general.default_band") == 7

    def test_get_nonexistent_key(self, tmp_path: Path):
        cfg = Config(config_path=tmp_path / "config.toml")
        assert cfg.get("nonexistent") is None
        assert cfg.get("nonexistent", "default") == "default"

    def test_get_nested_nonexistent(self, tmp_path: Path):
        cfg = Config(config_path=tmp_path / "config.toml")
        assert cfg.get("general.nonexistent") is None
        assert cfg.get("a.b.c") is None

    def test_set_and_get(self, tmp_path: Path):
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("general.daily_count", 100)
        assert cfg.get("general.daily_count") == 100

    def test_set_new_section(self, tmp_path: Path):
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("new_section.key", "value")
        assert cfg.get("new_section.key") == "value"

    def test_save_and_reload(self, tmp_path: Path):
        config_path = tmp_path / "config.toml"
        cfg1 = Config(config_path=config_path)
        cfg1.set("general.daily_count", 100)
        cfg1.save()

        cfg2 = Config(config_path=config_path)
        assert cfg2.get("general.daily_count") == 100

    def test_ensure_app_dir(self, tmp_path: Path):
        config_path = tmp_path / "subdir" / "config.toml"
        cfg = Config(config_path=config_path)
        app_dir = cfg.ensure_app_dir()
        assert app_dir.exists()
        assert app_dir == config_path.parent

    def test_get_deep_nesting_with_non_dict(self, tmp_path: Path):
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("general.daily_count", 50)
        # Try to get a nested key from an int value
        assert cfg.get("general.daily_count.something") is None


# =============================================================
# W4 阶段：mode / mysql_url 字段 + 解析器
# =============================================================


class TestDefaultConfigW4:
    """W4 新增的字段默认值"""

    def test_default_mode_is_local(self, tmp_path: Path):
        cfg = Config(config_path=tmp_path / "config.toml")
        assert cfg.get("general.mode") == "local"

    def test_default_mysql_url_is_empty(self, tmp_path: Path):
        cfg = Config(config_path=tmp_path / "config.toml")
        assert cfg.get("database.mysql_url") == ""

    def test_default_username(self, tmp_path: Path):
        cfg = Config(config_path=tmp_path / "config.toml")
        assert cfg.get("database.default_username") == "anonymous"

    def test_valid_modes(self):
        assert "local" in VALID_MODES
        assert "online" in VALID_MODES
        assert len(VALID_MODES) == 2

    def test_default_config_has_mode_key(self):
        assert "mode" in DEFAULT_CONFIG["general"]
        assert "database" in DEFAULT_CONFIG
        assert "mysql_url" in DEFAULT_CONFIG["database"]


class TestGetMode:
    """get_mode() — 解析当前 mode 的优先级链"""

    def test_no_env_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)
        cfg = Config(config_path=tmp_path / "config.toml")
        assert get_mode(cfg) == "local"

    def test_env_overrides_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # config 写 online
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("general.mode", "online")
        # env 强制 local
        monkeypatch.setenv("IELTS_BUDDY_MODE", "local")
        assert get_mode(cfg) == "local"

    def test_env_online(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("IELTS_BUDDY_MODE", "online")
        assert get_mode() == "online"

    def test_invalid_env_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("IELTS_BUDDY_MODE", "cloud")
        with pytest.warns(UserWarning, match="IELTS_BUDDY_MODE"):
            assert get_mode() == "local"

    def test_invalid_config_falls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("general.mode", "edge")
        with pytest.warns(UserWarning, match="general.mode"):
            assert get_mode(cfg) == "local"

    def test_config_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("general.mode", "online")
        assert get_mode(cfg) == "online"

    def test_env_case_normalized(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("IELTS_BUDDY_MODE", "ONLINE")
        assert get_mode() == "online"


class TestGetMysqlUrl:
    """get_mysql_url() — 解析 MySQL 连接 URL 的优先级链"""

    def test_env_overrides_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database.mysql_url", "mysql+pymysql://cfg:123@cfg-host/db")
        monkeypatch.setenv("MYSQL_URL", "mysql+pymysql://env:456@env-host/db")
        assert get_mysql_url(cfg) == "mysql+pymysql://env:456@env-host/db"

    def test_config_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("MYSQL_URL", raising=False)
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database.mysql_url", "mysql+pymysql://u:p@h/d")
        assert get_mysql_url(cfg) == "mysql+pymysql://u:p@h/d"

    def test_default_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """env 不存在 + config 未设 → 返回空串（让 MySQL 容器走模块默认）"""
        monkeypatch.delenv("MYSQL_URL", raising=False)
        cfg = Config(config_path=tmp_path / "config.toml")
        assert get_mysql_url(cfg) == ""

    def test_env_empty_treated_as_unset(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """env 纯空白被 strip 后视为未设，落到 config"""
        monkeypatch.setenv("MYSQL_URL", "   ")
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database.mysql_url", "mysql+pymysql://u@h/d")
        assert get_mysql_url(cfg) == "mysql+pymysql://u@h/d"

    def test_env_no_config_needed(self, monkeypatch: pytest.MonkeyPatch):
        """只设 env，不传 config 也能解析"""
        monkeypatch.setenv("MYSQL_URL", "mysql+pymysql://env@h/d")
        assert get_mysql_url() == "mysql+pymysql://env@h/d"


# =============================================================
# W5 阶段：get_user_id 解析器
# =============================================================


class TestGetUserId:
    """get_user_id() — 解析当前 user_id 的优先级链

    优先级：IELTS_BUDDY_USER_ID > config.database.user_id > 1
    """

    def test_default_is_one(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """无 env + 无 config → 默认 1（单机模式约定）"""
        monkeypatch.delenv("IELTS_BUDDY_USER_ID", raising=False)
        cfg = Config(config_path=tmp_path / "config.toml")
        assert get_user_id(cfg) == 1

    def test_config_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("IELTS_BUDDY_USER_ID", raising=False)
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database.user_id", 42)
        assert get_user_id(cfg) == 42

    def test_env_overrides_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database.user_id", 42)
        monkeypatch.setenv("IELTS_BUDDY_USER_ID", "100")
        assert get_user_id(cfg) == 100

    def test_env_zero_allowed(self, monkeypatch: pytest.MonkeyPatch):
        """user_id=0 是合法值（系统模板分类也用 0）"""
        monkeypatch.setenv("IELTS_BUDDY_USER_ID", "0")
        assert get_user_id() == 0

    def test_env_invalid_int_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("IELTS_BUDDY_USER_ID", "not_a_number")
        with pytest.warns(UserWarning, match="IELTS_BUDDY_USER_ID"):
            assert get_user_id() == 1

    def test_env_negative_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("IELTS_BUDDY_USER_ID", "-1")
        with pytest.warns(UserWarning, match="必须为非负整数"):
            assert get_user_id() == 1

    def test_config_zero_allowed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("IELTS_BUDDY_USER_ID", raising=False)
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database.user_id", 0)
        assert get_user_id(cfg) == 0

    def test_config_invalid_falls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("IELTS_BUDDY_USER_ID", raising=False)
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database.user_id", "not_a_number")
        with pytest.warns(UserWarning, match="database.user_id"):
            assert get_user_id(cfg) == 1

    def test_env_empty_falls_through(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """env 为纯空白视为未设，落到 config"""
        monkeypatch.setenv("IELTS_BUDDY_USER_ID", "   ")
        cfg = Config(config_path=tmp_path / "config.toml")
        cfg.set("database.user_id", 7)
        assert get_user_id(cfg) == 7

    def test_no_config_arg_uses_default(self, monkeypatch: pytest.MonkeyPatch):
        """不传 config 也能解析（env > 默认 1）"""
        monkeypatch.setenv("IELTS_BUDDY_USER_ID", "88")
        assert get_user_id() == 88

    def test_no_config_no_env_default_one(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("IELTS_BUDDY_USER_ID", raising=False)
        assert get_user_id() == 1

    def test_default_config_has_user_id(self):
        assert DEFAULT_CONFIG["database"]["user_id"] == 1
