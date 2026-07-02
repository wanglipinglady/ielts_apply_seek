"""用户登录与会话管理服务。

W6 阶段：
- 登录：根据 mode 走 local / online 容器；调 user_repo.get_or_create(username)
  拿到 user_id，持久化到 ~/.ielts-buddy/session.json，并把真实 user_id 写回
  config.toml 的 database.user_id（让 get_user_id() 后续能命中）。
- whoami / logout：只读写 session.json，不再触达数据库。
- 本地（local）模式下 user_repo.get_or_create 固定返回 1，因此
  login("anyone") 也能成功，但 user_id 始终是 1；username 仍会写 session
  供 CLI 显示。
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

from ielts_buddy.core.config import Config, get_app_dir, get_mode


# =============================================================
# 异常
# =============================================================


class NotLoggedInError(RuntimeError):
    """要求登录但当前没有 session 时抛出。"""


# =============================================================
# 持久化辅助
# =============================================================


def _serialize_session(data: dict[str, Any]) -> str:
    """将 session 字典序列化为带时间戳注释的 TOML 风格 JSON。"""
    # 使用 JSON：与 plan.json / email.json 等文件保持一致
    return json.dumps(data, ensure_ascii=False, indent=2)


# =============================================================
# AuthService
# =============================================================


class AuthService:
    """用户登录与本地 session 持久化服务。"""

    def __init__(
        self,
        mode: str | None = None,
        session_path: Path | None = None,
        container: Any = None,
        config: Config | None = None,
    ) -> None:
        """构造 AuthService。

        Args:
            mode: "local" | "online" | None (走 config)
            session_path: session.json 路径；None 时取 ~/.ielts-buddy/session.json
            container: 注入的 RepositoryContainer（测试用）；None 时按 mode 创建
            config: 注入的 Config 实例；None 时新构造
        """
        self._session_path = session_path or (get_app_dir() / "session.json")
        # 解析 mode（与 W4 一致：env > config > "local"）
        if mode is not None:
            if mode not in ("local", "online"):
                raise ValueError(f"未知 mode={mode!r}，应为 'local' 或 'online'")
            self._mode = mode
        else:
            cfg = config if config is not None else Config()
            self._mode = get_mode(cfg)

        self._container = container  # 可选注入；None 时在 login 时按需打开
        self._config = config  # 用于 writeback user_id
        self._owns_container = container is None

    # ---- 容器管理 ----

    def _get_container(self) -> Any:
        """懒加载 RepositoryContainer。"""
        if self._container is None:
            from ielts_buddy.repositories import create_repositories

            self._container = create_repositories(mode=self._mode)
        return self._container

    def close(self) -> None:
        """关闭内部容器（仅当本服务自己创建时）。"""
        if self._owns_container and self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None

    # ---- 会话文件 IO ----

    def _read_session(self) -> dict[str, Any] | None:
        """读取 session.json；不存在或损坏返回 None。"""
        if not self._session_path.exists():
            return None
        try:
            text = self._session_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _write_session(self, data: dict[str, Any]) -> None:
        """写入 session.json（自动创建父目录）。"""
        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_path.write_text(
            _serialize_session(data), encoding="utf-8"
        )

    def _delete_session(self) -> bool:
        """删除 session.json；文件不存在返回 False。"""
        if self._session_path.exists():
            self._session_path.unlink()
            return True
        return False

    # ---- 公开 API ----

    def login(self, username: str) -> dict[str, Any]:
        """登录并持久化 session。

        Steps:
            1) user_repo.get_or_create(username) -> user_id
            2) user_repo.update_last_login(user_id)
            3) user_repo.ensure_system_categories(user_id)
            4) 写 session.json
            5) 写回 config.database.user_id
            6) close() 自有容器

        Args:
            username: 用户名（联网模式必填；单机模式任意）

        Returns:
            {"user_id": int, "username": str, "mode": str, "is_new": bool}
        """
        name = (username or "").strip()
        if not name:
            raise ValueError("username 不能为空")

        container = self._get_container()
        user_repo = container.user

        # 1) get_or_create
        user_id = int(user_repo.get_or_create(name))

        # 2) update_last_login
        try:
            user_repo.update_last_login(user_id)
        except Exception as e:  # noqa: BLE001 - 容忍非关键失败
            warnings.warn(f"update_last_login 失败（非致命）: {e}", stacklevel=2)

        # 3) ensure_system_categories
        try:
            user_repo.ensure_system_categories(user_id)
        except Exception as e:  # noqa: BLE001 - 容忍非关键失败
            warnings.warn(
                f"ensure_system_categories 失败（非致命）: {e}", stacklevel=2
            )

        # 4) 写 session.json
        now = datetime.now().isoformat(timespec="seconds")
        session = {
            "user_id": user_id,
            "username": name,
            "mode": self._mode,
            "logged_in_at": now,
            "last_login_at": now,
        }
        self._write_session(session)

        # 5) 写回 config（让 get_user_id() 后续能命中真实 id）
        self._writeback_user_id(user_id)

        # 6) 关闭自有容器
        self.close()

        return {
            "user_id": user_id,
            "username": name,
            "mode": self._mode,
            "is_new": False,
        }

    def whoami(self) -> dict[str, Any] | None:
        """读取当前 session；不存在返回 None。

        W11：session.mode 必须跟当前 self._mode 一致才认账。
        否则视为未登录——避免 "用 online 模式登录后切 local 查 SQLite"
        出现 user_id 错位（W11 真实 bug）。

        Returns:
            {user_id, username, mode, logged_in_at, last_login_at} | None
        """
        data = self._read_session()
        if data is None:
            return None
        if data.get("mode") != self._mode:
            return None
        return data

    def logout(self) -> bool:
        """删除本地 session.json。返回是否实际删除。

        注：不删除 config 里的 database.user_id（下次 login 会覆盖）。
        """
        return self._delete_session()

    def get_current_user_id(self) -> int | None:
        """便捷：返回当前 session 里的 user_id；没登录返回 None。"""
        s = self._read_session()
        if s is None:
            return None
        return int(s.get("user_id", 0)) or None

    def require_login(self) -> dict[str, Any]:
        """要求已登录；否则抛 NotLoggedInError。"""
        s = self._read_session()
        if s is None:
            raise NotLoggedInError(
                "当前未登录，请先执行 `ib login <username>`"
            )
        return s

    # ---- 内部 ----

    def _writeback_user_id(self, user_id: int) -> None:
        """把真实 user_id 写回 config.toml 的 database.user_id。

        失败仅警告，不抛异常（写不回去下次 login 会再覆盖）。
        """
        try:
            cfg = self._config if self._config is not None else Config()
            cfg.set("database.user_id", int(user_id))
            cfg.save()
        except Exception as e:  # noqa: BLE001
            warnings.warn(
                f"写回 config.database.user_id 失败（非致命）: {e}",
                stacklevel=2,
            )
