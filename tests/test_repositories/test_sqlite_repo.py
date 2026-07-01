"""SQLiteRepository 单元测试

W2.3 阶段：覆盖 6 个 Repository 的全部方法。
"""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest

from ielts_buddy.core.models import (
    ExamQuestion,
    GradeDimension,
    GradeResult,
    PersonalWord,
    Word,
)
from ielts_buddy.repositories import (
    SQLiteExamRepository,
    SQLiteGradeRepository,
    SQLiteLearningRepository,
    SQLitePersonalVocabRepository,
    SQLiteRepositoryContainer,
    SQLiteUserRepository,
    SQLiteVocabCacheRepository,
)


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture
def tmp_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def container(tmp_dir: Path) -> SQLiteRepositoryContainer:
    c = SQLiteRepositoryContainer(
        db_path=tmp_dir / "data.db",
        cache_path=tmp_dir / "vocab_cache.db",
    )
    yield c
    # 显式关闭容器内的所有连接（Windows 文件句柄延迟）
    try:
        c.close()
    except Exception:
        pass


@pytest.fixture
def learning_repo(container: SQLiteRepositoryContainer) -> SQLiteLearningRepository:
    return container.learning


@pytest.fixture
def personal_vocab_repo(container: SQLiteRepositoryContainer) -> SQLitePersonalVocabRepository:
    return container.personal_vocab


@pytest.fixture
def exam_repo(container: SQLiteRepositoryContainer) -> SQLiteExamRepository:
    return container.exam


@pytest.fixture
def grade_repo(container: SQLiteRepositoryContainer) -> SQLiteGradeRepository:
    return container.grade


@pytest.fixture
def cache_repo(container: SQLiteRepositoryContainer) -> SQLiteVocabCacheRepository:
    return container.vocab_cache


@pytest.fixture
def user_repo(container: SQLiteRepositoryContainer) -> SQLiteUserRepository:
    return container.user


@pytest.fixture
def sample_word() -> Word:
    return Word(
        word="abandon",
        phonetic="/əˈbændən/",
        meaning="放弃",
        pos="v.",
        band=7,
        topic="study",
        example="abandon hope",
        example_cn="放弃希望",
        collocations=["abandon ship"],
        synonyms=["give up"],
    )


@pytest.fixture
def sample_word2() -> Word:
    return Word(
        word="benefit",
        phonetic="/ˈbɛnɪfɪt/",
        meaning="好处",
        pos="n.",
        band=6,
        topic="health",
    )


@pytest.fixture
def sample_personal_word() -> PersonalWord:
    return PersonalWord(
        word="custom",
        meaning="自定义",
        pos="n.",
        band=7,
        topic="misc",
        source="manual",
    )


@pytest.fixture
def sample_grade_result() -> GradeResult:
    now = datetime.now().isoformat(timespec="seconds")
    return GradeResult(
        user_id=1,
        overall_score=6.5,
        task_response=GradeDimension(score=6.0, comment="ok"),
        coherence=GradeDimension(score=6.5, comment="good"),
        lexical_resource=GradeDimension(score=7.0, comment="good"),
        grammar=GradeDimension(score=6.5, comment="ok"),
        suggestions=["more examples"],
        rewrite="Better rewrite",
        essay_text="Some essay text",
        topic="Some topic",
        task_type="task2",
        error_summary={"grammar": 2, "vocabulary": 1},
        graded_at=now,
    )


# =============================================================
# 1. LearningRepository
# =============================================================


