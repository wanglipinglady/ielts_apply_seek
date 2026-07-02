"""TOML 配置管理

配置文件位于 ~/.ielts-buddy/config.toml，首次运行时自动创建。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Python 3.11+ 内置 tomllib，3.10 需要 fallback
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]


# 默认配置
DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "daily_count": 50,
        "default_band": 7,
        # W4 阶段：数据源模式
        # - "local":  本地 SQLite（默认，向后兼容）
        # - "online": 远端 MySQL（推荐生产用）
        "mode": "local",
    },
    "database": {
        # W4 阶段：MySQL 连接信息
        # 优先级：环境变量 MYSQL_URL > 配置文件 > 模块默认
        # 留空字符串代表"使用模块默认（118.190.148.121:3306）"
        "mysql_url": "",
        # 联网模式默认登录用户名（占位；用户首登会复制模板分类）
        "default_username": "anonymous",
        # W5 阶段：当前 user_id
        # 优先级：环境变量 IELTS_BUDDY_USER_ID > 配置文件 > 1（单机默认）
        # 联网模式首登后会被 user_repo.get_or_create 返回的真实 id 覆盖
        "user_id": 1,
    },
}

# 有效模式集合（防止拼写错误静默走默认）
VALID_MODES = ("local", "online")

# 应用数据目录（惰性求值，支持运行时修改环境变量）
def get_app_dir() -> Path:
    return Path(os.environ.get("IELTS_BUDDY_HOME", "~/.ielts-buddy")).expanduser()


def get_config_path() -> Path:
    return get_app_dir() / "config.toml"


def get_db_path() -> Path:
    return get_app_dir() / "data.db"


# =============================================================
# W4 阶段：mode / MySQL URL 解析
# =============================================================


def get_mode(config: "Config | None" = None) -> str:
    """读取当前模式（"local" | "online"）。

    优先级：环境变量 IELTS_BUDDY_MODE > config.general.mode > "local"
    任何来源的值不在 VALID_MODES 内都退回到 "local" 并发出一次性提示。
    """
    import warnings
    env_mode = os.environ.get("IELTS_BUDDY_MODE", "").strip().lower()
    if env_mode:
        if env_mode in VALID_MODES:
            return env_mode
        warnings.warn(
            f"IELTS_BUDDY_MODE={env_mode!r} 非法，应为 {VALID_MODES}，已回退到 'local'",
            stacklevel=2,
        )
        return "local"

    if config is not None:
        cfg_mode = str(config.get("general.mode", "local")).strip().lower()
        if cfg_mode in VALID_MODES:
            return cfg_mode
        if cfg_mode:  # 非空但非法
            warnings.warn(
                f"general.mode={cfg_mode!r} 非法，应为 {VALID_MODES}，已回退到 'local'",
                stacklevel=2,
            )
    return "local"


def get_mysql_url(config: "Config | None" = None) -> str:
    """读取 MySQL 连接 URL。

    优先级：环境变量 MYSQL_URL > config.database.mysql_url > 模块默认
    返回值始终是 SQLAlchemy 格式的 URL（含 scheme://...）。
    """
    env_url = os.environ.get("MYSQL_URL", "").strip()
    if env_url:
        return env_url

    if config is not None:
        cfg_url = str(config.get("database.mysql_url", "")).strip()
        if cfg_url:
            return cfg_url

    # 留空：延迟到 MySQL 容器内部用默认 118.190.148.121
    return ""


# =============================================================
# W5 阶段：user_id 解析
# =============================================================


def get_user_id(config: "Config | None" = None) -> int:
    """读取当前 user_id。

    优先级：
    1. 环境变量 IELTS_BUDDY_USER_ID（必须是非负整数）
    2. config.database.user_id
    3. 默认 1（单机模式约定；SQLiteUserRepository 单机实现固定 1）

    联网模式下，CLI 启动时会调 user_repo.get_or_create(default_username)
    拿到真实 user_id，调用方应把该值写回 config 或环境变量后再构造 Service。
    """
    import warnings

    env = os.environ.get("IELTS_BUDDY_USER_ID", "").strip()
    if env:
        try:
            v = int(env)
            if v >= 0:
                return v
            warnings.warn(
                f"IELTS_BUDDY_USER_ID={env!r} 必须为非负整数，已回退",
                stacklevel=2,
            )
        except ValueError:
            warnings.warn(
                f"IELTS_BUDDY_USER_ID={env!r} 不是合法整数，已回退",
                stacklevel=2,
            )

    if config is not None:
        cfg_val = config.get("database.user_id", None)
        if cfg_val is not None:
            try:
                v = int(cfg_val)
                if v >= 0:
                    return v
                warnings.warn(
                    f"database.user_id={cfg_val!r} 必须为非负整数，已回退",
                    stacklevel=2,
                )
            except (TypeError, ValueError):
                warnings.warn(
                    f"database.user_id={cfg_val!r} 不是合法整数，已回退",
                    stacklevel=2,
                )

    return 1


def _serialize_toml(data: dict[str, Any]) -> str:
    """将字典序列化为 TOML 格式字符串（简易实现，避免额外依赖）"""
    lines: list[str] = []
    # 先写非 table 值
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_toml_value(value)}")
    # 再写 table
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"\n[{key}]")
            for k, v in value.items():
                lines.append(f"{k} = {_toml_value(v)}")
    return "\n".join(lines) + "\n"


def _toml_value(value: Any) -> str:
    """将 Python 值转换为 TOML 值字符串"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        items = ", ".join(_toml_value(v) for v in value)
        return f"[{items}]"
    return f'"{value}"'


class Config:
    """TOML 配置管理器"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.path = Path(config_path).expanduser() if config_path else get_config_path()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """加载配置文件，不存在则使用默认值"""
        if self.path.exists() and tomllib is not None:
            with open(self.path, "rb") as f:
                self._data = tomllib.load(f)
        else:
            self._data = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULT_CONFIG.items()}

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，支持 'section.key' 格式的点分路径"""
        parts = key.split(".")
        obj: Any = self._data
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return default
            if obj is None:
                return default
        return obj

    def set(self, key: str, value: Any) -> None:
        """设置配置项，支持 'section.key' 格式的点分路径"""
        parts = key.split(".")
        obj = self._data
        for part in parts[:-1]:
            if part not in obj or not isinstance(obj[part], dict):
                obj[part] = {}
            obj = obj[part]
        obj[parts[-1]] = value

    def save(self) -> None:
        """保存配置到文件"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(_serialize_toml(self._data), encoding="utf-8")

    def ensure_app_dir(self) -> Path:
        """确保应用数据目录存在并返回路径"""
        app_dir = self.path.parent
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir
