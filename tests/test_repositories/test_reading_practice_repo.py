"""SQLiteReadingPracticeRepository 单元测试(v3.8 P3.2 新增)。

覆盖:
- seed_passage upsert(UNIQUE section+set_id+qid)
- get_passage (含 options JSON 解析)
- list_sections_with_counts / list_sets_by_section
- list_passages_by_set
- count_passages
- record_attempt + get_user_stats
- list_user_attempts 分页 + section 过滤
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from ielts_buddy.repositories.fallback_repo import create_fallback_container


def _make_container(tmp_path: Path):
    sqlite_path = tmp_path / "web.db"
    return create_fallback_container(
        sqlite_db_path=sqlite_path,
        mysql_url="",
        prefer_mode="sqlite",
    )


def _sample_passage(
    section="easy",
    set_id=1,
    qid=1,
    passage_number=1,
    title="The History of Tea",
    topic="Culture",
    question_type="multiple_choice",
    word_count=600,
    passage_text="Tea has a long history ...",
    stem="Q1 What is the main idea?",
    options=None,
    answer="A",
    explanation="Because the passage describes...",
    source_line=None,
):
    if options is None:
        options = ["First", "Second", "Third", "Fourth"]
    return dict(
        section=section, set_id=set_id, qid=qid,
        passage_number=passage_number, title=title, topic=topic,
        question_type=question_type, word_count=word_count,
        passage_text=passage_text, stem=stem,
        options=options, answer=answer,
        explanation=explanation, source_line=source_line,
    )


class TestReadingSeed:
    def test_seed_inserts_new_passage(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        pid = repo.seed_passage(**_sample_passage())
        assert pid > 0
        loaded = repo.get_passage(pid)
        assert loaded is not None
        assert loaded["title"] == "The History of Tea"
        assert loaded["options"] == ["First", "Second", "Third", "Fourth"]

    def test_seed_upserts_on_uk_violation(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        p1 = repo.seed_passage(**_sample_passage(qid=99, title="Original"))
        p2 = repo.seed_passage(**_sample_passage(qid=99, title="Updated"))
        assert p1 == p2
        loaded = repo.get_passage(p1)
        assert loaded["title"] == "Updated"

    def test_seed_form_completion_options_null(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        pid = repo.seed_passage(**_sample_passage(
            question_type="summary", options=False, answer="seventeenth century",
        ))
        loaded = repo.get_passage(pid)
        assert loaded["options"] is None
        assert loaded["answer"] == "seventeenth century"

    def test_seed_persists_word_count_and_source_line(
        self, tmp_path: Path
    ) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        pid = repo.seed_passage(**_sample_passage(
            word_count=750, source_line=12,
        ))
        loaded = repo.get_passage(pid)
        assert loaded["word_count"] == 750
        assert loaded["source_line"] == 12


class TestReadingRead:
    def test_get_passage_returns_none_for_missing(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        assert repo.get_passage(99999) is None

    def test_get_passage_invalid_options_json(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        pid = repo.seed_passage(**_sample_passage())
        # 直接污染 options_json(测试容错路径)
        repo._conn.execute(
            "UPDATE reading_passages SET options_json = ? WHERE id = ?",
            ("not-json", pid),
        )
        loaded = repo.get_passage(pid)
        # 解析失败时,SQLite 走 except 分支返回 []
        assert loaded["options"] == []


class TestReadingList:
    def _seed_full_set(self, repo, section="medium", set_id=1):
        for i in range(1, 4):
            repo.seed_passage(**_sample_passage(
                section=section, set_id=set_id, qid=i, passage_number=i,
                title=f"Passage {i}",
            ))

    def test_list_sections_with_counts(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        self._seed_full_set(repo, section="easy", set_id=1)
        self._seed_full_set(repo, section="medium", set_id=1)
        sections = repo.list_sections_with_counts()
        section_map = {s["section"]: s for s in sections}
        assert section_map["easy"]["total_sets"] == 1
        assert section_map["easy"]["total_passages"] == 3
        assert section_map["medium"]["total_passages"] == 3

    def test_list_sets_by_section(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        self._seed_full_set(repo, section="medium", set_id=1)
        self._seed_full_set(repo, section="medium", set_id=2)
        sets = repo.list_sets_by_section("medium")
        assert len(sets) == 2
        for s in sets:
            assert s["section"] == "medium"
            assert s["question_count"] == 3

    def test_list_passages_by_set(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        self._seed_full_set(repo, section="hard", set_id=1)
        items = repo.list_passages_by_set("hard", 1)
        assert len(items) == 3
        qids = [int(q["qid"]) for q in items]
        assert qids == [1, 2, 3]

    def test_count_passages(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        assert repo.count_passages() == 0
        self._seed_full_set(repo, set_id=1)
        self._seed_full_set(repo, set_id=2)
        assert repo.count_passages() == 6


class TestReadingAttempts:
    def test_record_attempt_correct(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        pid = repo.seed_passage(**_sample_passage())
        aid = repo.record_attempt(
            user_id=1, question_id=pid, user_answer="A",
            is_correct=True, duration_sec=45.5,
        )
        assert aid > 0
        items, total = repo.list_user_attempts(user_id=1, page=1, size=10)
        assert total == 1
        assert items[0]["question_id"] == pid
        assert items[0]["is_correct"] == 1
        assert items[0]["duration_sec"] == 45.5

    def test_record_attempt_wrong(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        pid = repo.seed_passage(**_sample_passage(answer="A"))
        repo.record_attempt(user_id=1, question_id=pid, user_answer="B", is_correct=False)
        stats = repo.get_user_stats(user_id=1)
        assert stats["total_attempts"] == 1
        assert stats["correct_count"] == 0

    def test_get_user_stats_by_section(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        p_easy = repo.seed_passage(**_sample_passage(section="easy", qid=1))
        p_med = repo.seed_passage(**_sample_passage(section="medium", qid=2))
        repo.record_attempt(user_id=1, question_id=p_easy, user_answer="A", is_correct=True)
        repo.record_attempt(user_id=1, question_id=p_easy, user_answer="B", is_correct=False)
        repo.record_attempt(user_id=1, question_id=p_med, user_answer="A", is_correct=True)
        stats = repo.get_user_stats(user_id=1)
        assert stats["total_attempts"] == 3
        assert stats["correct_count"] == 2
        assert "easy" in stats["by_section"]
        assert "medium" in stats["by_section"]
        assert stats["by_section"]["easy"]["attempts"] == 2

    def test_list_user_attempts_pagination(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        pid = repo.seed_passage(**_sample_passage())
        for _ in range(5):
            repo.record_attempt(user_id=1, question_id=pid, user_answer="A", is_correct=True)
        items_p1, total = repo.list_user_attempts(user_id=1, page=1, size=2)
        items_p2, _ = repo.list_user_attempts(user_id=1, page=2, size=2)
        assert total == 5
        assert len(items_p1) == 2
        assert len(items_p2) == 2
        # 不重叠
        p1_ids = {it["id"] for it in items_p1}
        p2_ids = {it["id"] for it in items_p2}
        assert p1_ids.isdisjoint(p2_ids)

    def test_list_user_attempts_filter_by_section(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.reading_practice
        p_easy = repo.seed_passage(**_sample_passage(section="easy", qid=1))
        p_med = repo.seed_passage(**_sample_passage(section="medium", qid=2))
        repo.record_attempt(user_id=1, question_id=p_easy, user_answer="A", is_correct=True)
        repo.record_attempt(user_id=1, question_id=p_med, user_answer="A", is_correct=True)
        items, total = repo.list_user_attempts(user_id=1, page=1, size=10, section="easy")
        assert total == 1
        assert items[0]["section"] == "easy"