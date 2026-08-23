"""Repository Protocol 合规性测试。

W1 阶段：仅测试 Protocol 本身的方法签名（方法存在性 + 参数列表）。
W2/W3 阶段：测试 SQLite / MySQL 实现的运行时合规性。

关联方案: docs/方案_数据层扩展_v2.2.md §14 W1.3
"""
from __future__ import annotations

import inspect

import pytest

from ielts_buddy.core import repository as r


# =============================================================
# 1. LearningRepository — 方法签名测试
# =============================================================


class TestLearningRepositoryProtocol:
    """LearningRepository 必须有 13 个方法（v3.6 起 +3 错词本），且全部带 user_id。"""

    REQUIRED_METHODS = {
        "get_record",
        "upsert_record",
        "toggle_star",
        "toggle_difficult",
        "get_due_words",
        "get_due_count",
        "get_history",
        "get_all_records",
        "get_learned_count",
        "get_learned_words_today",
        # v3.6 错词本新增 3 个
        "get_wrong_words",
        "reset_mistake",
        "get_mistake_stats",
    }

    def test_required_methods_exist(self):
        actual = {n for n in dir(r.LearningRepository) if not n.startswith("_")}
        missing = self.REQUIRED_METHODS - actual
        assert not missing, f"LearningRepository 缺失方法: {missing}"

    @pytest.mark.parametrize(
        "method_name",
        sorted([
            "get_record", "upsert_record", "toggle_star", "toggle_difficult",
            "get_due_words", "get_due_count", "get_history",
            "get_all_records", "get_learned_count", "get_learned_words_today",
            # v3.6 错词本
            "get_wrong_words", "reset_mistake", "get_mistake_stats",
        ]),
    )
    def test_all_methods_take_user_id_as_first_param(self, method_name: str):
        """强制每个方法第一个非 self 参数是 user_id。"""
        method = getattr(r.LearningRepository, method_name)
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())
        # Protocol 方法签名: [self, user_id, ...] - 跳过 self
        assert len(params) >= 2, f"LearningRepository.{method_name} 参数过少: {params}"
        assert params[1] == "user_id", (
            f"LearningRepository.{method_name} 第二个参数（除 self）应是 user_id，"
            f"实际是 {params[1]}，完整签名: {params}"
        )


# =============================================================
# 2. PersonalVocabRepository — 方法签名测试
# =============================================================


class TestPersonalVocabRepositoryProtocol:
    """PersonalVocabRepository 必须有 18 个方法，且全部带 user_id。"""

    REQUIRED_METHODS = {
        "add_word", "edit_word", "delete_word", "get_word", "list_words",
        "create_category", "delete_category", "list_categories",
        "add_to_category", "remove_from_category", "get_word_categories",
        "add_mistake", "add_from_grading",
        "get_source_distribution", "get_band_distribution",
        "import_words", "export_words",
        # 额外 1 个：get_word_count
        "get_word_count",
    }

    def test_required_methods_exist(self):
        actual = {n for n in dir(r.PersonalVocabRepository) if not n.startswith("_")}
        missing = self.REQUIRED_METHODS - actual
        assert not missing, f"PersonalVocabRepository 缺失方法: {missing}"

    @pytest.mark.parametrize(
        "method_name",
        sorted([
            "add_word", "edit_word", "delete_word", "get_word", "list_words",
            "create_category", "delete_category", "list_categories",
            "add_to_category", "remove_from_category", "get_word_categories",
            "add_mistake", "add_from_grading",
            "get_source_distribution", "get_band_distribution",
            "import_words", "export_words", "get_word_count",
        ]),
    )
    def test_all_methods_take_user_id_as_first_param(self, method_name: str):
        method = getattr(r.PersonalVocabRepository, method_name)
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())
        assert len(params) >= 2, f"PersonalVocabRepository.{method_name} 参数过少: {params}"
        assert params[1] == "user_id", (
            f"PersonalVocabRepository.{method_name} 第二个参数应是 user_id，实际是 {params[1]}"
        )


# =============================================================
# 3. ExamRepository
# =============================================================


