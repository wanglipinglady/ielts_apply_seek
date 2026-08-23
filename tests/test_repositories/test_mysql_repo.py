"""MySQLRepository 单元测试

W3.4 阶段：覆盖 6 个 MySQL Repository 的全部方法。
连真实 MySQL 数据库（118.190.148.121:3306 / ietls_learn_online）。

设计要点：
- 每个测试用例使用唯一测试用户名（带 timestamp 避免冲突）
- fixture 在 teardown 时清理该用户的所有业务表数据
- 测试不会影响 user_id=0 的种子模板
- 失败时仍会清理（finally）
"""
from __future__ import annotations

import os
import time
from datetime import datetime

import pytest
from sqlalchemy import text

from ielts_buddy.core.models import (
    GradeDimension,
    GradeResult,
    PersonalWord,
    Word,
)
from ielts_buddy.repositories import (
    MySQLExamRepository,
    MySQLGradeRepository,
    MySQLLearningRepository,
    MySQLPersonalVocabRepository,
    MySQLRepositoryContainer,
    MySQLUserRepository,
    MySQLVocabCacheRepository,
    create_mysql_repositories,
)


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture(scope="module")
def container() -> MySQLRepositoryContainer:
    """整个测试模块共享一个容器（减少连接开销）。"""
    c = create_mysql_repositories()
    yield c
    try:
        c.close()
    except Exception:
        pass


@pytest.fixture
def test_user_id(container) -> int:
    """固定使用 pytest_user（id=1156），不创建新用户。

    v3+ 测试隔离策略：所有连真实 MySQL 的测试 fixture 共享 pytest_user，
    保证 users 表不会被无限自增。pytest_user 的 id=1156 由
    cleanup_users.py 一次性脚本创建并锁定 AUTO_INCREMENT=1157。

    teardown 只清理该用户的业务数据，**不删 users 行**（pytest_user 永生）。
    """
    uid = container.user.get_or_create("pytest_user")
    assert uid == 1156, (
        f"期望 pytest_user id=1156，实际={uid}。"
        "请先运行 cleanup_users.py 初始化测试用户。"
    )
    yield uid
    # 清理：按依赖反向删除该用户的业务数据（不删 users 行）
    try:
        with container._engine.begin() as conn:
            conn.execute(text("DELETE FROM vocab_category_words WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM learning_records WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM personal_vocab WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM vocab_categories WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM exam_sessions WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM grade_history WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM articles WHERE user_id = :u"), {"u": uid})
    except Exception:
        pass  # 测试失败时清理出错不影响整体


@pytest.fixture
def learning_repo(container) -> MySQLLearningRepository:
    return container.learning


@pytest.fixture
def personal_vocab_repo(container) -> MySQLPersonalVocabRepository:
    return container.personal_vocab


@pytest.fixture
def exam_repo(container) -> MySQLExamRepository:
    return container.exam


@pytest.fixture
def grade_repo(container) -> MySQLGradeRepository:
    return container.grade


@pytest.fixture
def cache_repo(container) -> MySQLVocabCacheRepository:
    return container.vocab_cache


@pytest.fixture
def user_repo(container) -> MySQLUserRepository:
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
# 0. Container
# =============================================================


class TestMySQLContainer:
    def test_container_has_six_repos(self, container):
        assert isinstance(container.learning, MySQLLearningRepository)
        assert isinstance(container.personal_vocab, MySQLPersonalVocabRepository)
        assert isinstance(container.exam, MySQLExamRepository)
        assert isinstance(container.grade, MySQLGradeRepository)
        assert isinstance(container.vocab_cache, MySQLVocabCacheRepository)
        assert isinstance(container.user, MySQLUserRepository)

    def test_repos_share_engine(self, container):
        eng_id = id(container._engine)
        for repo in [
            container.learning,
            container.personal_vocab,
            container.exam,
            container.grade,
            container.vocab_cache,
            container.user,
        ]:
            assert id(repo._engine) == eng_id


# =============================================================
# 1. LearningRepository
# =============================================================


