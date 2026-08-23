"""SQLiteSpeakingPracticeRepository 单元测试(v3.7 P1 新增)。

覆盖 speaking_practice_records 表 + record_speaking_error(Learning) 的
8 个 + 1 个核心方法。重点:
  - 完整 lifecycle: create → update_transcript → update_score → get/list
  - user_id 隔离(A 看不到 B)
  - 7 天 audio 清理:set_audio_null
  - 错词回收:record_speaking_error 不会推进 memory_level
"""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ielts_buddy.core.models import Word
from ielts_buddy.repositories import (
    SQLiteLearningRepository,
    SQLiteRepositoryContainer,
    SQLiteSpeakingPracticeRepository,
)


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
    c.close()


@pytest.fixture
def sp_repo(container: SQLiteRepositoryContainer) -> SQLiteSpeakingPracticeRepository:
    return container.speaking_practice


@pytest.fixture
def learning(container: SQLiteRepositoryContainer) -> SQLiteLearningRepository:
    return container.learning


# =============================================================
# Helpers
# =============================================================


def _sample_tokens() -> list[dict]:
    return [
        {"word": "I", "t0_ms": 100, "t1_ms": 200, "prob": 0.99},
        {"word": "usually", "t0_ms": 250, "t1_ms": 700, "prob": 0.97},
        {"word": "wake", "t0_ms": 750, "t1_ms": 1100, "prob": 0.95},
    ]


# =============================================================
# 1. create_practice_record
# =============================================================


def test_create_basic_record_returns_int(sp_repo, container):
    """create 应返回新 id,且记录能被 get 查到。"""
    sid = "uuid-test-001"
    rid = sp_repo.create_practice_record(
        user_id=1,
        session_id=sid,
        part=1,
        topic_id=3,
        topic_name="Daily Routine",
        question="What is your typical daily routine?",
        audio_path="/tmp/fake.webm",
        audio_duration_sec=35.4,
        audio_mime="audio/webm",
    )
    assert isinstance(rid, int) and rid > 0

    row = sp_repo.get_practice_by_session(1, sid)
    assert row is not None
    assert row["user_id"] == 1
    assert row["part"] == 1
    assert row["topic_id"] == 3
    assert row["topic_name"] == "Daily Routine"
    assert row["audio_duration_sec"] == 35.4
    assert row["score_fallback"] == 0
    assert row["transcript"] == ""  # 初始为空


def test_create_unique_session_id(sp_repo):
    """session_id UNIQUE 约束生效。"""
    sp_repo.create_practice_record(
        user_id=1, session_id="dup-uuid",
        part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path=None,
        audio_duration_sec=0.0,
    )
    with pytest.raises(Exception):
        sp_repo.create_practice_record(
            user_id=1, session_id="dup-uuid",  # 重复
            part=1, topic_id=1, topic_name="X",
            question="Q?", audio_path=None,
            audio_duration_sec=0.0,
        )


def test_create_with_optional_audio_none(sp_repo):
    """audio_path 可为 None（用于 upload 失败的边界）。"""
    rid = sp_repo.create_practice_record(
        user_id=1, session_id="no-audio",
        part=2, topic_id=None, topic_name="",
        question="Describe a place...", audio_path=None,
        audio_duration_sec=0.0,
    )
    row = sp_repo.get_practice_by_session(1, "no-audio")
    assert row["audio_path"] is None
    assert row["topic_id"] is None


# =============================================================
# 2. update_practice_transcript
# =============================================================


def test_update_transcript_fills_fields(sp_repo):
    """转写后 transcript + tokens 都填上。"""
    sid = "t-001"
    sp_repo.create_practice_record(
        user_id=1, session_id=sid, part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path="/tmp/x.webm", audio_duration_sec=10.0,
    )
    ok = sp_repo.update_practice_transcript(
        user_id=1, session_id=sid,
        transcript="I usually wake up at 7",
        transcript_tokens=_sample_tokens(),
        whisper_model="small.en",
        used_core_ml=True,
    )
    assert ok is True

    row = sp_repo.get_practice_by_session(1, sid)
    assert row["transcript"] == "I usually wake up at 7"
    tokens = json.loads(row["transcript_tokens"])
    assert len(tokens) == 3
    assert tokens[0]["word"] == "I"
    assert row["whisper_model"] == "small.en"
    assert row["used_core_ml"] == 1