class TestLearningRepository:
    def test_upsert_and_get(self, learning_repo, sample_word):
        rec = learning_repo.upsert_record(1, sample_word, correct=True)
        assert rec.memory_level == 1
        assert rec.learn_count == 1
        assert rec.correct_count == 1
        assert rec.wrong_count == 0

        got = learning_repo.get_record(1, "abandon")
        assert got is not None
        assert got.memory_level == 1

    def test_upsert_incorrect_lowers_level(self, learning_repo, sample_word):
        learning_repo.upsert_record(1, sample_word, correct=True)
        rec = learning_repo.upsert_record(1, sample_word, correct=False)
        assert rec.memory_level == 0
        assert rec.learn_count == 2
        assert rec.correct_count == 1
        assert rec.wrong_count == 1

    def test_get_record_none_for_missing(self, learning_repo):
        assert learning_repo.get_record(1, "nonexistent") is None

    def test_user_isolation(self, learning_repo, sample_word):
        learning_repo.upsert_record(1, sample_word, correct=True)
        assert learning_repo.get_record(1, "abandon") is not None
        assert learning_repo.get_record(2, "abandon") is None

    def test_toggle_star(self, learning_repo, sample_word):
        learning_repo.upsert_record(1, sample_word, correct=True)
        assert learning_repo.toggle_star(1, "abandon") is True
        assert learning_repo.toggle_star(1, "abandon") is False

    def test_toggle_star_raises_for_missing(self, learning_repo):
        with pytest.raises(ValueError, match="未找到"):
            learning_repo.toggle_star(1, "nonexistent")

    def test_toggle_difficult(self, learning_repo, sample_word):
        learning_repo.upsert_record(1, sample_word, correct=True)
        assert learning_repo.toggle_difficult(1, "abandon") is True

    def test_toggle_difficult_raises_for_missing(self, learning_repo):
        with pytest.raises(ValueError):
            learning_repo.toggle_difficult(1, "nonexistent")

    def test_get_due_words(self, learning_repo, sample_word, sample_word2):
        # level 1 -> next_review = today + 1 (not due)
        learning_repo.upsert_record(1, sample_word, correct=True)
        # level 0 -> next_review = today (due)
        learning_repo.upsert_record(1, sample_word2, correct=False)
        due = learning_repo.get_due_words(1, limit=10)
        # sample_word2 应该是 due 的（level 0, next=today）
        assert len(due) == 1
        assert due[0]["word"] == "benefit"
        # word_data 应是 Word 对象
        assert isinstance(due[0]["word_data"], Word)

    def test_get_due_count(self, learning_repo, sample_word):
        # sample_word level 1 -> next_review = tomorrow（不算 due）
        learning_repo.upsert_record(1, sample_word, correct=True)
        # 降低 level 让 next_review 变 today
        learning_repo.upsert_record(1, sample_word, correct=False)
        assert learning_repo.get_due_count(1) == 1

    def test_get_all_records(self, learning_repo, sample_word, sample_word2):
        learning_repo.upsert_record(1, sample_word, correct=True)
        learning_repo.upsert_record(1, sample_word2, correct=True)
        records = learning_repo.get_all_records(1)
        assert len(records) == 2

    def test_get_learned_count(self, learning_repo, sample_word, sample_word2):
        assert learning_repo.get_learned_count(1) == 0
        learning_repo.upsert_record(1, sample_word, correct=True)
        learning_repo.upsert_record(1, sample_word2, correct=True)
        assert learning_repo.get_learned_count(1) == 2

    def test_get_learned_words_today(self, learning_repo, sample_word):
        learning_repo.upsert_record(1, sample_word, correct=True)
        words = learning_repo.get_learned_words_today(1)
        assert "abandon" in words

    def test_get_history(self, learning_repo, sample_word):
        learning_repo.upsert_record(1, sample_word, correct=True)
        hist = learning_repo.get_history(1, days=7)
        assert len(hist) == 7
        today = date.today().isoformat()
        assert any(h["date"] == today and h["new_words"] >= 1 for h in hist)


# =============================================================
# 2. PersonalVocabRepository
# =============================================================