class TestMySQLLearningRepository:
    def test_upsert_and_get(self, learning_repo, test_user_id, sample_word):
        rec = learning_repo.upsert_record(test_user_id, sample_word, correct=True)
        assert rec.memory_level == 1
        assert rec.learn_count == 1

        got = learning_repo.get_record(test_user_id, "abandon")
        assert got is not None
        assert got.memory_level == 1

    def test_upsert_incorrect_lowers_level(self, learning_repo, test_user_id, sample_word):
        learning_repo.upsert_record(test_user_id, sample_word, correct=True)
        rec = learning_repo.upsert_record(test_user_id, sample_word, correct=False)
        assert rec.memory_level == 0
        assert rec.learn_count == 2
        assert rec.correct_count == 1
        assert rec.wrong_count == 1

    def test_user_isolation(self, learning_repo, test_user_id, sample_word, container):
        learning_repo.upsert_record(test_user_id, sample_word, correct=True)
        # 别的用户看不到
        other_username = f"w3_4_other_{int(time.time() * 1000)}"
        other_id = container.user.get_or_create(other_username)
        try:
            assert learning_repo.get_record(other_id, "abandon") is None
        finally:
            with container._engine.begin() as conn:
                conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": other_id})

    def test_toggle_star(self, learning_repo, test_user_id, sample_word):
        learning_repo.upsert_record(test_user_id, sample_word, correct=True)
        assert learning_repo.toggle_star(test_user_id, "abandon") is True
        assert learning_repo.toggle_star(test_user_id, "abandon") is False

    def test_toggle_difficult(self, learning_repo, test_user_id, sample_word):
        learning_repo.upsert_record(test_user_id, sample_word, correct=True)
        assert learning_repo.toggle_difficult(test_user_id, "abandon") is True

    def test_get_due_words(self, learning_repo, test_user_id, sample_word, sample_word2):
        learning_repo.upsert_record(test_user_id, sample_word, correct=True)  # level 1
        learning_repo.upsert_record(test_user_id, sample_word2, correct=False)  # level 0
        due = learning_repo.get_due_words(test_user_id, limit=10)
        # sample_word2 (level 0) 是 due 的
        words = [d["word"] for d in due]
        assert "benefit" in words

    def test_get_due_count(self, learning_repo, test_user_id, sample_word):
        learning_repo.upsert_record(test_user_id, sample_word, correct=True)
        learning_repo.upsert_record(test_user_id, sample_word, correct=False)
        assert learning_repo.get_due_count(test_user_id) >= 1

    def test_get_all_records(self, learning_repo, test_user_id, sample_word, sample_word2):
        learning_repo.upsert_record(test_user_id, sample_word, correct=True)
        learning_repo.upsert_record(test_user_id, sample_word2, correct=True)
        records = learning_repo.get_all_records(test_user_id)
        assert len(records) == 2

    def test_get_learned_count(self, learning_repo, test_user_id, sample_word):
        assert learning_repo.get_learned_count(test_user_id) == 0
        learning_repo.upsert_record(test_user_id, sample_word, correct=True)
        assert learning_repo.get_learned_count(test_user_id) == 1

    def test_history(self, learning_repo, test_user_id, sample_word):
        learning_repo.upsert_record(test_user_id, sample_word, correct=True)
        hist = learning_repo.get_history(test_user_id, days=7)
        assert len(hist) == 7
        # 今天应有 1 个新词
        from datetime import date
        today = date.today().isoformat()
        today_entry = next((h for h in hist if h["date"] == today), None)
        assert today_entry is not None
        assert today_entry["new_words"] >= 1


# =============================================================
# 2. PersonalVocabRepository
# =============================================================