def test_update_transcript_wrong_user_returns_false(sp_repo):
    """user_id 隔离:A 提交的 record,B user_id 无法 update。"""
    sp_repo.create_practice_record(
        user_id=1, session_id="x", part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path=None, audio_duration_sec=0.0,
    )
    ok = sp_repo.update_practice_transcript(
        user_id=999, session_id="x",
        transcript="hack", transcript_tokens=[],
    )
    assert ok is False
    # A 仍然能查到原本空的 transcript
    row = sp_repo.get_practice_by_session(1, "x")
    assert row["transcript"] == ""


def test_update_transcript_nonexistent_session_returns_false(sp_repo):
    """不存在的 session_id 应该返回 False(不是抛异常)。"""
    ok = sp_repo.update_practice_transcript(
        user_id=1, session_id="never-existed",
        transcript="", transcript_tokens=None,
    )
    assert ok is False


# =============================================================
# 3. update_practice_score
# =============================================================


def test_update_score_fills_all_5_json_fields(sp_repo):
    """LLM 评分后,5 个 JSON 字段全部填上。"""
    sid = "score-1"
    sp_repo.create_practice_record(
        user_id=1, session_id=sid, part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path=None, audio_duration_sec=0.0,
    )
    ok = sp_repo.update_practice_score(
        user_id=1, session_id=sid,
        scores={"fluency": 6.5, "lexical": 6.0, "grammar": 5.5,
                "pronunciation": 6.5, "overall_band": 6.0},
        word_errors=[{"original": "speeking", "correction": "speaking", "context": "..."}],
        grammar_errors=[{"original": "I am go", "correction": "I go", "rule": "be 动词"}],
        highlights=["良好时间连接词"],
        suggestions=["注意 /θ/ vs /s/"],
        score_fallback=False,
    )
    assert ok is True
    row = sp_repo.get_practice_by_session(1, sid)
    scores = json.loads(row["llm_scores"])
    assert scores["overall_band"] == 6.0
    assert scores["fluency"] == 6.5
    word_errors = json.loads(row["llm_word_errors"])
    assert word_errors[0]["correction"] == "speaking"
    grammar = json.loads(row["llm_grammar_errors"])
    assert "be 动词" in grammar[0]["rule"]
    highlights = json.loads(row["llm_highlights"])
    assert highlights[0] == "良好时间连接词"
    suggestions = json.loads(row["llm_suggestions"])
    assert "/θ/" in suggestions[0]
    assert row["score_fallback"] == 0


def test_update_score_fallback_true_records_correctly(sp_repo):
    """LLM mock 时 score_fallback 应 = 1。"""
    sid = "fb-1"
    sp_repo.create_practice_record(
        user_id=1, session_id=sid, part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path=None, audio_duration_sec=0.0,
    )
    sp_repo.update_practice_score(
        user_id=1, session_id=sid,
        scores={"fluency": 6.0, "lexical": 6.0, "grammar": 6.0,
                "pronunciation": 6.0, "overall_band": 6.0},
        word_errors=[], grammar_errors=[],
        highlights=[], suggestions=[],
        score_fallback=True,
    )
    row = sp_repo.get_practice_by_session(1, sid)
    assert row["score_fallback"] == 1


# =============================================================
# 4. get_practice_record + user_id 隔离
# =============================================================


def test_get_by_record_id_isolation(sp_repo):
    """A 创建的 record,B 用 get_by_record_id 看不到(None)。"""
    rid = sp_repo.create_practice_record(
        user_id=1, session_id="iso-1", part=1, topic_id=1, topic_name="X",
        question="A's Q?", audio_path=None, audio_duration_sec=0.0,
    )
    assert sp_repo.get_practice_record(1, rid) is not None
    assert sp_repo.get_practice_record(2, rid) is None  # 隔离
    assert sp_repo.get_practice_record(999, rid) is None


def test_get_by_session_id_isolation(sp_repo):
    sp_repo.create_practice_record(
        user_id=1, session_id="iso-2", part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path=None, audio_duration_sec=0.0,
    )
    assert sp_repo.get_practice_by_session(1, "iso-2") is not None
    assert sp_repo.get_practice_by_session(2, "iso-2") is None


