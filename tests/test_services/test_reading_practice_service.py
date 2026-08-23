"""``reading_practice_service`` 业务层单测（v3.8 P3.2 Sprint 2 新增）。

覆盖:
1. seed_initial_reading:题库为空时种子;已有题时跳过
2. seed_initial_reading:LLM 不可用走 mock 也能落库
3. ReadingPracticeService.list_sections:返回 Section 概览(含 user stats)
4. ReadingPracticeService.list_sets:按 Section 列套题
5. ReadingPracticeService.start_set:返回完整题组(过滤敏感字段)
6. ReadingPracticeService.start_random_set:任意 Section 抽一套
7. ReadingPracticeService.start_set:不存在的 set → None
8. ReadingPracticeService.get_question:返回单题(过滤敏感字段)
9. ReadingPracticeService.submit_answer:tfng 容错(T/F/True/False/NG)
10. ReadingPracticeService.submit_answer:multiple_choice 大小写
11. ReadingPracticeService.submit_answer:summary 大小写+去标点
12. ReadingPracticeService.submit_answer:找下一题
13. ReadingPracticeService.submit_answer:question 不存在 → None
14. ReadingPracticeService.get_user_stats:聚合格式
15. ReadingPracticeService.list_history:分页+section 过滤
"""
from __future__ import annotations

from pathlib import Path

from ielts_buddy.repositories.fallback_repo import create_fallback_container
from ielts_buddy.services.reading_practice_service import (
    ReadingPracticeService,
    SECTION_LABELS,
    QUESTION_TYPE_LABELS,
    seed_initial_reading,
)


# =============================================================
# Helpers
# =============================================================


def _make_container(tmp_path: Path):
    sqlite_path = tmp_path / "web.db"
    return create_fallback_container(
        sqlite_db_path=sqlite_path,
        mysql_url="",
        prefer_mode="sqlite",
    )


