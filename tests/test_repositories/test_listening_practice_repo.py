"""SQLiteListeningPracticeRepository 单元测试（v3.7 P2 新增）。

覆盖:
1. seed_question 插入 + upsert
2. get_question + options 反序列化
3. list_sections_with_counts / list_sets_by_section / list_questions_by_set
4. set_audio_path 持久化
5. record_attempt + is_correct 校验
6. list_user_attempts + section 过滤
7. get_user_stats 聚合(全量 + 按 section)
8. list_expired_audio_paths 30 天清理边界
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ielts_buddy.repositories.sqlite_repo import (
    SQLiteListeningPracticeRepository,
    SQLiteRepositoryContainer,
)


@pytest.fixture
def repo(tmp_path: Path) -> SQLiteListeningPracticeRepository:
    """构造独立的 SQLite 文件 + 容器,避免污染其他测试。"""
    db_path = tmp_path / "listening.db"
    container = SQLiteRepositoryContainer(db_path=db_path)
    yield container.listening_practice  # type: ignore[attr-defined]
    container.close()


def _seed(
    repo: SQLiteListeningPracticeRepository,
    section: int = 1,
    set_id: int = 1,
    qid: int = 1,
    scenario: str = "租房",
    audio_path: str | None = None,
    audio_generated_at: str | None = None,
    options: list[str] | None = None,
) -> int:
    return repo.seed_question(
        section=section, set_id=set_id, qid=qid, scenario=scenario,
        question_type="multiple_choice",
        stem=f"Question {qid} of set {set_id}?",
        options=options or ["A. opt1", "B. opt2", "C. opt3", "D. opt4"],
        answer="A",
        explanation="Because.",
        transcript="Hello, this is a test transcript.",
        audio_path=audio_path,
        audio_generated_at=audio_generated_at,
    )


def test_seed_question_inserts_then_returns_id(repo):
    qid = _seed(repo, section=1, set_id=1, qid=1)
    assert qid > 0


def test_seed_question_is_upsert(repo):
    """同 (section, set_id, qid) 重复 seed → 仍返回相同 id 且字段更新。"""
    qid_first = _seed(repo, scenario="first")
    qid_second = _seed(repo, scenario="second")
    assert qid_first == qid_second
    item = repo.get_question(qid_first)
    assert item is not None
    assert item["scenario"] == "second"


def test_get_question_returns_none_for_missing(repo):
    assert repo.get_question(99999) is None


def test_get_question_parses_options(repo):
    qid = _seed(repo, options=["A. yes", "B. no"])
    item = repo.get_question(qid)
    assert item is not None
    assert item["options"] == ["A. yes", "B. no"]


def test_get_question_handles_null_options(repo):
    """填空题 options=None。"""
    qid = repo.seed_question(
        section=4, set_id=1, qid=1, scenario="lecture",
        question_type="form_completion",
        stem="The lecturer's name is ___.",
        options=None, answer="Smith",
        explanation="explicit", transcript="...",
    )
    item = repo.get_question(qid)
    assert item is not None
    assert item["options"] is None


def test_list_sections_with_counts(repo):
    _seed(repo, section=1, set_id=1, qid=1)
    _seed(repo, section=1, set_id=1, qid=2)
    _seed(repo, section=1, set_id=2, qid=1)
    _seed(repo, section=2, set_id=1, qid=1)
    counts = repo.list_sections_with_counts()
    by_section = {c["section"]: c for c in counts}
    assert by_section[1]["total_sets"] == 2
    assert by_section[1]["total_questions"] == 3
    assert by_section[2]["total_sets"] == 1
    assert by_section[2]["total_questions"] == 1


def test_list_sets_by_section_aggregates_per_set(repo):
    _seed(repo, section=1, set_id=1, qid=1, scenario="rent")
    _seed(repo, section=1, set_id=1, qid=2, scenario="rent")
    _seed(repo, section=1, set_id=2, qid=1, scenario="tour")
    sets = repo.list_sets_by_section(1)
    assert len(sets) == 2
    by_id = {s["set_id"]: s for s in sets}
    assert by_id[1]["scenario"] == "rent"
    assert by_id[1]["question_count"] == 2
    assert by_id[2]["scenario"] == "tour"
    assert by_id[2]["question_count"] == 1


def test_list_sets_by_section_excludes_other_sections(repo):
    _seed(repo, section=1, set_id=1, qid=1)
    _seed(repo, section=2, set_id=1, qid=1)
    sets = repo.list_sets_by_section(1)
    assert len(sets) == 1
    assert sets[0]["section"] == 1


def test_list_questions_by_set_orders_by_qid(repo):
    _seed(repo, section=1, set_id=1, qid=3)
    _seed(repo, section=1, set_id=1, qid=1)
    _seed(repo, section=1, set_id=1, qid=2)
    items = repo.list_questions_by_set(1, 1)
    assert [it["qid"] for it in items] == [1, 2, 3]


def test_set_audio_path_updates_audio_fields(repo):
    qid = _seed(repo, audio_path=None)
    repo.set_audio_path(
        qid,
        audio_path="/cache/audio/s1/q1.mp3",
        audio_generated_at="2026-08-23T10:00:00",
    )
    item = repo.get_question(qid)
    assert item["audio_path"] == "/cache/audio/s1/q1.mp3"
    assert item["audio_generated_at"] == "2026-08-23T10:00:00"


def test_count_questions_starts_at_zero(repo):
    assert repo.count_questions() == 0
    _seed(repo, section=1, set_id=1, qid=1)
    _seed(repo, section=2, set_id=1, qid=1)
    assert repo.count_questions() == 2


def test_record_attempt_returns_id_and_persists(repo):
    qid = _seed(repo)
    aid = repo.record_attempt(
        user_id=100, question_id=qid,
        user_answer="A", is_correct=True,
        duration_sec=15.5, played_count=2,
    )
    assert aid > 0


def test_list_user_attempts_filters_by_section(repo):
    qid1 = _seed(repo, section=1, set_id=1, qid=1)
    qid2 = _seed(repo, section=2, set_id=1, qid=1)
    repo.record_attempt(user_id=100, question_id=qid1,
                         user_answer="A", is_correct=True)
    repo.record_attempt(user_id=100, question_id=qid2,
                         user_answer="B", is_correct=False)

    items_s1, total_s1 = repo.list_user_attempts(100, section=1)
    assert total_s1 == 1
    assert items_s1[0]["section"] == 1

    items_all, total_all = repo.list_user_attempts(100)
    assert total_all == 2


def test_list_user_attempts_isolation_by_user(repo):
    qid = _seed(repo)
    repo.record_attempt(user_id=100, question_id=qid,
                         user_answer="A", is_correct=True)
    repo.record_attempt(user_id=200, question_id=qid,
                         user_answer="B", is_correct=False)
    items_100, total_100 = repo.list_user_attempts(100)
    items_200, total_200 = repo.list_user_attempts(200)
    assert total_100 == 1 and total_200 == 1
    assert items_100[0]["is_correct"] == 1
    assert items_200[0]["is_correct"] == 0


def test_list_user_attempts_orders_by_created_desc(repo):
    qid = _seed(repo)
    aid_old = repo.record_attempt(
        user_id=100, question_id=qid,
        user_answer="A", is_correct=True,
    )
    # 手动更新 created_at 让第二条更新
    repo._conn.execute(
        "UPDATE listening_attempts SET created_at=? WHERE id=?",
        ((datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds"),
         aid_old),
    )
    repo._conn.commit()
    aid_new = repo.record_attempt(
        user_id=100, question_id=qid,
        user_answer="B", is_correct=False,
    )
    items, _ = repo.list_user_attempts(100)
    assert items[0]["id"] == aid_new


def test_get_user_stats_aggregates_correctly(repo):
    qid1 = _seed(repo, section=1, set_id=1, qid=1)
    qid2 = _seed(repo, section=1, set_id=1, qid=2)
    qid3 = _seed(repo, section=2, set_id=1, qid=1)
    repo.record_attempt(user_id=100, question_id=qid1,
                         user_answer="A", is_correct=True)
    repo.record_attempt(user_id=100, question_id=qid2,
                         user_answer="A", is_correct=False)
    repo.record_attempt(user_id=100, question_id=qid3,
                         user_answer="A", is_correct=True)

    stats = repo.get_user_stats(100)
    assert stats["total_attempts"] == 3
    assert stats["correct_count"] == 2
    assert stats["accuracy"] == round(2 / 3 * 100, 1)
    assert stats["by_section"][1]["attempts"] == 2
    assert stats["by_section"][1]["correct"] == 1
    assert stats["by_section"][1]["accuracy"] == 50.0
    assert stats["by_section"][2]["attempts"] == 1
    assert stats["by_section"][2]["correct"] == 1
    assert stats["by_section"][2]["accuracy"] == 100.0


def test_get_user_stats_returns_zero_when_no_attempts(repo):
    stats = repo.get_user_stats(99999)
    assert stats["total_attempts"] == 0
    assert stats["correct_count"] == 0
    assert stats["accuracy"] == 0.0
    assert stats["by_section"] == {}


def test_list_expired_audio_paths_respects_retention(repo):
    """30 天前的 audio → 出现在列表;2 天前的不出现。"""
    now_iso = datetime.now().isoformat(timespec="seconds")
    long_ago = (datetime.now() - timedelta(days=40)).isoformat(
        timespec="seconds"
    )

    qid_old = _seed(
        repo, section=1, set_id=1, qid=1,
        audio_path="/cache/audio/old.mp3",
        audio_generated_at=long_ago,
    )
    qid_new = _seed(
        repo, section=2, set_id=1, qid=1,
        audio_path="/cache/audio/new.mp3",
        audio_generated_at=now_iso,
    )

    expired = repo.list_expired_audio_paths(30)
    expired_ids = {qid for qid, _ in expired}
    assert qid_old in expired_ids
    assert qid_new not in expired_ids


def test_list_expired_audio_paths_handles_null_audio(repo):
    """audio_path=NULL 的不入清理列表。"""
    qid = _seed(repo, audio_path=None, audio_generated_at=None)
    expired = repo.list_expired_audio_paths(0)
    assert all(eq != qid for eq, _ in expired)


def test_container_exposes_listening_practice(tmp_path: Path):
    """RepositoryContainer 必须有 listening_practice 属性。"""
    container = SQLiteRepositoryContainer(db_path=tmp_path / "db")
    try:
        assert hasattr(container, "listening_practice")
        assert isinstance(
            container.listening_practice,
            SQLiteListeningPracticeRepository,
        )
    finally:
        container.close()


def test_seed_question_unique_constraint_same_section_set_qid_raises(
    repo, tmp_path: Path
):
    """不同 stem 但同 (section, set_id, qid) → upsert 走 UPDATE 路径。"""
    qid_first = _seed(repo, section=1, set_id=1, qid=1)
    # 直接调 seed_question 不走 _seed 助手,改 answer
    qid_second = repo.seed_question(
        section=1, set_id=1, qid=1,
        scenario="changed",
        question_type="multiple_choice",
        stem="changed stem",
        options=["X. changed"], answer="X",
        explanation="new explanation",
        transcript="new transcript",
    )
    assert qid_first == qid_second
    item = repo.get_question(qid_first)
    assert item is not None
    assert item["answer"] == "X"
    assert item["scenario"] == "changed"
    assert item["stem"] == "changed stem"