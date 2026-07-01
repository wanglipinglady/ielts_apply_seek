"""个人词库服务：管理用户自定义单词和分类，SQLite 存储

W2 阶段：所有 SQL 调用委托给 SQLitePersonalVocabRepository。
公开 API 保持不变（commands 层和测试无需修改）。
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ielts_buddy.core.models import PersonalWord, VocabCategory, Word
from ielts_buddy.repositories import create_sqlite_repositories


class PersonalVocabService:
    """个人词库管理服务（W2: 委托给 Repository）"""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            from ielts_buddy.core.config import get_db_path
            db_path = get_db_path()
        self._container = create_sqlite_repositories(db_path=db_path)
        self._repo = self._container.personal_vocab
        self._user_id = 1

    def close(self) -> None:
        self._container.close()

    # ---- 向后兼容 ----

    @property
    def _conn(self):
        return self._container._conn

    @property
    def _db_path(self) -> Path:
        return self._container._db_path

    # ---- 单词 CRUD ----

    def add_word(self, word: PersonalWord) -> PersonalWord:
        """添加单词到个人词库，返回带 id 的 PersonalWord"""
        self._repo.add_word(self._user_id, word)
        return self._repo.get_word(self._user_id, word.word)  # type: ignore[return-value]

    def edit_word(self, word_name: str, **kwargs) -> PersonalWord:
        """编辑个人词库中的单词字段"""
        return self._repo.edit_word(self._user_id, word_name, **kwargs)

    def delete_word(self, word_name: str) -> bool:
        """删除个人词库中的单词，返回是否成功"""
        return self._repo.delete_word(self._user_id, word_name)

    def get_word(self, word_name: str) -> PersonalWord | None:
        """查询个人词库中的单词"""
        return self._repo.get_word(self._user_id, word_name)

    def list_words(
        self,
        category: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[PersonalWord], int]:
        """列出个人词库单词，支持按分类筛选和分页"""
        return self._repo.list_words(self._user_id, category, page, per_page)

    def get_word_count(self) -> int:
        """获取个人词库总词数"""
        return self._repo.get_word_count(self._user_id)

    # ---- 分类管理 ----

    def create_category(self, name: str, description: str = "") -> VocabCategory:
        """创建新分类"""
        return self._repo.create_category(self._user_id, name, description)

    def delete_category(self, name: str) -> bool:
        """删除分类（系统分类不可删除）"""
        return self._repo.delete_category(self._user_id, name)

    def list_categories(self) -> list[VocabCategory]:
        """列出所有分类及其词数"""
        return self._repo.list_categories(self._user_id)

    def add_word_to_category(self, word_name: str, category_name: str) -> bool:
        """将单词添加到分类"""
        return self._repo.add_to_category(self._user_id, word_name, category_name)

    def remove_word_from_category(self, word_name: str, category_name: str) -> bool:
        """从分类中移除单词"""
        return self._repo.remove_from_category(self._user_id, word_name, category_name)

    def get_word_categories(self, word_name: str) -> list[VocabCategory]:
        """获取单词所属的所有分类"""
        return self._repo.get_word_categories(self._user_id, word_name)

    def add_mistake(self, word: Word | PersonalWord, source: str = "quiz_mistake") -> PersonalWord:
        """将错词添加到个人词库的 mistakes 分类（去重）"""
        return self._repo.add_mistake(self._user_id, word, source)

    def add_from_grading(
        self, word: str, context: str = "", suggestion: str = "", comment: str = "",
    ) -> PersonalWord:
        """从写作批改结果中添加单词到个人词库"""
        return self._repo.add_from_grading(self._user_id, word, context, suggestion, comment)

    def to_word(self, pw: PersonalWord) -> Word:
        """将 PersonalWord 转换为 Word 对象（用于复习系统集成）"""
        return Word(
            word=pw.word,
            phonetic=pw.phonetic,
            meaning=pw.meaning,
            pos=pw.pos,
            band=pw.band,
            topic=pw.topic,
            example=pw.example,
            example_cn=pw.example_cn,
            is_custom=True,
        )

    # ---- 统计 ----

    def get_category_stats(self) -> list[dict]:
        """获取各分类的统计信息"""
        cats = self.list_categories()
        return [
            {
                "name": c.name,
                "description": c.description,
                "is_system": c.is_system,
                "word_count": c.word_count,
            }
            for c in cats
        ]

    def get_source_distribution(self) -> dict[str, int]:
        """获取词库来源分布"""
        return self._repo.get_source_distribution(self._user_id)

    def get_band_distribution(self) -> dict[int, int]:
        """获取个人词库的 band 分布"""
        return self._repo.get_band_distribution(self._user_id)

    # ---- 批量导入导出 ----

    def import_words(self, file_path: Path, vocab_service=None) -> dict[str, int]:
        """批量导入单词，支持 JSON / CSV / 纯文本格式"""
        return self._repo.import_words(self._user_id, file_path, vocab_service)

    def export_words(
        self,
        fmt: str = "json",
        category: str | None = None,
    ) -> str:
        """导出个人词库为 JSON 或 CSV 字符串"""
        return self._repo.export_words(self._user_id, fmt, category)
