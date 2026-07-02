"""W4 模式工厂测试：create_repositories(mode, ...) 按 mode 选 SQLite/MySQL 容器。

测试范围：
1. 默认（无参）走 local
2. mode="local" 走 SQLite 容器
3. mode="online" 走 MySQL 容器（连真实 MySQL）
4. mode 非法 → ValueError
5. mode="online" 但 MySQL 不可用 → ImportError（用 mock 模拟 SQLAlchemy 缺失）
6. 容器满足 RepositoryContainer Protocol（runtime_checkable）
7. close() 幂等
8. db_path 透传到 SQLite
9. connection_url 透传到 MySQL
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ielts_buddy.core.repository import RepositoryContainer
from ielts_buddy.repositories import (
    _MYSQL_AVAILABLE,
    create_repositories,
)


# =============================================================
# 1. 默认 / local 模式
# =============================================================


class TestLocalMode:
    def test_default_is_local(self, tmp_path):
        """无参调用走 local，db_path 落到 tmp_path/data.db"""
        db = tmp_path / "data.db"
        c = create_repositories(db_path=db)
        try:
            # 类型与 Protocol
            assert isinstance(c, RepositoryContainer)
            # 6 个属性都在
            for attr in ("learning", "personal_vocab", "exam", "grade", "vocab_cache", "user"):
                assert hasattr(c, attr), f"缺少属性 {attr}"
            # 文件已创建
            assert db.exists()
        finally:
            c.close()

    def test_explicit_local(self, tmp_path):
        """显式 mode='local' 等价于默认"""
        db = tmp_path / "explicit.db"
        c = create_repositories(mode="local", db_path=db)
        try:
            assert isinstance(c, RepositoryContainer)
        finally:
            c.close()

    def test_local_with_cache_path(self, tmp_path):
        """local 模式 + 独立 cache_path"""
        db = tmp_path / "main.db"
        cache = tmp_path / "cache.db"
        c = create_repositories(mode="local", db_path=db, cache_path=cache)
        try:
            assert cache.exists()
        finally:
            c.close()


# =============================================================
# 2. online 模式
# =============================================================


@pytest.mark.skipif(not _MYSQL_AVAILABLE, reason="MySQL 依赖未安装")
class TestOnlineMode:
    def test_online_returns_mysql_container(self):
        """mode='online' 返回满足 Protocol 的 MySQL 容器"""
        c = create_repositories(mode="online")
        try:
            assert isinstance(c, RepositoryContainer)
        finally:
            c.close()

    def test_online_passes_url(self):
        """connection_url 透传到容器内部"""
        from ielts_buddy.repositories.mysql_repo import _build_mysql_url
        custom = _build_mysql_url(database="ietls_learn_online")
        c = create_repositories(mode="online", connection_url=custom)
        try:
            # 验证 engine URL 是我们传的
            url_str = str(c._engine.url)
            assert "ietls_learn_online" in url_str
        finally:
            c.close()

    def test_online_empty_url_uses_default(self):
        """connection_url='' 不报错，落到模块默认 URL"""
        c = create_repositories(mode="online", connection_url="")
        try:
            url_str = str(c._engine.url)
            # 默认是 118.190.148.121:3306
            assert "118.190.148.121" in url_str
            assert "3306" in url_str
        finally:
            c.close()


# =============================================================
# 3. mode 校验
# =============================================================


class TestModeValidation:
    def test_invalid_mode_raises(self, tmp_path):
        with pytest.raises(ValueError, match="未知 mode"):
            create_repositories(mode="cloud", db_path=tmp_path / "x.db")

    def test_empty_string_invalid(self, tmp_path):
        with pytest.raises(ValueError, match="未知 mode"):
            create_repositories(mode="", db_path=tmp_path / "x.db")

    def test_case_sensitive(self, tmp_path):
        """大小写敏感：'LOCAL' 不被接受（防误用）"""
        with pytest.raises(ValueError, match="未知 mode"):
            create_repositories(mode="LOCAL", db_path=tmp_path / "x.db")


# =============================================================
# 4. online 模式但依赖未安装
# =============================================================


class TestOnlineWithoutDeps:
    def test_online_raises_import_error_when_mysql_unavailable(self, tmp_path):
        """模拟 _MYSQL_AVAILABLE=False 时 online 模式抛 ImportError"""
        with patch("ielts_buddy.repositories._MYSQL_AVAILABLE", False):
            with pytest.raises(ImportError, match="SQLAlchemy"):
                create_repositories(mode="online")

    def test_local_still_works_when_mysql_unavailable(self, tmp_path):
        """MySQL 不可用时 local 模式仍能用"""
        with patch("ielts_buddy.repositories._MYSQL_AVAILABLE", False):
            c = create_repositories(mode="local", db_path=tmp_path / "ok.db")
            try:
                assert isinstance(c, RepositoryContainer)
            finally:
                c.close()


# =============================================================
# 5. close() 幂等 + Protocol 一致性
# =============================================================


class TestContainerLifecycle:
    def test_close_idempotent(self, tmp_path):
        c = create_repositories(mode="local", db_path=tmp_path / "c.db")
        c.close()
        c.close()  # 不应抛
        c.close()  # 第三次也行

    def test_satisfies_protocol(self, tmp_path):
        """工厂返回的实例满足 RepositoryContainer Protocol"""
        c = create_repositories(mode="local", db_path=tmp_path / "p.db")
        try:
            assert isinstance(c, RepositoryContainer)
        finally:
            c.close()


# =============================================================
# 6. 6 个属性名稳定（防止重命名破坏上层调用）
# =============================================================


class TestAttributeContract:
    """RepositoryContainer 协议约定的 6 个属性名必须保持。"""

    EXPECTED_ATTRS = ("learning", "personal_vocab", "exam", "grade", "vocab_cache", "user")

    def test_local_attrs_match_protocol(self, tmp_path):
        c = create_repositories(mode="local", db_path=tmp_path / "a.db")
        try:
            for attr in self.EXPECTED_ATTRS:
                assert hasattr(c, attr)
        finally:
            c.close()

    @pytest.mark.skipif(not _MYSQL_AVAILABLE, reason="MySQL 依赖未安装")
    def test_mysql_attrs_match_protocol(self):
        c = create_repositories(mode="online")
        try:
            for attr in self.EXPECTED_ATTRS:
                assert hasattr(c, attr)
        finally:
            c.close()