def _seed_passages(container, section="easy", set_id=1, count=3, qtype="multiple_choice"):
    """落 N 道题。"""
    repo = container.reading_practice
    for i in range(1, count + 1):
        repo.seed_passage(
            section=section, set_id=set_id, qid=i,
            passage_number=((i - 1) // 2) + 1,
            title=f"Title {section}-{set_id}-{i}",
            topic="Test Topic",
            question_type=qtype,
            word_count=650,
            passage_text=(
                f"This is passage {i} about topic. "
                f"It discusses several points relevant to question {i}."
            ),
            stem=f"Question {i}: what does the text say?",
            options=(["A opt", "B opt", "C opt", "D opt"]
                     if qtype in ("multiple_choice", "matching") else None),
            answer="A" if qtype in ("multiple_choice", "matching") else "key_term",
            explanation=f"Explanation {i}.",
            source_line=i,
        )


# =============================================================
# seed_initial_reading
# =============================================================


class TestSeedInitialReading:
    def test_skips_when_passages_exist(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        _seed_passages(container, "easy", 1, 3)
        result = seed_initial_reading(
            container, sections={"easy": 10, "medium": 8, "hard": 7, "academic": 5},
        )
        assert result["skipped"] is True
        assert result["seeded_passages"] == 0

    def test_seeds_when_empty(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        result = seed_initial_reading(
            container, sections={"easy": 1, "medium": 0, "hard": 0, "academic": 0},
        )
        assert result["skipped"] is False
        # easy 1 套:约 10 题(根据 question_count)
        assert result["seeded_passages"] >= 5
        # 再次调用应跳过
        result2 = seed_initial_reading(
            container, sections={"easy": 1, "medium": 0, "hard": 0, "academic": 0},
        )
        assert result2["skipped"] is True


# =============================================================
# ReadingPracticeService - 列表 / 概览
# =============================================================


class TestReadingServiceList:
    def _make_service(self, tmp_path: Path, user_id: int = 1):
        container = _make_container(tmp_path)
        _seed_passages(container, "easy", 1, 3)
        _seed_passages(container, "medium", 1, 3)
        svc = ReadingPracticeService(container=container, user_id=user_id)
        return svc, container

    def test_section_labels_defined(self) -> None:
        assert "easy" in SECTION_LABELS
        assert "medium" in SECTION_LABELS
        assert "hard" in SECTION_LABELS
        assert "academic" in SECTION_LABELS

    def test_question_type_labels_defined(self) -> None:
        for qt in ("tfng", "multiple_choice", "matching",
                   "summary", "sentence_completion"):
            assert qt in QUESTION_TYPE_LABELS

    def test_list_sections_returns_with_counts(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        sections = svc.list_sections()
        sec_keys = {s["section"] for s in sections}
        assert "easy" in sec_keys
        assert "medium" in sec_keys
        for s in sections:
            assert "name" in s
            assert "total_sets" in s
            assert "total_passages" in s
            assert "user_attempts" in s
            # 无做题 → user_accuracy 为 None
            assert s["user_accuracy"] is None

    def test_list_sections_includes_user_accuracy_after_attempts(
        self, tmp_path: Path,
    ) -> None:
        svc, container = self._make_service(tmp_path)
        qs = container.reading_practice.list_passages_by_set("easy", 1)
        # 做对 1 道做错 1 道
        svc.submit_answer(int(qs[0]["id"]), "A", duration_sec=10)
        svc.submit_answer(int(qs[1]["id"]), "WRONG", duration_sec=10)
        sections = svc.list_sections()
        easy = next(s for s in sections if s["section"] == "easy")
        assert easy["user_attempts"] == 2
        assert easy["user_accuracy"] == 50.0

    def test_list_sets_filters_by_section(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        sets = svc.list_sets("easy")
        assert len(sets) >= 1
        assert sets[0]["set_id"] == 1


# =============================================================
# ReadingPracticeService - 抽题
# =============================================================


class TestReadingServiceStart:
    def _make_service(self, tmp_path: Path, user_id: int = 1):
        container = _make_container(tmp_path)
        _seed_passages(container, "easy", 1, 3)
        _seed_passages(container, "easy", 2, 3)
        svc = ReadingPracticeService(container=container, user_id=user_id)
        return svc, container

    def test_start_set_returns_full_set(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        result = svc.start_set("easy", 1)
        assert result is not None
        assert result["section"] == "easy"
        assert result["set_id"] == 1
        assert len(result["questions"]) == 3
        # 过滤敏感字段
        for q in result["questions"]:
            assert "answer" not in q
            assert "explanation" not in q
            assert q["id"]
            assert q["question_type_label"]

    def test_start_set_returns_none_for_missing(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        result = svc.start_set("easy", 99)
        assert result is None

    def test_start_random_returns_a_set(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        result = svc.start_random_set()
        assert result is not None
        assert result["section"] in ("easy", "medium", "hard", "academic")
        assert result["set_id"] >= 1

    def test_start_random_filters_section(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        for _ in range(5):
            result = svc.start_random_set(section="easy")
            assert result is not None
            assert result["section"] == "easy"

    def test_get_question_returns_normalized(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        qs = container.reading_practice.list_passages_by_set("easy", 1)
        q = svc.get_question(int(qs[0]["id"]))
        assert q is not None
        # 过滤敏感字段
        assert "answer" not in q
        assert "explanation" not in q

    def test_get_question_missing_returns_none(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        result = svc.get_question(99999)
        assert result is None


# =============================================================
# ReadingPracticeService - 判分
# =============================================================


class TestReadingServiceSubmit:
    def _make_service(self, tmp_path: Path, user_id: int = 1):
        container = _make_container(tmp_path)
        # 加各种题型
        _seed_passages(container, "easy", 1, 1, qtype="tfng")
        _seed_passages(container, "easy", 2, 1, qtype="multiple_choice")
        _seed_passages(container, "easy", 3, 1, qtype="summary")
        _seed_passages(container, "easy", 4, 1, qtype="sentence_completion")
        # 修改特定题目的答案便于测试
        repo = container.reading_practice
        # TFNG 题答 T
        tfng_qs = repo.list_passages_by_set("easy", 1)
        repo._conn.execute(
            "UPDATE reading_passages SET answer='T' WHERE id=?",
            (int(tfng_qs[0]["id"]),)
        )
        repo._conn.commit()
        # summary 题答 'key term'
        summary_qs = repo.list_passages_by_set("easy", 3)
        repo._conn.execute(
            "UPDATE reading_passages SET answer='key term' WHERE id=?",
            (int(summary_qs[0]["id"]),)
        )
        repo._conn.commit()
        svc = ReadingPracticeService(container=container, user_id=user_id)
        return svc, container

    def test_submit_tfng_correct(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        q = container.reading_practice.list_passages_by_set("easy", 1)[0]
        out = svc.submit_answer(int(q["id"]), "T", duration_sec=10)
        assert out is not None
        assert out["is_correct"] is True
        assert out["correct_answer"] == "T"

    def test_submit_tfng_lowercase_true(self, tmp_path: Path) -> None:
        """T/F/True/False/NG 都归一化。"""
        svc, container = self._make_service(tmp_path)
        q = container.reading_practice.list_passages_by_set("easy", 1)[0]
        out = svc.submit_answer(int(q["id"]), "true")
        assert out["is_correct"] is True

    def test_submit_tfng_wrong(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        q = container.reading_practice.list_passages_by_set("easy", 1)[0]
        out = svc.submit_answer(int(q["id"]), "F")
        assert out["is_correct"] is False

    def test_submit_multiple_choice_case_insensitive(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        q = container.reading_practice.list_passages_by_set("easy", 2)[0]
        out = svc.submit_answer(int(q["id"]), "a")
        assert out["is_correct"] is True

    def test_submit_summary_normalizes_punctuation(self, tmp_path: Path) -> None:
        """summary:大小写不敏感 + 去标点 + 多空格合并。"""
        svc, container = self._make_service(tmp_path)
        q = container.reading_practice.list_passages_by_set("easy", 3)[0]
        out = svc.submit_answer(int(q["id"]), "Key, Term!")
        assert out["is_correct"] is True

    def test_submit_returns_next_question_id(self, tmp_path: Path) -> None:
        """同 set 的下一题 qid。"""
        # 多放一道在 set 5
        container = _make_container(tmp_path)
        _seed_passages(container, "easy", 5, 1, qtype="multiple_choice")
        _seed_passages(container, "easy", 5, 2, qtype="multiple_choice")
        svc = ReadingPracticeService(container=container, user_id=1)
        qs = container.reading_practice.list_passages_by_set("easy", 5)
        sorted_qs = sorted(qs, key=lambda x: int(x["qid"]))
        out = svc.submit_answer(int(sorted_qs[0]["id"]), "A")
        # 下一题 qid 不为 None
        assert out["next_question_id"] is not None
        assert out["next_question_id"] == int(sorted_qs[1]["id"])

    def test_submit_last_question_returns_none_next(self, tmp_path: Path) -> None:
        """做最后一题 → next_question_id=None。"""
        container = _make_container(tmp_path)
        _seed_passages(container, "easy", 6, 1, qtype="multiple_choice")
        svc = ReadingPracticeService(container=container, user_id=1)
        qs = container.reading_practice.list_passages_by_set("easy", 6)
        out = svc.submit_answer(int(qs[0]["id"]), "A")
        assert out["next_question_id"] is None

    def test_submit_missing_question_returns_none(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        result = svc.submit_answer(99999, "A")
        assert result is None

    def test_submit_records_attempt(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        q = container.reading_practice.list_passages_by_set("easy", 1)[0]
        _, total_before = container.reading_practice.list_user_attempts(1, 1, 100)
        svc.submit_answer(int(q["id"]), "T")
        _, total_after = container.reading_practice.list_user_attempts(1, 1, 100)
        assert total_after == total_before + 1


# =============================================================
# ReadingPracticeService - 统计 + 历史
# =============================================================


class TestReadingServiceStats:
    def _make_service(self, tmp_path: Path, user_id: int = 1):
        container = _make_container(tmp_path)
        _seed_passages(container, "easy", 1, 1, qtype="multiple_choice")
        _seed_passages(container, "easy", 2, 1, qtype="multiple_choice")
        svc = ReadingPracticeService(container=container, user_id=user_id)
        return svc, container

    def test_user_stats_empty(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        stats = svc.get_user_stats()
        assert stats["total_attempts"] == 0
        assert stats["correct"] == 0
        assert stats["accuracy"] is None
        assert stats["by_section"] == {}

    def test_user_stats_after_attempts(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        qs = container.reading_practice.list_passages_by_set("easy", 1)
        # 答对 + 答错
        svc.submit_answer(int(qs[0]["id"]), "A")
        # 第 2 套同样 A 也是对的
        qs2 = container.reading_practice.list_passages_by_set("easy", 2)
        svc.submit_answer(int(qs2[0]["id"]), "B")  # 错
        stats = svc.get_user_stats()
        assert stats["total_attempts"] == 2
        assert stats["correct"] == 1
        assert stats["accuracy"] == 50.0

    def test_list_history_pagination(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        qs = container.reading_practice.list_passages_by_set("easy", 1)
        qs2 = container.reading_practice.list_passages_by_set("easy", 2)
        svc.submit_answer(int(qs[0]["id"]), "A")
        svc.submit_answer(int(qs2[0]["id"]), "A")
        rows, total = svc.list_history(page=1, size=1)
        assert total == 2
        assert len(rows) == 1
        rows2, _ = svc.list_history(page=2, size=1)
        assert len(rows2) == 1
        assert rows[0]["id"] != rows2[0]["id"]

    def test_list_history_filter_section(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        # 加个 medium 套
        _seed_passages(container, "medium", 1, 1, qtype="multiple_choice")
        medium_qs = container.reading_practice.list_passages_by_set("medium", 1)
        easy_qs = container.reading_practice.list_passages_by_set("easy", 1)
        svc.submit_answer(int(easy_qs[0]["id"]), "A")
        svc.submit_answer(int(medium_qs[0]["id"]), "A")
        rows_easy, _ = svc.list_history(section="easy")
        rows_medium, _ = svc.list_history(section="medium")
        for r in rows_easy:
            assert r["section"] == "easy"
        for r in rows_medium:
            assert r["section"] == "medium"