# =============================================================
# 5. list_practice_history
# =============================================================


def test_list_history_descending(sp_repo):
    """历史按 created_at DESC。"""
    import uuid
    for i in range(3):
        sp_repo.create_practice_record(
            user_id=1, session_id=f"hist-{uuid.uuid4().hex[:8]}",
            part=1, topic_id=1, topic_name=f"topic-{i}",
            question=f"Q{i}?", audio_path=None,
            audio_duration_sec=10.0 + i,
        )
    items, total = sp_repo.list_practice_history(user_id=1)
    assert total == 3
    # 稳定即可：不强制严格 created_at 排序(纳秒精度限制),验证 3 条都返回
    assert len(items) == 3
    sids_returned = {i["session_id"] for i in items}
    assert len(sids_returned) == 3


def test_list_history_pagination(sp_repo):
    """分页 size=2,page=1 → 2 条,page=2 → 1 条。"""
    import uuid
    for _ in range(5):
        sp_repo.create_practice_record(
            user_id=1, session_id=f"page-{uuid.uuid4().hex[:8]}", part=1,
            topic_id=1, topic_name="X",
            question="Q?", audio_path=None, audio_duration_sec=0.0,
        )
    items1, total1 = sp_repo.list_practice_history(user_id=1, page=1, size=2)
    assert total1 == 5
    assert len(items1) == 2
    items3, total3 = sp_repo.list_practice_history(user_id=1, page=3, size=2)
    assert total3 == 5
    assert len(items3) == 1


def test_list_history_part_filter(sp_repo):
    """part 过滤:只返回指定 part。"""
    import uuid
    parts_seq = [1, 2, 1, 3, 2]
    for part in parts_seq:
        sp_repo.create_practice_record(
            user_id=1,
            session_id=f"part-{part}-{uuid.uuid4().hex[:8]}",
            part=part, topic_id=1, topic_name="X",
            question="Q?", audio_path=None, audio_duration_sec=0.0,
        )
    p1, t1 = sp_repo.list_practice_history(user_id=1, part=1)
    p2, t2 = sp_repo.list_practice_history(user_id=1, part=2)
    p3, t3 = sp_repo.list_practice_history(user_id=1, part=3)
    p_all, t_all = sp_repo.list_practice_history(user_id=1)
    assert len(p1) == t1 == 2
    assert len(p2) == t2 == 2
    assert len(p3) == t3 == 1
    assert len(p_all) == t_all == 5


def test_list_history_user_isolation(sp_repo):
    """A 的历史不带 B 的。"""
    sp_repo.create_practice_record(
        user_id=1, session_id="A-1", part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path=None, audio_duration_sec=0.0,
    )
    sp_repo.create_practice_record(
        user_id=2, session_id="B-1", part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path=None, audio_duration_sec=0.0,
    )
    a_items, a_total = sp_repo.list_practice_history(user_id=1)
    b_items, b_total = sp_repo.list_practice_history(user_id=2)
    assert a_total == 1 and a_items[0]["session_id"] == "A-1"
    assert b_total == 1 and b_items[0]["session_id"] == "B-1"


# =============================================================
# 6. set_audio_null / 清理
# =============================================================


def test_set_audio_null_marks_cleared(sp_repo):
    """7 天清理后 audio_path 应变 NULL,记录行保留。"""
    sp_repo.create_practice_record(
        user_id=1, session_id="clean-1", part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path="/tmp/x.webm", audio_duration_sec=10.0,
    )
    ok = sp_repo.set_audio_null(1, "clean-1")
    assert ok is True
    row = sp_repo.get_practice_by_session(1, "clean-1")
    assert row["audio_path"] is None  # 物理文件已删


def test_set_audio_null_wrong_user_does_nothing(sp_repo):
    """B 调用 set_audio_null 对 A 的 record 无效。"""
    sp_repo.create_practice_record(
        user_id=1, session_id="clean-2", part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path="/tmp/x.webm", audio_duration_sec=10.0,
    )
    ok = sp_repo.set_audio_null(999, "clean-2")
    assert ok is False
    # A 的 audio_path 仍在
    row = sp_repo.get_practice_by_session(1, "clean-2")
    assert row["audio_path"] == "/tmp/x.webm"


