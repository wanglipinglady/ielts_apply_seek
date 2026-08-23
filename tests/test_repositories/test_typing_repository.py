"""SQLiteTypingRepository 单测。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ielts_buddy.core.models import TypingRecord
from ielts_buddy.repositories import (
    SQLiteRepositoryContainer,
    create_sqlite_repositories,
)


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture
def container(tmp_path: Path) -> SQLiteRepositoryContainer:
    return create_sqlite_repositories(db_path=tmp_path / "test.db")


@pytest.fixture
def repo(container: SQLiteRepositoryContainer):
    return container.typing


def _make_record(
    user_id: int = 1,
    mode: str = "words",
    prompt_text: str = "the quick brown fox",
    typed_text: str = "the quick brown fax",
    duration_sec: int = 10,
    wpm: float = 30.0,
    accuracy: float = 0.95,
    error_count: int = 1,
    total_chars: int = 19,
    completed: bool = True,
    created_at: str | None = None,
) -> TypingRecord:
    return TypingRecord(
        user_id=user_id,
        mode=mode,
        prompt_text=prompt_text,
        typed_text=typed_text,
        duration_sec=duration_sec,
        wpm=wpm,
        accuracy=accuracy,
        error_count=error_count,
        total_chars=total_chars,
        completed=completed,
        created_at=created_at or datetime.now().isoformat(timespec="seconds"),
    )


# =============================================================
# save_record
# =============================================================


class TestSaveRecord:

    def test_save_returns_int_id(self, repo):
        rec = _make_record()
        rid = repo.save_record(1, rec)
        assert isinstance(rid, int)
        assert rid > 0

    def test_save_persists_full_record(self, repo):
        rec = _make_record(
            user_id=1,
            mode="sentences",
            prompt_text="Climate change is a serious issue.",
            typed_text="climate change is a serius issue.",
            wpm=27.5,
            accuracy=0.92,
            error_count=2,
            total_chars=35,
        )
        rid = repo.save_record(1, rec)
        rows = repo.get_history(1)
        assert len(rows) == 1
        loaded = rows[0]
        assert loaded.user_id == 1
        assert loaded.mode == "sentences"
        assert loaded.prompt_text == rec.prompt_text
        assert loaded.typed_text == rec.typed_text
        assert loaded.wpm == 27.5
        assert loaded.accuracy == 0.92
        assert loaded.error_count == 2
        assert loaded.total_chars == 35
        # 注:repo 不回填 rec.id(只是 intsave 返回);history 里 dict→TypingRecord 无 id


class TestGetHistory:

    def test_get_history_empty_returns_empty_list(self, repo):
        assert repo.get_history(1) == []
        assert repo.get_history(99) == []

    def test_get_history_descending_by_id(self, repo):
        for i in range(3):
            repo.save_record(1, _make_record(wpm=float(10 + i), prompt_text=f"prompt{i}"))
        rows = repo.get_history(1)
        # get_history 是按 id DESC,最近的在最前
        assert len(rows) == 3
        # 验证第一条是最后保存的(wpm=12)
        assert rows[0].wpm == 12.0
        assert rows[0].prompt_text == "prompt2"

    def test_get_history_with_mode_filter(self, repo):
        repo.save_record(1, _make_record(mode="words", prompt_text="w1"))
        repo.save_record(1, _make_record(mode="sentences", prompt_text="s1"))
        repo.save_record(1, _make_record(mode="words", prompt_text="w2"))

        words = repo.get_history(1, mode="words")
        assert len(words) == 2
        assert all(r.mode == "words" for r in words)

        sentences = repo.get_history(1, mode="sentences")
        assert len(sentences) == 1
        assert sentences[0].mode == "sentences"

    def test_get_history_limit(self, repo):
        for i in range(5):
            repo.save_record(1, _make_record(prompt_text=f"p{i}"))
        assert len(repo.get_history(1, limit=2)) == 2


# =============================================================
# Aggregate metrics: count / avg / max
# =============================================================


class TestAggregateMetrics:

    def test_history_count_empty(self, repo):
        assert repo.get_history_count(1) == 0
        assert repo.get_history_count(1, mode="words") == 0

    def test_history_count_with_mode(self, repo):
        repo.save_record(1, _make_record(mode="words", prompt_text="w1"))
        repo.save_record(1, _make_record(mode="words", prompt_text="w2"))
        repo.save_record(1, _make_record(mode="sentences", prompt_text="s1"))

        assert repo.get_history_count(1) == 3
        assert repo.get_history_count(1, mode="words") == 2
        assert repo.get_history_count(1, mode="sentences") == 1

    def test_average_wpm(self, repo):
        repo.save_record(1, _make_record(wpm=20.0, prompt_text="a"))
        repo.save_record(1, _make_record(wpm=30.0, prompt_text="b"))
        repo.save_record(1, _make_record(wpm=40.0, prompt_text="c"))

        avg = repo.get_average_wpm(1)
        # 三次 (20+30+40)/3 = 30
        assert abs(avg - 30.0) < 0.01

    def test_average_accuracy(self, repo):
        repo.save_record(1, _make_record(accuracy=0.90, prompt_text="a"))
        repo.save_record(1, _make_record(accuracy=0.95, prompt_text="b"))
        avg = repo.get_average_accuracy(1)
        # 平均 0.925
        assert abs(avg - 0.925) < 0.001

    def test_max_wpm(self, repo):
        for wpm in (10.0, 50.0, 30.0):
            repo.save_record(1, _make_record(wpm=wpm, prompt_text=f"p{wpm}"))
        assert repo.get_max_wpm(1) == 50.0

    def test_max_wpm_no_records(self, repo):
        assert repo.get_max_wpm(99) == 0.0

    def test_user_isolation(self, repo):
        repo.save_record(1, _make_record(user_id=1, wpm=10.0, prompt_text="u1"))
        repo.save_record(2, _make_record(user_id=2, wpm=20.0, prompt_text="u2"))
        repo.save_record(3, _make_record(user_id=3, wpm=30.0, prompt_text="u3"))

        # 不同用户的记录互不可见
        assert len(repo.get_history(1)) == 1
        assert len(repo.get_history(2)) == 1
        assert len(repo.get_history(3)) == 1
        assert repo.get_history(1)[0].wpm == 10.0
        assert repo.get_history(2)[0].wpm == 20.0
        assert repo.get_history(3)[0].wpm == 30.0

        assert repo.get_history_count(1) == 1
        assert repo.get_average_wpm(1) == 10.0
        assert repo.get_max_wpm(1) == 10.0

    def test_aggregate_per_mode_isolation(self, repo):
        repo.save_record(1, _make_record(mode="words", wpm=10.0, prompt_text="w1"))
        repo.save_record(1, _make_record(mode="sentences", wpm=40.0, prompt_text="s1"))

        assert repo.get_average_wpm(1, mode="words") == 10.0
        assert repo.get_average_wpm(1, mode="sentences") == 40.0
        assert repo.get_max_wpm(1, mode="words") == 10.0
        assert repo.get_max_wpm(1, mode="sentences") == 40.0


# =============================================================
# 边界 & 鲁棒性
# =============================================================


class TestEdgeCases:

    def test_save_completed_true_false(self, repo):
        repo.save_record(1, _make_record(completed=True, prompt_text="c1"))
        repo.save_record(1, _make_record(completed=False, prompt_text="c2"))
        rows = repo.get_history(1)
        assert len(rows) == 2
        completed_values = {r.completed for r in rows}
        assert completed_values == {True, False}

    def test_large_typed_text(self, repo):
        long_text = "a" * 4000
        rec = _make_record(prompt_text=long_text, typed_text=long_text)
        rid = repo.save_record(1, rec)
        assert rid > 0
        rows = repo.get_history(1)
        assert rows[0].prompt_text == long_text

    def test_zero_wpm_no_records(self, repo):
        # 用户无记录时返回 0 / 0.0
        assert repo.get_history_count(999) == 0
        assert repo.get_average_wpm(999) == 0.0
        assert repo.get_average_accuracy(999) == 0.0
        assert repo.get_max_wpm(999) == 0.0