class TestExamRepositoryProtocol:
    """ExamRepository 必须有 5 个方法，且全部带 user_id。"""

    REQUIRED_METHODS = {
        "create_exam", "submit_answer", "finish_exam",
        "get_exam_history", "get_exam_session",
    }

    def test_required_methods_exist(self):
        actual = {n for n in dir(r.ExamRepository) if not n.startswith("_")}
        missing = self.REQUIRED_METHODS - actual
        assert not missing, f"ExamRepository 缺失方法: {missing}"

    @pytest.mark.parametrize(
        "method_name",
        sorted(["create_exam", "submit_answer", "finish_exam",
                "get_exam_history", "get_exam_session"]),
    )
    def test_all_methods_take_user_id_as_first_param(self, method_name: str):
        method = getattr(r.ExamRepository, method_name)
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())
        assert len(params) >= 2, f"ExamRepository.{method_name} 参数过少: {params}"
        assert params[1] == "user_id", (
            f"ExamRepository.{method_name} 第二个参数应是 user_id，实际是 {params[1]}"
        )


# =============================================================
# 4. GradeRepository
# =============================================================


class TestGradeRepositoryProtocol:
    """GradeRepository 必须有 4 个方法，且全部带 user_id。"""

    REQUIRED_METHODS = {
        "save_result", "get_history", "get_average_score", "get_error_trend",
    }

    def test_required_methods_exist(self):
        actual = {n for n in dir(r.GradeRepository) if not n.startswith("_")}
        missing = self.REQUIRED_METHODS - actual
        assert not missing, f"GradeRepository 缺失方法: {missing}"

    @pytest.mark.parametrize(
        "method_name",
        sorted(["save_result", "get_history", "get_average_score", "get_error_trend"]),
    )
    def test_all_methods_take_user_id_as_first_param(self, method_name: str):
        method = getattr(r.GradeRepository, method_name)
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())
        assert len(params) >= 2, f"GradeRepository.{method_name} 参数过少: {params}"
        assert params[1] == "user_id", (
            f"GradeRepository.{method_name} 第二个参数应是 user_id，实际是 {params[1]}"
        )


# =============================================================
# 5. VocabCacheRepository — 不带 user_id
# =============================================================


class TestVocabCacheRepositoryProtocol:
    """VocabCacheRepository 是共享缓存，5 个方法都不应有 user_id 参数。"""

    METHODS = ["get_cached", "put_cached", "get_mtime", "set_mtime", "clear_cache"]

    def test_required_methods_exist(self):
        actual = {n for n in dir(r.VocabCacheRepository) if not n.startswith("_")}
        expected = set(self.METHODS)
        missing = expected - actual
        assert not missing, f"VocabCacheRepository 缺失方法: {missing}"

    @pytest.mark.parametrize("method_name", METHODS)
    def test_no_user_id_in_methods(self, method_name: str):
        method = getattr(r.VocabCacheRepository, method_name)
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())
        assert "user_id" not in params, (
            f"VocabCacheRepository.{method_name} 不应含 user_id 参数，实际是 {params}"
        )


# =============================================================
# 6. UserRepository
# =============================================================


class TestUserRepositoryProtocol:
    """UserRepository 必须有 5 个方法。"""

    REQUIRED_METHODS = {
        "get_or_create", "get_by_id", "update_last_login",
        "list_users", "ensure_system_categories",
    }

    def test_required_methods_exist(self):
        actual = {n for n in dir(r.UserRepository) if not n.startswith("_")}
        missing = self.REQUIRED_METHODS - actual
        assert not missing, f"UserRepository 缺失方法: {missing}"

    def test_ensure_system_categories_signature(self):
        """ensure_system_categories 必须以 user_id 为第一参数（3-A 决策）。"""
        method = r.UserRepository.ensure_system_categories
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())
        assert len(params) >= 2, "ensure_system_categories 参数过少"
        assert params[1] == "user_id", (
            f"UserRepository.ensure_system_categories 第二个参数应是 user_id，实际是 {params[1]}"
        )


# =============================================================
# 7. RepositoryContainer — 聚合容器
# =============================================================


class TestRepositoryContainerProtocol:
    """RepositoryContainer 聚合 6 个 Repository + close 方法。

    注：Protocol 的属性用 ``__annotations__`` 声明（PEP 544），
    不出现在 ``dir()`` 里。``close`` 是方法，出现在 ``dir()`` 里。
    """

    REQUIRED_REPO_ATTRS = {
        "learning", "personal_vocab", "exam", "grade", "vocab_cache", "user",
    }

    def test_required_repo_attrs_in_annotations(self):
        """6 个 Repository 属性应在 __annotations__ 中声明。"""
        annotations = getattr(r.RepositoryContainer, "__annotations__", {})
        missing = self.REQUIRED_REPO_ATTRS - set(annotations.keys())
        assert not missing, f"RepositoryContainer __annotations__ 缺失: {missing}"

    def test_close_is_method(self):
        """close 应是可调用方法。"""
        assert callable(getattr(r.RepositoryContainer, "close", None)), (
            "RepositoryContainer.close 应是可调用方法"
        )

    def test_all_required_present(self):
        """6 个 Repository + close 全部到位。"""
        annotations = set(getattr(r.RepositoryContainer, "__annotations__", {}).keys())
        assert annotations == self.REQUIRED_REPO_ATTRS, (
            f"RepositoryContainer 属性集合不对: 实际 {annotations}"
        )
        assert callable(getattr(r.RepositoryContainer, "close", None))


