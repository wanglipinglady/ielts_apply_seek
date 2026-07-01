"""Repository 抽象层。

W1 阶段定义接口契约，不含任何实现。W2 / W3 分别实现 SQLite / MySQL。
所有方法必须带 ``user_id`` 参数（共享缓存除外），强制数据隔离。

关联方案: docs/方案_数据层扩展_v2.2.md §14 W1.1
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from ielts_buddy.core.models import (
    ExamReport,
    ExamSession,
    GradeResult,
    LearningRecord,
    PersonalWord,
    VocabCategory,
    Word,
)


# =============================================================
# 1. LearningRepository — 学习记录 + 艾宾浩斯复习
# =============================================================


@runtime_checkable
class LearningRepository(Protocol):
    """学习记录仓储接口。

    设计要点：
      - 所有方法都带 ``user_id: int``，强制数据隔离
      - 读写分离：``record_*`` / ``upsert_*`` 走写；``get_*`` 走只读
      - 返回 Pydantic 模型，不返回 ``sqlite3.Row`` / ``dict``
    """

    # ---- 单条记录 ----
    def get_record(self, user_id: int, word: str) -> Optional[LearningRecord]:
        """获取单词的学习记录；不存在则返回 None。"""
        ...

    def upsert_record(
        self,
        user_id: int,
        word: Word,
        correct: bool,
        source: str = "builtin",
    ) -> LearningRecord:
        """插入或更新学习记录，自动推进艾宾浩斯 level。"""
        ...

    def toggle_star(self, user_id: int, word: str) -> bool:
        """切换收藏状态，返回切换后的值。"""
        ...

    def toggle_difficult(self, user_id: int, word: str) -> bool:
        """切换"难词"标记，返回切换后的值。"""
        ...

    # ---- 复习计划 ----
    def get_due_words(self, user_id: int, limit: int = 20) -> list[dict]:
        """获取到期需复习的单词。"""
        ...

    def get_due_count(self, user_id: int) -> int:
        """到期单词数量。"""
        ...

    def get_history(self, user_id: int, days: int = 30) -> list[dict]:
        """最近 N 天的学习活动（每日聚合）。"""
        ...

    # ---- 全量查询 ----
    def get_all_records(self, user_id: int) -> list[LearningRecord]:
        """该用户全部学习记录。"""
        ...

    def get_learned_count(self, user_id: int) -> int:
        """已学过的单词总数（去重）。"""
        ...

    def get_learned_words_today(self, user_id: int) -> list[str]:
        """今日新学的单词列表。"""
        ...


# =============================================================
# 2. PersonalVocabRepository — 个人词库 + 分类
# =============================================================


@runtime_checkable
class PersonalVocabRepository(Protocol):
    """个人词库仓储接口。

    包含：单词 CRUD、分类管理、错词自动收录、批量导入导出。
    """

    # ---- 单词 CRUD ----
    def add_word(self, user_id: int, pw: PersonalWord) -> int:
        """新增单词，返回新行 id。"""
        ...

    def edit_word(self, user_id: int, word_name: str, **kwargs: Any) -> PersonalWord:
        """编辑单词字段；返回更新后的实例。"""
        ...

    def delete_word(self, user_id: int, word_name: str) -> bool:
        """删除单词，返回是否成功。"""
        ...

    def get_word(self, user_id: int, word_name: str) -> Optional[PersonalWord]:
        """获取单词详情；不存在返回 None。"""
        ...

    def list_words(
        self,
        user_id: int,
        category: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[PersonalWord], int]:
        """分页列出单词，返回 (列表, 总数)。"""
        ...

    def get_word_count(self, user_id: int) -> int:
        """个人词库单词总数。"""
        ...

    # ---- 分类管理 ----
    def create_category(
        self,
        user_id: int,
        name: str,
        description: str = "",
    ) -> VocabCategory:
        """创建分类。"""
        ...

    def delete_category(self, user_id: int, name: str) -> bool:
        """删除分类（系统分类 is_system=1 禁止删除）。"""
        ...

    def list_categories(self, user_id: int) -> list[VocabCategory]:
        """列出该用户的所有分类（含系统分类）。"""
        ...

    def add_to_category(
        self,
        user_id: int,
        word: str,
        category: str,
    ) -> bool:
        """把单词加入分类。"""
        ...

    def remove_from_category(
        self,
        user_id: int,
        word: str,
        category: str,
    ) -> bool:
        """从分类移除单词。"""
        ...

    def get_word_categories(
        self,
        user_id: int,
        word: str,
    ) -> list[VocabCategory]:
        """获取单词所属的所有分类。"""
        ...

    # ---- 特殊方法 ----
    def add_mistake(
        self,
        user_id: int,
        word: Word | PersonalWord,
        source: str = "quiz_mistake",
    ) -> PersonalWord:
        """收录错词到 mistakes 分类。"""
        ...

    def add_from_grading(
        self,
        user_id: int,
        word: str,
        context: str = "",
        suggestion: str = "",
        comment: str = "",
    ) -> PersonalWord:
        """从批改结果收录词汇。"""
        ...

    # ---- 统计 ----
    def get_source_distribution(self, user_id: int) -> dict[str, int]:
        """按来源统计单词数。"""
        ...

    def get_band_distribution(self, user_id: int) -> dict[int, int]:
        """按 Band 统计单词数。"""
        ...

    # ---- 导入导出 ----
    def import_words(
        self,
        user_id: int,
        file_path: Any,
        vocab_service: Any = None,
    ) -> dict[str, int]:
        """从文件导入单词，返回 {'success': N, 'failed': M}。"""
        ...

    def export_words(
        self,
        user_id: int,
        fmt: str = "json",
        category: Optional[str] = None,
    ) -> str:
        """导出为 JSON / CSV / 纯文本，返回文件内容字符串。"""
        ...


# =============================================================
# 3. ExamRepository — 模拟考试
# =============================================================


@runtime_checkable
class ExamRepository(Protocol):
    """模拟考试仓储接口。"""

    def create_exam(
        self,
        user_id: int,
        band: int,
        count: int,
        time_limit: int = 20,
    ) -> ExamSession:
        """创建一场模拟考试。"""
        ...

    def submit_answer(
        self,
        user_id: int,
        session_id: str,
        q_index: int,
        answer: str,
    ) -> dict:
        """提交一题答案，返回判分结果 {'correct': bool, 'answer': str}。"""
        ...

    def finish_exam(self, user_id: int, session_id: str) -> ExamReport:
        """完成考试，生成报告。"""
        ...

    def get_exam_history(
        self,
        user_id: int,
        limit: int = 20,
    ) -> list[dict]:
        """获取历史考试记录。"""
        ...

    def get_exam_session(
        self,
        user_id: int,
        session_id: str,
    ) -> Optional[ExamSession]:
        """获取考试会话详情（含题目）。"""
        ...


# =============================================================
# 4. GradeRepository — AI 写作批改历史
# =============================================================


@runtime_checkable
class GradeRepository(Protocol):
    """批改结果仓储接口。"""

    def save_result(self, user_id: int, result: GradeResult) -> int:
        """保存批改结果，返回新行 id。"""
        ...

    def get_history(
        self,
        user_id: int,
        limit: int = 20,
        task_type: Optional[str] = None,
    ) -> list[GradeResult]:
        """获取批改历史，task_type 可选 'task1_academic' / 'task1_general' / 'task2'。"""
        ...

    def get_average_score(self, user_id: int) -> float:
        """平均分。"""
        ...

    def get_error_trend(self, user_id: int, limit: int = 10) -> list[dict]:
        """错误类型趋势。"""
        ...


# =============================================================
# 5. VocabCacheRepository — 大词库缓存
# =============================================================


@runtime_checkable
class VocabCacheRepository(Protocol):
    """词库缓存仓储接口。

    注：缓存层不带 ``user_id``（所有用户共享同一份词库）。
    只缓存内置词库（526 精选 / 4485 大词库），不存用户数据。
    """

    def get_cached(self, word: str) -> Optional[dict]:
        """读取缓存的词条；不存在返回 None。"""
        ...

    def put_cached(
        self,
        word: str,
        band: int,
        topic: str,
        payload: dict,
    ) -> None:
        """写入缓存。"""
        ...

    def get_mtime(self, key: str) -> str:
        """获取缓存元数据的 mtime。"""
        ...

    def set_mtime(self, key: str, value: str) -> None:
        """设置缓存元数据的 mtime。"""
        ...

    def clear_cache(self) -> None:
        """清空缓存（用于强制重建）。"""
        ...


# =============================================================
# 6. UserRepository — 用户表（仅联网模式用）
# =============================================================


@runtime_checkable
class UserRepository(Protocol):
    """用户表仓储接口。

    单机模式下 SQLite 实现为 no-op（固定返回 ``user_id=1``）。
    联网模式下走 MySQL，处理 ``username`` -> ``user_id`` 映射。
    """

    def get_or_create(self, username: str) -> int:
        """根据 username 获取或创建用户，返回 user_id。"""
        ...

    def get_by_id(self, user_id: int) -> Optional[dict]:
        """根据 user_id 获取用户信息（含 username / created_at / last_login_at）。"""
        ...

    def update_last_login(self, user_id: int) -> None:
        """更新 last_login_at 为当前时间。"""
        ...

    def list_users(self) -> list[dict]:
        """列出所有用户（仅联网模式有效）。"""
        ...

    # ---- 种子分类（3-A 决策） ----
    def ensure_system_categories(self, user_id: int) -> None:
        """用户首次进入联网模式时，从 user_id=0 模板复制系统分类。

        单机模式实现为 no-op；联网模式实现为
        ``INSERT INTO vocab_categories (user_id, name, ...) SELECT :uid, name, ... FROM vocab_categories WHERE user_id = 0``。
        """
        ...


# =============================================================
# 7. RepositoryContainer — 6 个 Repository 的容器
# =============================================================


@runtime_checkable
class RepositoryContainer(Protocol):
    """6 个 Repository 的聚合。

    ``db_factory.create_repositories()`` 返回此接口的实现。
    Services 接受一个 ``RepositoryContainer`` 注入。
    """

    learning: LearningRepository
    personal_vocab: PersonalVocabRepository
    exam: ExamRepository
    grade: GradeRepository
    vocab_cache: VocabCacheRepository
    user: UserRepository

    def close(self) -> None:
        """关闭所有底层连接（SQLite / MySQL 连接池）。"""
        ...


# =============================================================
# 8. 运行时断言工具
# =============================================================


def assert_repository_implements_protocol(
    instance: Any,
    protocol: type,
) -> None:
    """运行时检查 ``instance`` 是否满足 ``protocol`` 接口。

    用于 W3 阶段：``db_factory`` 创建的 Repository 集合应当通过此断言，
    确保实现完整，缺失方法立即 fail-fast。

    Args:
        instance: 待检查的实例。
        protocol: 目标 Protocol 类。

    Raises:
        TypeError: 如果 ``instance`` 缺少 ``protocol`` 要求的方法。
    """
    if not isinstance(instance, protocol):
        missing = _find_missing_methods(instance, protocol)
        raise TypeError(
            f"{type(instance).__name__} 未实现 {protocol.__name__}，"
            f"缺失方法: {missing}"
        )


def _find_missing_methods(instance: Any, protocol: type) -> list[str]:
    """找出 ``instance`` 缺失的 protocol 方法。"""
    proto_methods = {
        name
        for name in dir(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }
    impl_methods = set(dir(instance))
    return sorted(proto_methods - impl_methods)


__all__ = [
    "LearningRepository",
    "PersonalVocabRepository",
    "ExamRepository",
    "GradeRepository",
    "VocabCacheRepository",
    "UserRepository",
    "RepositoryContainer",
    "assert_repository_implements_protocol",
]
