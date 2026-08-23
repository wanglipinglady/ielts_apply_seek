"""SQLiteFocusSessionRepository 单测（v3.6 番茄钟）。

覆盖：
- start_session 落库 + 自动赋 id
- complete_session 写入实际时长 + interrupted + note
- get_history 按 started_at DESC,user 隔离
- get_today_summary 今日累计 (总数 / 总秒数 / 完成数 / 放弃数)
- get_total_count 累计番茄数
- activity 白名单校验 (非法 activity 回落到 "other")
- planned_sec 边界 (60-7200)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ielts_buddy.core.models import FocusSession
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
    return container.focus_sessions


def _make_session(
    user_id: int = 1,
    activity: str = "vocab",
    planned_sec: int = 1500,
    duration_sec: int = 0,
    interrupted: bool = False,
    note: str = "",
    started_at: str | None = None,
    created_at: str | None = None,
) -> FocusSession:
    now = datetime.now().isoformat(timespec="seconds")
    return FocusSession(
        user_id=user_id,
        activity=activity,
        planned_sec=planned_sec,
        duration_sec=duration_sec,
        interrupted=interrupted,
        note=note,
        started_at=started_at or now,
        created_at=created_at or now,
    )


# =============================================================
# Tests
# =============================================================


class TestStartSession:
    def test_start_returns_int_id(self, repo):
        session = _make_session()
        sid = repo.start_session(1, session)
        assert isinstance(sid, int)
        assert sid > 0

    def test_start_persists_all_fields(self, repo, container):
        session = _make_session(
            activity="writing", planned_sec=1800, note="开始 Task 2"
        )
        sid = repo.start_session(1, session)
        cur = container._conn.execute(
            "SELECT user_id, activity, planned_sec, duration_sec, "
            "interrupted, note FROM focus_sessions WHERE id = ?",
            (sid,),
        ).fetchone()
        assert cur["user_id"] == 1
        assert cur["activity"] == "writing"
        assert cur["planned_sec"] == 1800
        assert cur["duration_sec"] == 0       # start 时为 0
        assert cur["interrupted"] == 0       # start 时未中断
        assert cur["note"] == "开始 Task 2"

    def test_invalid_activity_normalized_to_other(self, repo, container):
        session = _make_session(activity="hacking")  # 不在白名单
        sid = repo.start_session(1, session)
        cur = container._conn.execute(
            "SELECT activity FROM focus_sessions WHERE id = ?", (sid,)
        ).fetchone()
        assert cur["activity"] == "other"

    def test_multiple_sessions_get_distinct_ids(self, repo):
        ids = set()
        for _ in range(5):
            ids.add(repo.start_session(1, _make_session()))
        assert len(ids) == 5


class TestCompleteSession:
    def test_complete_writes_duration_interrupted_note(self, repo, container):
        sid = repo.start_session(1, _make_session(activity="reading"))
        ok = repo.complete_session(
            user_id=1, session_id=sid,
            duration_sec=1500, interrupted=False, note="读完 chapter 5",
        )
        assert ok is True

        cur = container._conn.execute(
            "SELECT duration_sec, interrupted, note, ended_at "
            "FROM focus_sessions WHERE id = ?",
            (sid,),
        ).fetchone()
        assert cur["duration_sec"] == 1500
        assert cur["interrupted"] == 0
        assert cur["note"] == "读完 chapter 5"
        assert cur["ended_at"]                  # 写入结束时间

    def test_complete_interrupted_true(self, repo, container):
        sid = repo.start_session(1, _make_session(planned_sec=1500))
        repo.complete_session(1, sid, duration_sec=300, interrupted=True, note="")
        cur = container._conn.execute(
            "SELECT interrupted, duration_sec FROM focus_sessions WHERE id = ?",
            (sid,),
        ).fetchone()
        assert cur["interrupted"] == 1
        assert cur["duration_sec"] == 300       # 实际时长 < planned

    def test_complete_unknown_id_returns_false(self, repo):
        ok = repo.complete_session(
            user_id=1, session_id=999999,
            duration_sec=100, interrupted=False, note="",
        )
        assert ok is False

    def test_complete_other_users_session_returns_false(self, repo):
        sid = repo.start_session(2, _make_session(user_id=2))
        ok = repo.complete_session(
            user_id=1, session_id=sid,
            duration_sec=100, interrupted=False, note="",
        )
        assert ok is False       # user 1 拿不到 user 2 的会话

    def test_complete_marks_sync_status_pending_upload(self, repo, container):
        sid = repo.start_session(1, _make_session())
        repo.complete_session(1, sid, duration_sec=100, interrupted=False, note="")
        cur = container._conn.execute(
            "SELECT sync_status FROM focus_sessions WHERE id = ?", (sid,)
        ).fetchone()
        assert cur["sync_status"] == "pending_upload"


class TestGetHistory:
    def test_history_returns_recent_first(self, repo):
        # 三次插入,started_at 各往后错开 1 秒,确保 started_at DESC 稳定排序
        base = datetime.now()
        ids = []
        for i in range(3):
            ts = (base + timedelta(seconds=i)).isoformat(timespec="seconds")
            ids.append(repo.start_session(1, _make_session(started_at=ts)))
        h = repo.get_history(1, limit=10)
        assert len(h) == 3
        # 倒序：新插入的在前
        assert [s.id for s in h] == list(reversed(ids))

    def test_history_respects_limit(self, repo):
        for _ in range(5):
            repo.start_session(1, _make_session())
        h = repo.get_history(1, limit=2)
        assert len(h) == 2

    def test_history_user_isolation(self, repo):
        repo.start_session(1, _make_session(user_id=1, activity="vocab"))
        repo.start_session(2, _make_session(user_id=2, activity="writing"))
        repo.start_session(1, _make_session(user_id=1, activity="exam"))

        h1 = repo.get_history(1, limit=10)
        h2 = repo.get_history(2, limit=10)
        assert len(h1) == 2
        assert len(h2) == 1
        assert all(s.user_id == 1 for s in h1)
        assert all(s.user_id == 2 for s in h2)
        assert h2[0].activity == "writing"

    def test_history_includes_all_focus_session_fields(self, repo):
        sid = repo.start_session(1, _make_session(
            activity="exam", planned_sec=1500, note="模考"
        ))
        repo.complete_session(1, sid, duration_sec=1450, interrupted=False, note="完成")
        h = repo.get_history(1)
        s = h[0]
        assert s.id == sid
        assert s.activity == "exam"
        assert s.planned_sec == 1500
        assert s.duration_sec == 1450
        assert s.interrupted is False
        assert s.note == "完成"
        assert s.started_at != ""
        assert s.ended_at != ""


class TestTodaySummary:
    def test_today_summary_counts_today_only(self, repo, container):
        today_sid = repo.start_session(1, _make_session(started_at="2026-08-23T10:00:00"))
        repo.complete_session(1, today_sid, duration_sec=1500, interrupted=False, note="")

        # 昨天一行（手工造）
        cur = container._conn.execute(
            "INSERT INTO focus_sessions "
            "(user_id, activity, planned_sec, duration_sec, interrupted, "
            " started_at, ended_at, created_at) "
            "VALUES (1, 'vocab', 1500, 1500, 0, "
            " '2026-08-22T10:00:00', '2026-08-22T10:25:00', '2026-08-22T10:00:00')"
        )
        container._conn.commit()

        s = repo.get_today_summary(1)
        assert s["total"] == 1               # 只有今天这 1 行
        assert s["total_sec"] == 1500
        assert s["completed"] == 1
        assert s["abandoned"] == 0

    def test_today_summary_zero_when_empty(self, repo):
        s = repo.get_today_summary(1)
        assert s["total"] == 0
        assert s["total_sec"] == 0
        assert s["completed"] == 0
        assert s["abandoned"] == 0

    def test_today_summary_user_isolation(self, repo):
        repo.start_session(1, _make_session(user_id=1))
        repo.start_session(2, _make_session(user_id=2))
        s1 = repo.get_today_summary(1)
        s2 = repo.get_today_summary(2)
        assert s1["total"] == 1
        assert s2["total"] == 1

    def test_today_summary_completed_threshold_80pct(self, repo):
        # 完成 95% → completed
        sid = repo.start_session(1, _make_session(planned_sec=1500))
        repo.complete_session(1, sid, duration_sec=1425, interrupted=False, note="")
        # 完成 70% → 不算 completed
        sid2 = repo.start_session(1, _make_session(planned_sec=1500))
        repo.complete_session(1, sid2, duration_sec=1050, interrupted=False, note="")
        # 中途放弃
        sid3 = repo.start_session(1, _make_session(planned_sec=1500))
        repo.complete_session(1, sid3, duration_sec=200, interrupted=True, note="")

        s = repo.get_today_summary(1)
        assert s["total"] == 3
        assert s["completed"] == 1      # 只有 95% 那个算
        assert s["abandoned"] == 1


class TestTotalCount:
    def test_total_count_zero_initially(self, repo):
        assert repo.get_total_count(1) == 0

    def test_total_count_increments_on_start(self, repo):
        for _ in range(4):
            repo.start_session(1, _make_session())
        assert repo.get_total_count(1) == 4

    def test_total_count_user_isolation(self, repo):
        repo.start_session(1, _make_session(user_id=1))
        repo.start_session(1, _make_session(user_id=1))
        repo.start_session(2, _make_session(user_id=2))
        assert repo.get_total_count(1) == 2
        assert repo.get_total_count(2) == 1


class TestEdgeCases:
    def test_planned_sec_min(self, repo, container):
        """planned_sec 60 是最小值(下界)。"""
        session = _make_session(planned_sec=60)
        sid = repo.start_session(1, session)
        cur = container._conn.execute(
            "SELECT planned_sec FROM focus_sessions WHERE id = ?", (sid,)
        ).fetchone()
        assert cur["planned_sec"] == 60

    def test_zero_duration_complete_means_immediate_abort(self, repo, container):
        """duration_sec=0 且 interrupted=True 表示用户点开始立刻放弃。"""
        sid = repo.start_session(1, _make_session(planned_sec=1500))
        repo.complete_session(1, sid, duration_sec=0, interrupted=True, note="")
        cur = container._conn.execute(
            "SELECT duration_sec, interrupted FROM focus_sessions WHERE id = ?",
            (sid,),
        ).fetchone()
        assert cur["duration_sec"] == 0
        assert cur["interrupted"] == 1

    def test_long_session_2hours(self, repo, container):
        """planned_sec=7200 (2h 上界) 应允许。"""
        sid = repo.start_session(1, _make_session(planned_sec=7200))
        repo.complete_session(1, sid, duration_sec=7200, interrupted=False, note="2h 模考")
        cur = container._conn.execute(
            "SELECT planned_sec, duration_sec FROM focus_sessions WHERE id = ?",
            (sid,),
        ).fetchone()
        assert cur["planned_sec"] == 7200
        assert cur["duration_sec"] == 7200