# =============================================================
# 8. assert_repository_implements_protocol 工具测试
# =============================================================


class TestAssertProtocol:
    """运行时断言工具的正确性。"""

    def test_passes_for_complete_implementation(self):
        """完整实现应通过断言。"""

        class FakeLearning:
            def get_record(self, user_id, word): pass
            def upsert_record(self, user_id, word, correct, source="builtin"): pass
            def toggle_star(self, user_id, word): pass
            def toggle_difficult(self, user_id, word): pass
            def get_due_words(self, user_id, limit=20): pass
            def get_due_count(self, user_id): pass
            def get_history(self, user_id, days=30): pass
            def get_all_records(self, user_id): pass
            def get_learned_count(self, user_id): pass
            def get_learned_words_today(self, user_id): pass
            # v3.6 错词本新增 3 个
            def get_wrong_words(self, user_id, min_wrong=1, days=None, limit=200): pass
            def reset_mistake(self, user_id, word): pass
            def get_mistake_stats(self, user_id): pass

        # 不应抛错
        r.assert_repository_implements_protocol(FakeLearning(), r.LearningRepository)

    def test_raises_for_missing_methods(self):
        """不完整实现应抛 TypeError 并列出缺失方法。"""

        class IncompleteLearning:
            def get_record(self, user_id, word): pass
            # 其他 9 个方法缺失

        with pytest.raises(TypeError, match="缺失方法"):
            r.assert_repository_implements_protocol(
                IncompleteLearning(), r.LearningRepository
            )

    def test_error_message_lists_all_missing_methods(self):
        """错误信息应列出全部缺失方法。"""

        class Empty:
            pass

        with pytest.raises(TypeError) as exc_info:
            r.assert_repository_implements_protocol(Empty(), r.LearningRepository)
        msg = str(exc_info.value)
        # 至少包含几个关键方法名
        for name in ("get_record", "upsert_record", "toggle_star"):
            assert name in msg, f"错误信息应包含缺失方法 {name}，实际: {msg}"

    def test_works_for_personal_vocab_repository(self):
        """PersonalVocabRepository 同样应能校验。"""

        class FakePV:
            # 故意只实现一半方法
            def add_word(self, user_id, pw): pass
            def get_word(self, user_id, word): pass

        with pytest.raises(TypeError, match="缺失方法"):
            r.assert_repository_implements_protocol(FakePV(), r.PersonalVocabRepository)


# =============================================================
# 9. 交叉验证：Protocol 一致性
# =============================================================


class TestProtocolConsistency:
    """Protocol 之间的内部一致性。"""

    def test_all_protocols_have_distinct_method_counts(self):
        """6 个 Repository 的方法数应当不同（防止命名重复）。"""
        sizes = {
            "LearningRepository": 13,
            "PersonalVocabRepository": 18,
            "ExamRepository": 5,
            "GradeRepository": 4,
            "VocabCacheRepository": 5,
            "UserRepository": 5,
        }
        actual = {}
        for name, expected in sizes.items():
            cls = getattr(r, name)
            methods = {
                m for m in dir(cls)
                if not m.startswith("_") and callable(getattr(cls, m, None))
            }
            actual[name] = len(methods)
            assert len(methods) == expected, (
                f"{name} 实际方法数 {len(methods)} 与预期 {expected} 不符"
            )

    def test_protocol_module_exports(self):
        """__all__ 应包含 6 个 Protocol + 工具函数 + Container。"""
        expected = {
            "LearningRepository", "PersonalVocabRepository", "ExamRepository",
            "GradeRepository", "VocabCacheRepository", "UserRepository",
            "RepositoryContainer", "assert_repository_implements_protocol",
        }
        actual = set(r.__all__)
        assert actual == expected, f"__all__ 不一致: 缺 {expected - actual}, 多 {actual - expected}"