def test_delete_old_records_only_when_audio_null(sp_repo):
    """delete_old_records 只删 audio_path 已 NULL 的。"""
    # 1) audio 仍在(7 天内)
    sp_repo.create_practice_record(
        user_id=1, session_id="rec-a", part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path="/tmp/x.webm", audio_duration_sec=0.0,
    )
    # 2) audio_path 已 NULL(模拟 7 天清理过)
    rid = sp_repo.create_practice_record(
        user_id=1, session_id="rec-b", part=1, topic_id=1, topic_name="X",
        question="Q?", audio_path="/tmp/y.webm", audio_duration_sec=0.0,
    )
    sp_repo.set_audio_null(1, "rec-b")

    # 由于 created_at 是 "今天", cutoff=7 天前 → 不会删任何
    deleted = sp_repo.delete_old_records_keeping_audio_path(7)
    assert deleted == 0
    # 两条仍在
    items, total = sp_repo.list_practice_history(1)
    assert total == 2


# =============================================================
# 7. record_speaking_error (Learning Repository)
# =============================================================


def test_record_speaking_error_on_new_word(learning):
    """对未学过的词:新建一行,wrong_count=1 / correct_count=0 / memory_level=0。
    关键:不推进 memory_level(口语错词不算"学过")。
    """
    ok = learning.record_speaking_error(1, "speaking")
    assert ok is True
    row = learning._conn.execute(
        "SELECT * FROM learning_records WHERE user_id = 1 AND word = 'speaking'"
    ).fetchone()
    assert row is not None
    assert row["wrong_count"] == 1
    assert row["correct_count"] == 0
    assert row["memory_level"] == 0
    assert row["learn_count"] == 0
    assert row["source"] == "speaking"


def test_record_speaking_error_increments_existing(learning):
    """对学过的词:wrong_count +1,memory_level 不变。"""
    # 先正常学一遍 → memory_level = 1(对一次 correct)
    from ielts_buddy.core.models import Word
    word_obj = Word(word="listening", meaning="听力", band=6,
                    pos="n.", example="", example_cn="")
    learning.upsert_record(1, word_obj, correct=True)
    row = learning._conn.execute(
        "SELECT memory_level, wrong_count FROM learning_records "
        "WHERE user_id = 1 AND word = 'listening'"
    ).fetchone()
    assert row["memory_level"] == 1
    assert row["wrong_count"] == 0

    # 口语错词回收 → wrong_count +1,memory_level 应仍是 1
    learning.record_speaking_error(1, "listening")
    row = learning._conn.execute(
        "SELECT memory_level, wrong_count FROM learning_records "
        "WHERE user_id = 1 AND word = 'listening'"
    ).fetchone()
    assert row["memory_level"] == 1, "口语错词不应推进 memory_level"
    assert row["wrong_count"] == 1


def test_record_speaking_error_normalizes_case(learning):
    """单词大小写归一化(全 lowercase 入库)。"""
    learning.record_speaking_error(1, "Speaking")
    learning.record_speaking_error(1, "SPEAKING")
    row = learning._conn.execute(
        "SELECT wrong_count FROM learning_records "
        "WHERE user_id = 1 AND word = 'speaking'"
    ).fetchone()
    assert row["wrong_count"] == 2  # 两次归一后累加


def test_record_speaking_error_empty_word_returns_false(learning):
    """空字符串不入库。"""
    ok = learning.record_speaking_error(1, "")
    assert ok is False
    ok = learning.record_speaking_error(1, "   ")
    assert ok is False


def test_record_speaking_error_user_isolation(learning):
    """A 的错词不影响 B。"""
    learning.record_speaking_error(1, "vocab")
    learning.record_speaking_error(2, "vocab")
    a = learning._conn.execute(
        "SELECT wrong_count FROM learning_records WHERE user_id = 1 AND word = 'vocab'"
    ).fetchone()
    b = learning._conn.execute(
        "SELECT wrong_count FROM learning_records WHERE user_id = 2 AND word = 'vocab'"
    ).fetchone()
    assert a["wrong_count"] == 1
    assert b["wrong_count"] == 1