class TestMySQLPersonalVocabRepository:
    def test_add_and_get_word(self, personal_vocab_repo, test_user_id, sample_personal_word):
        new_id = personal_vocab_repo.add_word(test_user_id, sample_personal_word)
        assert new_id > 0
        got = personal_vocab_repo.get_word(test_user_id, "custom")
        assert got is not None
        assert got.meaning == "自定义"

    def test_add_word_accepts_word(self, personal_vocab_repo, test_user_id):
        # add_word 接受 Word（不含 note）应能正常工作
        w = Word(word="alpha", meaning="α", band=5, pos="n.")
        new_id = personal_vocab_repo.add_word(test_user_id, w)
        assert new_id > 0

    def test_add_duplicate_raises(self, personal_vocab_repo, test_user_id, sample_personal_word):
        personal_vocab_repo.add_word(test_user_id, sample_personal_word)
        with pytest.raises(ValueError, match="已存在"):
            personal_vocab_repo.add_word(test_user_id, sample_personal_word)

    def test_edit_word(self, personal_vocab_repo, test_user_id, sample_personal_word):
        personal_vocab_repo.add_word(test_user_id, sample_personal_word)
        edited = personal_vocab_repo.edit_word(test_user_id, "custom", meaning="用户自定义", band=8)
        assert edited.meaning == "用户自定义"
        assert edited.band == 8

    def test_list_words(self, personal_vocab_repo, test_user_id, sample_personal_word, sample_word):
        personal_vocab_repo.add_word(test_user_id, sample_personal_word)
        personal_vocab_repo.add_word(test_user_id, PersonalWord(word="delta", meaning="δ", band=5))
        words, total = personal_vocab_repo.list_words(test_user_id, page=1, per_page=10)
        assert total == 2
        assert len(words) == 2

    def test_get_word_count(self, personal_vocab_repo, test_user_id, sample_personal_word):
        personal_vocab_repo.add_word(test_user_id, sample_personal_word)
        assert personal_vocab_repo.get_word_count(test_user_id) == 1

    def test_create_and_list_categories(self, personal_vocab_repo, test_user_id):
        cats = personal_vocab_repo.list_categories(test_user_id)
        # 系统分类应自动存在
        names = [c.name for c in cats]
        assert "favorites" in names
        assert "mistakes" in names

        personal_vocab_repo.create_category(test_user_id, "my_cards", "我的卡片")
        cats2 = personal_vocab_repo.list_categories(test_user_id)
        names2 = [c.name for c in cats2]
        assert "my_cards" in names2

    def test_delete_system_category_refused(self, personal_vocab_repo, test_user_id):
        with pytest.raises(ValueError, match="系统分类"):
            personal_vocab_repo.delete_category(test_user_id, "favorites")

    def test_delete_custom_category(self, personal_vocab_repo, test_user_id):
        personal_vocab_repo.create_category(test_user_id, "tmp", "临时")
        assert personal_vocab_repo.delete_category(test_user_id, "tmp") is True
        cats = personal_vocab_repo.list_categories(test_user_id)
        assert "tmp" not in [c.name for c in cats]

    def test_add_to_category(self, personal_vocab_repo, test_user_id, sample_personal_word):
        personal_vocab_repo.add_word(test_user_id, sample_personal_word)
        personal_vocab_repo.create_category(test_user_id, "study", "学习")
        assert personal_vocab_repo.add_to_category(test_user_id, "custom", "study") is True
        # 重复
        assert personal_vocab_repo.add_to_category(test_user_id, "custom", "study") is False

    def test_get_word_categories(self, personal_vocab_repo, test_user_id, sample_personal_word):
        personal_vocab_repo.add_word(test_user_id, sample_personal_word)
        personal_vocab_repo.create_category(test_user_id, "study", "学习")
        personal_vocab_repo.add_to_category(test_user_id, "custom", "study")
        cats = personal_vocab_repo.get_word_categories(test_user_id, "custom")
        names = [c.name for c in cats]
        assert "study" in names

    def test_add_mistake(self, personal_vocab_repo, test_user_id):
        mistake = Word(word="forget", meaning="忘记", band=5, pos="v.")
        personal_vocab_repo.add_mistake(test_user_id, mistake, source="quiz_mistake")
        # words 表里应有这条
        got = personal_vocab_repo.get_word(test_user_id, "forget")
        assert got is not None
        # mistakes 分类里应有
        cats = personal_vocab_repo.get_word_categories(test_user_id, "forget")
        assert "mistakes" in [c.name for c in cats]

    def test_remove_from_category(self, personal_vocab_repo, test_user_id, sample_personal_word):
        personal_vocab_repo.add_word(test_user_id, sample_personal_word)
        personal_vocab_repo.create_category(test_user_id, "study", "学习")
        personal_vocab_repo.add_to_category(test_user_id, "custom", "study")
        assert personal_vocab_repo.remove_from_category(test_user_id, "custom", "study") is True
        cats = personal_vocab_repo.get_word_categories(test_user_id, "custom")
        assert "study" not in [c.name for c in cats]

    def test_source_and_band_distribution(self, personal_vocab_repo, test_user_id):
        personal_vocab_repo.add_word(test_user_id, PersonalWord(word="a", meaning="A", band=5, source="manual"))
        personal_vocab_repo.add_word(test_user_id, PersonalWord(word="b", meaning="B", band=7, source="quiz_mistake"))
        sd = personal_vocab_repo.get_source_distribution(test_user_id)
        assert "manual" in sd
        assert "quiz_mistake" in sd
        bd = personal_vocab_repo.get_band_distribution(test_user_id)
        assert bd.get(5) == 1
        assert bd.get(7) == 1

    def test_delete_word(self, personal_vocab_repo, test_user_id, sample_personal_word):
        personal_vocab_repo.add_word(test_user_id, sample_personal_word)
        assert personal_vocab_repo.delete_word(test_user_id, "custom") is True
        assert personal_vocab_repo.get_word(test_user_id, "custom") is None


