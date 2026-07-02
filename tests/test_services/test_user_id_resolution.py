"""W5 阶段：Service 端 user_id 解析行为测试

测试范围：
1. 5 个有 user_id 的 Service 全部支持 user_id 显式注入
2. 5 个 Service 显式传 user_id > env > config > 1 的解析优先级
3. 显式传 user_id=0 仍能使用（系统模板场景）
4. 显式传 user_id=100（不存在的）能让 Service 跑通容器内调用
   （不会做"该用户是否存在"校验，那是 UserRepository.get_or_create 的职责）
5. 显式传 user_id 与 db_path 互不干扰（两个独立参数）
6. 老调用方式 Service(db_path=...) 行为不变（默认 user_id=1）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ielts_buddy.services.exam_service import ExamService
from ielts_buddy.services.grading_service import GradingService
from ielts_buddy.services.personal_vocab_service import PersonalVocabService
from ielts_buddy.services.review_service import ReviewService
from ielts_buddy.services.stats_service import StatsService


# 5 个有 self._user_id 的 Service
SERVICES_WITH_USER_ID = [
    StatsService,
    ReviewService,
    PersonalVocabService,
    ExamService,
    GradingService,
]


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离环境变量 + config 目录，确保不污染用户真实配置。"""
    monkeypatch.setenv("IELTS_BUDDY_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("IELTS_BUDDY_USER_ID", raising=False)
    monkeypatch.delenv("IELTS_BUDDY_MODE", raising=False)
    monkeypatch.delenv("MYSQL_URL", raising=False)
    yield tmp_path / "home"


# =============================================================
# 1. 显式 user_id 注入
# =============================================================


class TestExplicitUserId:
    """Service(user_id=N) 直接使用传入的 user_id。"""

    @pytest.mark.parametrize(
        "svc_cls",
        SERVICES_WITH_USER_ID,
        ids=lambda c: c.__name__,
    )
    def test_explicit_user_id_used(self, isolated_home, tmp_path, svc_cls):
        svc = svc_cls(db_path=tmp_path / "x.db", user_id=123)
        try:
            assert svc._user_id == 123
        finally:
            svc.close()

    @pytest.mark.parametrize(
        "svc_cls",
        SERVICES_WITH_USER_ID,
        ids=lambda c: c.__name__,
    )
    def test_explicit_user_id_zero_allowed(self, isolated_home, tmp_path, svc_cls):
        """user_id=0 是合法值（系统模板分类场景）"""
        svc = svc_cls(db_path=tmp_path / "x.db", user_id=0)
        try:
            assert svc._user_id == 0
        finally:
            svc.close()

    @pytest.mark.parametrize(
        "svc_cls",
        SERVICES_WITH_USER_ID,
        ids=lambda c: c.__name__,
    )
    def test_explicit_user_id_very_large(self, isolated_home, tmp_path, svc_cls):
        """user_id=99999999（实际不存在的用户）也能让 Service 跑通容器初始化"""
        svc = svc_cls(db_path=tmp_path / "x.db", user_id=99999999)
        try:
            assert svc._user_id == 99999999
        finally:
            svc.close()


# =============================================================
# 2. 隐式解析（env > config > 1）
# =============================================================


class TestImplicitUserId:
    """未传 user_id 时按 get_user_id() 解析（env > config > 1）。"""

    @pytest.mark.parametrize(
        "svc_cls",
        SERVICES_WITH_USER_ID,
        ids=lambda c: c.__name__,
    )
    def test_default_is_one(self, isolated_home, tmp_path, svc_cls):
        """env 不设 + config 不写 → 默认 1"""
        svc = svc_cls(db_path=tmp_path / "x.db")
        try:
            assert svc._user_id == 1
        finally:
            svc.close()

    @pytest.mark.parametrize(
        "svc_cls",
        SERVICES_WITH_USER_ID,
        ids=lambda c: c.__name__,
    )
    def test_env_overrides_default(
        self, isolated_home, tmp_path, svc_cls, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("IELTS_BUDDY_USER_ID", "55")
        svc = svc_cls(db_path=tmp_path / "x.db")
        try:
            assert svc._user_id == 55
        finally:
            svc.close()

    @pytest.mark.parametrize(
        "svc_cls",
        SERVICES_WITH_USER_ID,
        ids=lambda c: c.__name__,
    )
    def test_config_user_id_used(
        self, isolated_home, tmp_path, svc_cls, monkeypatch: pytest.MonkeyPatch
    ):
        """config.database.user_id 生效"""
        from ielts_buddy.core.config import Config
        cfg = Config()
        cfg.set("database.user_id", 77)
        # 触发保存（默认在 app_dir/config.toml，隔离了 IELTS_BUDDY_HOME）
        cfg.save()
        svc = svc_cls(db_path=tmp_path / "x.db")
        try:
            assert svc._user_id == 77
        finally:
            svc.close()


# =============================================================
# 3. 参数独立性：db_path 和 user_id 互不干扰
# =============================================================


class TestParameterIndependence:
    """db_path 和 user_id 是两个独立参数，可任意组合。"""

    def test_only_db_path(self, isolated_home, tmp_path):
        """只传 db_path → user_id 默认 1（兼容老调用方式）"""
        svc = StatsService(db_path=tmp_path / "x.db")
        try:
            assert svc._user_id == 1
        finally:
            svc.close()

    def test_only_user_id(self, isolated_home, tmp_path, monkeypatch: pytest.MonkeyPatch):
        """只传 user_id → db_path 走 config（这里用 env 强制 local）"""
        monkeypatch.setenv("IELTS_BUDDY_MODE", "local")
        svc = StatsService(user_id=42)
        try:
            assert svc._user_id == 42
            # db_path 已从 config.get_db_path() 拿，容器能正常建
            assert svc._container is not None
        finally:
            svc.close()

    def test_neither_uses_config(self, isolated_home, tmp_path, monkeypatch: pytest.MonkeyPatch):
        """两个都不传 → 走 config（env 强制 local 保证不出网）"""
        monkeypatch.setenv("IELTS_BUDDY_MODE", "local")
        monkeypatch.delenv("IELTS_BUDDY_USER_ID", raising=False)
        svc = StatsService()
        try:
            assert svc._user_id == 1
            assert svc._container is not None
        finally:
            svc.close()


# =============================================================
# 4. 端到端：user_id 真的影响数据落库
# =============================================================


class TestUserIdEndsUpInData:
    """验证 user_id 真的被传到 Repository，不会因为缓存而错位。"""

    def test_review_user_id_isolated(self, isolated_home, tmp_path):
        """两个 user_id 写入的记录互不串（用独立 db_path 模拟真实用户场景）"""
        a = ReviewService(db_path=tmp_path / "a.db", user_id=10)
        b = ReviewService(db_path=tmp_path / "b.db", user_id=20)
        try:
            from ielts_buddy.core.models import Word
            w = Word(word="test", meaning="测试", band=5, pos="n.")
            a.record_learn(w, correct=True)
            # 跨 db 看不到
            assert b._repo.get_record(10, "test") is None
            assert a._repo.get_record(20, "test") is None
            # 自己看得到
            assert a._repo.get_record(10, "test") is not None
            assert b._repo.get_record(20, "test") is None  # b 自己没写
        finally:
            a.close()
            b.close()


# =============================================================
# 5. 向后兼容：老调用方式不变
# =============================================================


class TestBackwardCompatibility:
    """W4 之前的代码调用 Service(db_path=...) 行为完全不变。"""

    def test_old_call_signature(self, isolated_home, tmp_path):
        """W4 之前的 Service(db_path=tmp_path/...) 仍能跑通"""
        svc = StatsService(db_path=tmp_path / "old.db")
        try:
            # 三个不变性
            assert svc._user_id == 1
            assert svc._container is not None
            assert hasattr(svc, "close")
        finally:
            svc.close()