class TestPersonalVocabRepository:
    def test_add_and_get_word(self, personal_vocab_repo, sample_personal_word):
        word_id = personal_vocab_repo.add_word(1, sample_personal_word)
        assert word_id > 0
        got = personal_vocab_repo.get_word(1, "custom")
        assert got is not None
        assert got.meaning == "自定义"

    def test_add_word_duplicate_raises(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        with pytest.raises(ValueError, match="已存在"):
            personal_vocab_repo.add_word(1, sample_personal_word)

    def test_edit_word(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        edited = personal_vocab_repo.edit_word(1, "custom", meaning="订制", band=8)
        assert edited.meaning == "订制"
        assert edited.band == 8

    def test_edit_nonexistent_raises(self, personal_vocab_repo):
        with pytest.raises(ValueError, match="不在"):
            personal_vocab_repo.edit_word(1, "missing", meaning="x")

    def test_delete_word(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        assert personal_vocab_repo.delete_word(1, "custom") is True
        assert personal_vocab_repo.delete_word(1, "custom") is False

    def test_list_words(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        words, total = personal_vocab_repo.list_words(1, page=1, per_page=10)
        assert total == 1
        assert len(words) == 1

    def test_get_word_count(self, personal_vocab_repo, sample_personal_word):
        assert personal_vocab_repo.get_word_count(1) == 0
        personal_vocab_repo.add_word(1, sample_personal_word)
        assert personal_vocab_repo.get_word_count(1) == 1

    def test_create_and_list_categories(self, personal_vocab_repo):
        cats = personal_vocab_repo.list_categories(1)
        names = [c.name for c in cats]
        # 系统分类应自动存在
        assert "favorites" in names
        assert "mistakes" in names

        new_cat = personal_vocab_repo.create_category(1, "my_topic", "我的主题")
        assert new_cat.name == "my_topic"
        assert new_cat.is_system is False

        cats = personal_vocab_repo.list_categories(1)
        names = [c.name for c in cats]
        assert "my_topic" in names

    def test_create_duplicate_category_raises(self, personal_vocab_repo):
        personal_vocab_repo.create_category(1, "dup_cat")
        with pytest.raises(ValueError, match="已存在"):
            personal_vocab_repo.create_category(1, "dup_cat")

    def test_delete_system_category_raises(self, personal_vocab_repo):
        with pytest.raises(ValueError, match="系统分类.*不可删除"):
            personal_vocab_repo.delete_category(1, "favorites")

    def test_delete_user_category(self, personal_vocab_repo):
        personal_vocab_repo.create_category(1, "to_delete")
        assert personal_vocab_repo.delete_category(1, "to_delete") is True
        # 再次删应报错
        with pytest.raises(ValueError, match="不存在"):
            personal_vocab_repo.delete_category(1, "to_delete")

    def test_add_to_category(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        personal_vocab_repo.create_category(1, "test_cat")
        assert personal_vocab_repo.add_to_category(1, "custom", "test_cat") is True
        # 重复 add 返回 False
        assert personal_vocab_repo.add_to_category(1, "custom", "test_cat") is False

    def test_add_to_category_missing_word_raises(self, personal_vocab_repo):
        personal_vocab_repo.create_category(1, "any_cat")
        with pytest.raises(ValueError, match="不在"):
            personal_vocab_repo.add_to_category(1, "missing", "any_cat")

    def test_add_to_category_missing_category_raises(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        with pytest.raises(ValueError, match="不存在"):
            personal_vocab_repo.add_to_category(1, "custom", "nonexistent_cat")

    def test_remove_from_category(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        personal_vocab_repo.create_category(1, "rem_cat")
        personal_vocab_repo.add_to_category(1, "custom", "rem_cat")
        assert personal_vocab_repo.remove_from_category(1, "custom", "rem_cat") is True
        assert personal_vocab_repo.remove_from_category(1, "custom", "rem_cat") is False

    def test_get_word_categories(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        cats = personal_vocab_repo.get_word_categories(1, "custom")
        assert len(cats) == 0

        personal_vocab_repo.create_category(1, "cat_x")
        personal_vocab_repo.add_to_category(1, "custom", "cat_x")
        cats = personal_vocab_repo.get_word_categories(1, "custom")
        assert len(cats) == 1
        assert cats[0].name == "cat_x"

    def test_add_mistake(self, personal_vocab_repo):
        word = Word(word="forget", meaning="忘记", band=5, pos="v.")
        personal_vocab_repo.add_mistake(1, word, source="quiz_mistake")
        # 单词应已加入
        got = personal_vocab_repo.get_word(1, "forget")
        assert got is not None
        # 应自动加入 mistakes 分类
        cats = personal_vocab_repo.get_word_categories(1, "forget")
        assert any(c.name == "mistakes" for c in cats)

    def test_add_from_grading(self, personal_vocab_repo):
        result = personal_vocab_repo.add_from_grading(
            1, "vocab_word", context="context", suggestion="suggest", comment="note"
        )
        assert result.word == "vocab_word"
        assert result.source == "grading"

    def test_get_source_distribution(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        dist = personal_vocab_repo.get_source_distribution(1)
        assert "manual" in dist

    def test_get_band_distribution(self, personal_vocab_repo, sample_personal_word):
        personal_vocab_repo.add_word(1, sample_personal_word)
        dist = personal_vocab_repo.get_band_distribution(1)
        assert 7 in dist


# =============================================================
# 3. ExamRepository
# =============================================================


class TestExamRepository:
    def test_create_exam_returns_session(self, exam_repo):
        session = exam_repo.create_exam(1, band=6, count=10, time_limit=20)
        assert session.id is not None
        assert session.user_id == 1
        assert session.band_filter == 6
        assert session.time_limit == 20

    def test_submit_and_finish_exam(self, exam_repo):
        # 手工插入一个 session（因为 create_exam 不写库）
        from ielts_buddy.core.models import ExamSession

        session = ExamSession(
            id="test_session_1",
            user_id=1,
            questions=[
                ExamQuestion(index=0, word="hello", mode="en2zh", prompt="hello", answer="你好", band=5),
                ExamQuestion(index=1, word="world", mode="zh2en", prompt="世界", answer="world", band=5),
            ],
            time_limit=20,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )
        # 直接 INSERT
        exam_repo._conn.execute(  # type: ignore[attr-defined]
            """INSERT INTO exam_sessions
               (id, user_id, questions, time_limit, started_at, band_filter)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session.id, session.user_id,
                json.dumps([q.model_dump() for q in session.questions], ensure_ascii=False),
                session.time_limit, session.started_at, session.band_filter,
            ),
        )
        exam_repo._conn.commit()  # type: ignore[attr-defined]

        # 提交答案
        r1 = exam_repo.submit_answer(1, "test_session_1", 0, "你好")
        assert r1["correct"] is True
        r2 = exam_repo.submit_answer(1, "test_session_1", 1, "world")
        assert r2["correct"] is True

        # 结束考试
        report = exam_repo.finish_exam(1, "test_session_1")
        assert report.score == 2
        assert report.total == 2
        assert report.accuracy == 1.0

    def test_submit_answer_wrong(self, exam_repo):
        from ielts_buddy.core.models import ExamSession

        session = ExamSession(
            id="test_session_2",
            user_id=1,
            questions=[
                ExamQuestion(index=0, word="hello", mode="zh2en", prompt="你好", answer="hello", band=5),
            ],
            time_limit=20,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )
        exam_repo._conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO exam_sessions (id, user_id, questions, time_limit, started_at) VALUES (?, ?, ?, ?, ?)",
            (session.id, 1, json.dumps([q.model_dump() for q in session.questions], ensure_ascii=False), 20, session.started_at),
        )
        exam_repo._conn.commit()  # type: ignore[attr-defined]

        r = exam_repo.submit_answer(1, "test_session_2", 0, "world")
        assert r["correct"] is False

    def test_submit_answer_missing_session_raises(self, exam_repo):
        with pytest.raises(ValueError, match="不存在"):
            exam_repo.submit_answer(1, "nonexistent", 0, "answer")

    def test_submit_answer_out_of_range_raises(self, exam_repo):
        from ielts_buddy.core.models import ExamSession

        session = ExamSession(
            id="test_session_3",
            user_id=1,
            questions=[
                ExamQuestion(index=0, word="a", mode="zh2en", prompt="一", answer="a", band=5),
            ],
            time_limit=20,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )
        exam_repo._conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO exam_sessions (id, user_id, questions, time_limit, started_at) VALUES (?, ?, ?, ?, ?)",
            (session.id, 1, json.dumps([q.model_dump() for q in session.questions], ensure_ascii=False), 20, session.started_at),
        )
        exam_repo._conn.commit()  # type: ignore[attr-defined]

        with pytest.raises(IndexError):
            exam_repo.submit_answer(1, "test_session_3", 5, "x")

    def test_get_exam_history(self, exam_repo):
        from ielts_buddy.core.models import ExamSession

        session = ExamSession(
            id="test_session_4",
            user_id=1,
            questions=[
                ExamQuestion(index=0, word="a", mode="en2zh", prompt="a", answer="一", band=5),
            ],
            time_limit=20,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )
        exam_repo._conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO exam_sessions (id, user_id, questions, time_limit, started_at) VALUES (?, ?, ?, ?, ?)",
            (session.id, 1, json.dumps([q.model_dump() for q in session.questions], ensure_ascii=False), 20, session.started_at),
        )
        exam_repo._conn.commit()  # type: ignore[attr-defined]
        exam_repo.submit_answer(1, "test_session_4", 0, "一")
        exam_repo.finish_exam(1, "test_session_4")

        hist = exam_repo.get_exam_history(1, limit=10)
        assert len(hist) == 1
        assert hist[0]["session_id"] == "test_session_4"

    def test_get_exam_session(self, exam_repo):
        from ielts_buddy.core.models import ExamSession

        session = ExamSession(
            id="test_session_5",
            user_id=1,
            questions=[
                ExamQuestion(index=0, word="a", mode="en2zh", prompt="a", answer="一", band=5),
            ],
            time_limit=20,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )
        exam_repo._conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO exam_sessions (id, user_id, questions, time_limit, started_at) VALUES (?, ?, ?, ?, ?)",
            (session.id, 1, json.dumps([q.model_dump() for q in session.questions], ensure_ascii=False), 20, session.started_at),
        )
        exam_repo._conn.commit()  # type: ignore[attr-defined]

        got = exam_repo.get_exam_session(1, "test_session_5")
        assert got is not None
        assert got.id == "test_session_5"
        assert len(got.questions) == 1

    def test_get_exam_session_missing(self, exam_repo):
        assert exam_repo.get_exam_session(1, "missing") is None

    def test_user_isolation(self, exam_repo):
        from ielts_buddy.core.models import ExamSession

        session = ExamSession(
            id="test_user_iso",
            user_id=1,
            questions=[],
            time_limit=20,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )
        exam_repo._conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO exam_sessions (id, user_id, questions, time_limit, started_at) VALUES (?, ?, ?, ?, ?)",
            (session.id, 1, "[]", 20, session.started_at),
        )
        exam_repo._conn.commit()  # type: ignore[attr-defined]

        assert exam_repo.get_exam_session(1, "test_user_iso") is not None
        assert exam_repo.get_exam_session(2, "test_user_iso") is None


# =============================================================
# 4. GradeRepository
# =============================================================


class TestGradeRepository:
    def test_save_and_get_history(self, grade_repo, sample_grade_result):
        rid = grade_repo.save_result(1, sample_grade_result)
        assert rid > 0
        hist = grade_repo.get_history(1, limit=10)
        assert len(hist) == 1
        assert hist[0].overall_score == 6.5

    def test_get_history_task_type_filter(self, grade_repo, sample_grade_result):
        grade_repo.save_result(1, sample_grade_result)
        result = grade_repo.get_history(1, limit=10, task_type="task2")
        assert len(result) == 1
        empty = grade_repo.get_history(1, limit=10, task_type="task1_academic")
        assert len(empty) == 0

    def test_get_average_score(self, grade_repo, sample_grade_result):
        assert grade_repo.get_average_score(1) == 0.0
        grade_repo.save_result(1, sample_grade_result)
        avg = grade_repo.get_average_score(1)
        assert 6.0 <= avg <= 7.0

    def test_get_error_trend(self, grade_repo, sample_grade_result):
        grade_repo.save_result(1, sample_grade_result)
        trend = grade_repo.get_error_trend(1, limit=5)
        assert len(trend) == 1
        assert "grammar" in trend[0]["error_summary"]


# =============================================================
# 5. VocabCacheRepository
# =============================================================


class TestVocabCacheRepository:
    def test_put_and_get_cached(self, cache_repo):
        cache_repo.put_cached(
            "test_word", 5, "topic_x",
            {"phonetic": "/t/", "meaning": "测试", "pos": "n.", "example": "ex"},
        )
        got = cache_repo.get_cached("test_word")
        assert got is not None
        assert got["meaning"] == "测试"

    def test_get_cached_missing(self, cache_repo):
        assert cache_repo.get_cached("nonexistent") is None

    def test_mtime_set_and_get(self, cache_repo):
        assert cache_repo.get_mtime("any_key") == ""
        cache_repo.set_mtime("any_key", "12345")
        assert cache_repo.get_mtime("any_key") == "12345"

    def test_clear_cache(self, cache_repo):
        cache_repo.put_cached("w1", 5, "t", {"meaning": "一"})
        cache_repo.put_cached("w2", 6, "t", {"meaning": "二"})
        cache_repo.clear_cache()
        assert cache_repo.get_cached("w1") is None
        assert cache_repo.get_cached("w2") is None

    def test_shared_across_users(self, cache_repo):
        """vocab_cache 与 user_id 无关（共享）"""
        cache_repo.put_cached("shared_word", 7, "t", {"meaning": "shared"})
        # user 1 和 user 2 都能看到
        assert cache_repo.get_cached("shared_word") is not None


# =============================================================
# 6. UserRepository (单机模式 no-op)
# =============================================================


class TestUserRepository:
    def test_get_or_create_returns_one(self, user_repo):
        assert user_repo.get_or_create("anyone") == 1
        assert user_repo.get_or_create("another_user") == 1

    def test_get_by_id_local(self, user_repo):
        u = user_repo.get_by_id(1)
        assert u is not None
        assert u["username"] == "local"

    def test_get_by_id_missing(self, user_repo):
        assert user_repo.get_by_id(99) is None

    def test_list_users(self, user_repo):
        users = user_repo.list_users()
        assert len(users) == 1
        assert users[0]["id"] == 1

    def test_update_last_login_noop(self, user_repo):
        # 不应抛错
        user_repo.update_last_login(1)
        user_repo.update_last_login(99)

    def test_ensure_system_categories_noop(self, user_repo):
        # 不应抛错
        user_repo.ensure_system_categories(1)


# =============================================================
# 7. Container integration
# =============================================================


class TestRepositoryContainer:
    def test_all_repos_attached(self, container):
        assert container.learning is not None
        assert container.personal_vocab is not None
        assert container.exam is not None
        assert container.grade is not None
        assert container.vocab_cache is not None
        assert container.user is not None

    def test_close_does_not_raise(self, container):
        container.close()  # 不抛错