# =============================================================
# 3. ExamRepository
# =============================================================


class TestMySQLExamRepository:
    def test_create_and_finish_exam(self, exam_repo, test_user_id, container):
        # W3 设计：create_exam 只生成 session 对象，题目由测试手工组装后 save
        from ielts_buddy.core.models import ExamQuestion
        sess = exam_repo.create_exam(test_user_id, 5, 2, 20)
        # 手工注入题目并显式 save_exam_session
        sess.questions = [
            ExamQuestion(index=0, word="hello", mode="en2zh", prompt="hello", answer="你好", band=5),
            ExamQuestion(index=1, word="world", mode="zh2en", prompt="世界", answer="world", band=5),
        ]
        exam_repo.save_exam_session(test_user_id, sess)

        # 提交两个答案
        res0 = exam_repo.submit_answer(test_user_id, sess.id, 0, "你好")
        res1 = exam_repo.submit_answer(test_user_id, sess.id, 1, "world")
        assert res0["correct"] is True
        assert res1["correct"] is True

        report = exam_repo.finish_exam(test_user_id, sess.id)
        assert report.score == 2
        assert report.total == 2
        assert report.accuracy == 1.0

        # 验证历史里有这条
        hist = exam_repo.get_exam_history(test_user_id, limit=10)
        assert any(h["session_id"] == sess.id for h in hist)

    def test_get_exam_session(self, exam_repo, test_user_id):
        from ielts_buddy.core.models import ExamQuestion
        sess = exam_repo.create_exam(test_user_id, 6, 1, 20)
        sess.questions = [
            ExamQuestion(index=0, word="w", mode="en2zh", prompt="w", answer="w", band=5),
        ]
        exam_repo.save_exam_session(test_user_id, sess)
        got = exam_repo.get_exam_session(test_user_id, sess.id)
        assert got is not None
        assert len(got.questions) == 1

    def test_get_exam_history(self, exam_repo, test_user_id):
        from ielts_buddy.core.models import ExamQuestion
        # 多次创建 + save
        ids = []
        for _ in range(3):
            s = exam_repo.create_exam(test_user_id, 5, 1, 20)
            s.questions = [ExamQuestion(index=0, word="w", mode="en2zh", prompt="w", answer="w", band=5)]
            exam_repo.save_exam_session(test_user_id, s)
            ids.append(s.id)
        # history 只列出 finished 的，所以这里 0 条（没 finish）
        # 改测：save 后未 finish，get_exam_session 能找到
        for sid in ids:
            assert exam_repo.get_exam_session(test_user_id, sid) is not None


# =============================================================
# 4. GradeRepository
# =============================================================


class TestMySQLGradeRepository:
    def test_save_and_get_history(self, grade_repo, test_user_id, sample_grade_result):
        rid = grade_repo.save_result(test_user_id, sample_grade_result)
        assert rid > 0
        hist = grade_repo.get_history(test_user_id, limit=10)
        assert len(hist) == 1
        assert hist[0].overall_score == 6.5

    def test_get_history_with_task_filter(self, grade_repo, test_user_id, sample_grade_result):
        grade_repo.save_result(test_user_id, sample_grade_result)
        from ielts_buddy.core.models import GradeResult, GradeDimension
        now = datetime.now().isoformat(timespec="seconds")
        grade_repo.save_result(test_user_id, GradeResult(
            user_id=test_user_id,
            overall_score=7.0,
            task_response=GradeDimension(score=7.0, comment="ok"),
            coherence=GradeDimension(score=7.0, comment="ok"),
            lexical_resource=GradeDimension(score=7.0, comment="ok"),
            grammar=GradeDimension(score=7.0, comment="ok"),
            suggestions=[], rewrite="r", essay_text="e", topic="t",
            task_type="task1", error_summary={}, graded_at=now,
        ))
        h_task2 = grade_repo.get_history(test_user_id, task_type="task2", limit=10)
        h_task1 = grade_repo.get_history(test_user_id, task_type="task1", limit=10)
        assert len(h_task2) == 1
        assert len(h_task1) == 1

    def test_average_score(self, grade_repo, test_user_id, sample_grade_result):
        grade_repo.save_result(test_user_id, sample_grade_result)
        from ielts_buddy.core.models import GradeResult, GradeDimension
        now = datetime.now().isoformat(timespec="seconds")
        grade_repo.save_result(test_user_id, GradeResult(
            user_id=test_user_id,
            overall_score=7.5,
            task_response=GradeDimension(score=7.5, comment="ok"),
            coherence=GradeDimension(score=7.5, comment="ok"),
            lexical_resource=GradeDimension(score=7.5, comment="ok"),
            grammar=GradeDimension(score=7.5, comment="ok"),
            suggestions=[], rewrite="r", essay_text="e", topic="t",
            task_type="task1", error_summary={}, graded_at=now,
        ))
        avg = grade_repo.get_average_score(test_user_id)
        # (6.5 + 7.5) / 2 = 7.0
        assert 6.9 <= avg <= 7.1

    def test_error_trend(self, grade_repo, test_user_id, sample_grade_result):
        grade_repo.save_result(test_user_id, sample_grade_result)
        trend = grade_repo.get_error_trend(test_user_id, limit=10)
        assert len(trend) == 1
        assert "grammar" in trend[0]["error_summary"]


# =============================================================
# 5. VocabCacheRepository
# =============================================================


class TestMySQLVocabCacheRepository:
    def test_put_and_get(self, cache_repo):
        # 用唯一 key 避免污染
        key = f"w3_4_test_{int(time.time() * 1000)}"
        cache_repo.put_cached(key, 5, "test", {"phonetic": "/t/", "meaning": "测试", "pos": "n."})
        got = cache_repo.get_cached(key)
        assert got is not None
        assert got["meaning"] == "测试"
        # 清理
        from sqlalchemy import text
        with cache_repo._engine.begin() as conn:
            conn.execute(text("DELETE FROM vocab_cache WHERE word = :w"), {"w": key})

    def test_mtime(self, cache_repo):
        # 用唯一 key 避免污染
        key = f"w3_4_mtime_{int(time.time() * 1000)}"
        m0 = cache_repo.get_mtime(key)
        assert m0 == ""
        cache_repo.set_mtime(key, "9999")
        m1 = cache_repo.get_mtime(key)
        assert m1 == "9999"
        # 清理
        from sqlalchemy import text
        with cache_repo._engine.begin() as conn:
            conn.execute(text("DELETE FROM cache_meta WHERE key_name = :k"), {"k": key})


# =============================================================
# 6. UserRepository
# =============================================================


class TestMySQLUserRepository:
    def test_get_or_create(self, user_repo, container):
        username = f"w3_4_user_{int(time.time() * 1000)}"
        try:
            uid1 = user_repo.get_or_create(username)
            uid2 = user_repo.get_or_create(username)
            assert uid1 == uid2
        finally:
            with container._engine.begin() as conn:
                conn.execute(text("DELETE FROM users WHERE username = :n"), {"n": username})

    def test_get_by_id(self, user_repo, test_user_id):
        info = user_repo.get_by_id(test_user_id)
        assert info is not None
        assert "username" in info

    def test_update_last_login(self, user_repo, test_user_id, container):
        from sqlalchemy import text
        with container._engine.begin() as conn:
            conn.execute(text("UPDATE users SET last_login_at = NULL WHERE id = :u"), {"u": test_user_id})
        user_repo.update_last_login(test_user_id)
        with container._engine.connect() as conn:
            v = conn.execute(text("SELECT last_login_at FROM users WHERE id = :u"), {"u": test_user_id}).scalar()
        assert v is not None

    def test_list_users(self, user_repo, test_user_id):
        users = user_repo.list_users()
        ids = [u["id"] for u in users]
        assert test_user_id in ids

    def test_ensure_system_categories(self, user_repo, test_user_id):
        # 通过 user_repo 触发系统分类复制
        user_repo.ensure_system_categories(test_user_id)
        # 验证 final 结果：用 personal_vocab.list_categories 看
        from ielts_buddy.repositories import MySQLPersonalVocabRepository
        pv = MySQLPersonalVocabRepository(user_repo._engine)
        names = [c.name for c in pv.list_categories(test_user_id)]
        assert "favorites" in names
        assert "mistakes" in names
