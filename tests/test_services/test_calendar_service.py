"""测试 ``CalendarService`` —— 学习日历热力图聚合逻辑（v3.6 新增）。

覆盖：
1. 空数据 → 全 0、streak=0
2. focus_sessions 累加（sum → minutes）
3. learning_records 累加（count → minutes）
4. 混合数据聚合（同一天两个数据源相加）
5. user_id 隔离（user A 看不到 user B 的数据）
6. 等级映射（0/1-15/16-30/31-60/>60）
7. streak current（今天 0 → 0；连续 3 天 → 3；中间断 → 断后归零）
8. streak max（全区间最长连续）
9. 表不存在时静默跳过（迁移前的场景）
10. today_summary 字段完整性
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from ielts_buddy.web.calendar_service import CalendarService


# =============================================================
# Fixtures
# =============================================================


@pytest.fixture
def conn():
    """内存 SQLite，建 focus_sessions + learning_records 两张表。"""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE focus_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            activity TEXT NOT NULL DEFAULT 'other',
            planned_sec INTEGER NOT NULL DEFAULT 1500,
            duration_sec INTEGER NOT NULL DEFAULT 0,
            interrupted INTEGER NOT NULL DEFAULT 0,
            note TEXT DEFAULT '',
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT '',
            sync_status TEXT NOT NULL DEFAULT 'synced'
        );
        CREATE TABLE learning_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            word_data TEXT NOT NULL,
            memory_level INTEGER DEFAULT 0,
            next_review TEXT,
            learn_count INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0,
            first_learned TEXT,
            last_reviewed TEXT,
            is_starred INTEGER DEFAULT 0,
            is_difficult INTEGER DEFAULT 0,
            source TEXT DEFAULT 'builtin',
            updated_at TEXT NOT NULL DEFAULT '',
            sync_status TEXT NOT NULL DEFAULT 'synced',
            UNIQUE (user_id, word)
        );
        """
    )
    yield c
    c.close()


def _insert_focus(
    conn, user_id: int, started_at: str, duration_sec: int
) -> None:
    conn.execute(
        """INSERT INTO focus_sessions
               (user_id, activity, planned_sec, duration_sec,
                interrupted, started_at, ended_at, created_at)
           VALUES (?, 'vocab', ?, ?, 0, ?, ?, ?)""",
        (user_id, max(duration_sec, 60), duration_sec,
         started_at, started_at, started_at),
    )
    conn.commit()


def _insert_review(
    conn, user_id: int, word: str, last_reviewed: str
) -> None:
    conn.execute(
        """INSERT INTO learning_records
               (user_id, word, word_data, last_reviewed)
           VALUES (?, ?, '{}', ?)""",
        (user_id, word, last_reviewed),
    )
    conn.commit()


# =============================================================
# 1. 空数据
# =============================================================


class TestEmptyData:
    def test_daily_minutes_empty(self, conn):
        svc = CalendarService(conn, user_id=1)
        daily = svc.get_daily_minutes(months=3)
        assert daily == {}

    def test_calendar_data_empty(self, conn):
        svc = CalendarService(conn, user_id=1)
        days = svc.get_calendar_data(months=1)
        # months=1 → 31 天全 0 分钟全 level 0
        assert len(days) == 31
        assert all(d["minutes"] == 0 and d["level"] == 0 for d in days)
        # 第一天 = 30 天前，今天是最后一天
        today = date.today()
        assert days[-1]["date"] == today.isoformat()
        assert days[0]["date"] == (today - timedelta(days=30)).isoformat()

    def test_today_summary_empty(self, conn):
        svc = CalendarService(conn, user_id=1)
        t = svc.get_today_summary()
        assert t["minutes"] == 0
        assert t["level"] == 0
        assert t["date"] == date.today().isoformat()

    def test_streak_empty(self, conn):
        svc = CalendarService(conn, user_id=1)
        s = svc.get_streak()
        assert s == {"current": 0, "max": 0}


# =============================================================
# 2. focus_sessions 聚合
# =============================================================


class TestFocusSessionsAggregation:
    def test_single_focus_today(self, conn):
        """今天 1 次 25 min 番茄 → today minutes=25, level=2。"""
        today = date.today().isoformat()
        _insert_focus(conn, 1, f"{today}T10:00:00", 25 * 60)

        svc = CalendarService(conn, user_id=1)
        daily = svc.get_daily_minutes(months=3)
        assert daily.get(today) == 25

        t = svc.get_today_summary()
        assert t["minutes"] == 25
        # 25 在 (15, 30] → level 2
        assert t["level"] == 2

    def test_multiple_focus_same_day_summed(self, conn):
        """同一天 2 次番茄 = 25 + 30 = 55 min → level 3。"""
        today = date.today().isoformat()
        _insert_focus(conn, 1, f"{today}T09:00:00", 25 * 60)
        _insert_focus(conn, 1, f"{today}T14:00:00", 30 * 60)

        svc = CalendarService(conn, user_id=1)
        daily = svc.get_daily_minutes(months=3)
        assert daily[today] == 55
        assert svc.get_today_summary()["level"] == 3

    def test_focus_only_counts_whole_minutes(self, conn):
        """duration_sec = 1500 → 25 min（整除）。"""
        today = date.today().isoformat()
        _insert_focus(conn, 1, f"{today}T10:00:00", 1500)
        svc = CalendarService(conn, user_id=1)
        assert svc.get_today_summary()["minutes"] == 25  # 1500 // 60


# =============================================================
# 3. learning_records 聚合
# =============================================================


class TestLearningRecordsAggregation:
    def test_single_review_today(self, conn):
        """今天复习 1 次 = 1 分钟（简化：count * 1）。"""
        today = date.today().isoformat()
        _insert_review(conn, 1, "hello", f"{today}T08:00:00")

        svc = CalendarService(conn, user_id=1)
        assert svc.get_today_summary()["minutes"] == 1

    def test_multiple_reviews_same_day(self, conn):
        """今天复习 10 个词 = 10 分钟。"""
        today = date.today().isoformat()
        for i in range(10):
            _insert_review(conn, 1, f"word{i}", f"{today}T08:00:00")

        svc = CalendarService(conn, user_id=1)
        assert svc.get_today_summary()["minutes"] == 10


# =============================================================
# 4. 混合数据（focus + review 同一天）
# =============================================================


class TestMixedAggregation:
    def test_focus_plus_review_same_day(self, conn):
        """番茄 25 min + 复习 5 个词 = 30 min → level 2。"""
        today = date.today().isoformat()
        _insert_focus(conn, 1, f"{today}T10:00:00", 25 * 60)
        for i in range(5):
            _insert_review(conn, 1, f"word{i}", f"{today}T08:00:00")

        svc = CalendarService(conn, user_id=1)
        t = svc.get_today_summary()
        assert t["minutes"] == 30
        assert t["level"] == 2


# =============================================================
# 5. user_id 隔离
# =============================================================


class TestUserIsolation:
    def test_other_user_data_not_counted(self, conn):
        """user_id=1 看不到 user_id=2 的数据。"""
        today = date.today().isoformat()
        _insert_focus(conn, 2, f"{today}T10:00:00", 25 * 60)
        _insert_focus(conn, 2, f"{today}T11:00:00", 25 * 60)

        svc = CalendarService(conn, user_id=1)
        assert svc.get_today_summary()["minutes"] == 0


# =============================================================
# 6. 等级映射
# =============================================================


class TestLevelMapping:
    @pytest.mark.parametrize(
        "minutes,expected_level",
        [
            (0, 0),
            (1, 1),
            (15, 1),
            (16, 2),
            (30, 2),
            (31, 3),
            (60, 3),
            (61, 4),
            (120, 4),
        ],
    )
    def test_thresholds(self, minutes, expected_level):
        assert CalendarService._minutes_to_level(minutes) == expected_level


# =============================================================
# 7. streak current
# =============================================================


class TestStreakCurrent:
    def test_today_no_study(self, conn):
        """今天没学 → current=0。"""
        svc = CalendarService(conn, user_id=1)
        assert svc.get_streak()["current"] == 0

    def test_only_today(self, conn):
        """只今天学了 → current=1。"""
        today = date.today().isoformat()
        _insert_focus(conn, 1, f"{today}T10:00:00", 25 * 60)

        svc = CalendarService(conn, user_id=1)
        assert svc.get_streak()["current"] == 1

    def test_three_consecutive_days_including_today(self, conn):
        """今天 + 昨天 + 前天连续 3 天 → current=3。"""
        today = date.today()
        for offset in range(3):
            d = (today - timedelta(days=offset)).isoformat()
            _insert_focus(conn, 1, f"{d}T10:00:00", 25 * 60)

        svc = CalendarService(conn, user_id=1)
        assert svc.get_streak()["current"] == 3

    def test_today_zero_breaks_streak(self, conn):
        """今天没学 + 昨天前天连续 → current=0（断在今天）。"""
        today = date.today()
        for offset in range(1, 3):  # 只插昨天/前天
            d = (today - timedelta(days=offset)).isoformat()
            _insert_focus(conn, 1, f"{d}T10:00:00", 25 * 60)

        svc = CalendarService(conn, user_id=1)
        assert svc.get_streak()["current"] == 0


# =============================================================
# 8. streak max
# =============================================================


class TestStreakMax:
    def test_max_with_gap(self, conn):
        """3 天 + 1 天空 + 2 天 → max=3。"""
        today = date.today()
        # 今天 / 昨天 / 前天
        for offset in range(3):
            d = (today - timedelta(days=offset)).isoformat()
            _insert_focus(conn, 1, f"{d}T10:00:00", 25 * 60)
        # 大前天（断）
        # 5/6/7 天前
        for offset in range(5, 8):
            d = (today - timedelta(days=offset)).isoformat()
            _insert_focus(conn, 1, f"{d}T10:00:00", 25 * 60)

        svc = CalendarService(conn, user_id=1)
        assert svc.get_streak()["max"] == 3

    def test_max_single_long_run(self, conn):
        """连续 7 天 → max=7。"""
        today = date.today()
        for offset in range(7):
            d = (today - timedelta(days=offset)).isoformat()
            _insert_focus(conn, 1, f"{d}T10:00:00", 25 * 60)

        svc = CalendarService(conn, user_id=1)
        assert svc.get_streak()["max"] == 7


# =============================================================
# 9. 表缺失场景
# =============================================================


class TestMissingTables:
    def test_focus_table_missing_does_not_crash(self):
        """focus_sessions 表不存在 → 静默返回空聚合。"""
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        # 不建任何业务表
        c.executescript(
            """CREATE TABLE learning_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                word_data TEXT NOT NULL,
                last_reviewed TEXT,
                UNIQUE (user_id, word)
            );"""
        )
        today = date.today().isoformat()
        c.execute(
            "INSERT INTO learning_records (user_id, word, word_data, last_reviewed) "
            "VALUES (1, 'a', '{}', ?)",
            (f"{today}T08:00:00",),
        )
        c.commit()

        svc = CalendarService(c, user_id=1)
        # focus_sessions 缺失应被 try/except 吞掉，learning_records 仍能算
        assert svc.get_today_summary()["minutes"] == 1
        c.close()

    def test_both_tables_missing(self):
        """两张表都不存在 → 全 0、不抛异常。"""
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        svc = CalendarService(c, user_id=1)
        assert svc.get_daily_minutes(months=3) == {}
        assert svc.get_today_summary()["minutes"] == 0
        assert svc.get_streak() == {"current": 0, "max": 0}
        c.close()


# =============================================================
# 10. today_summary 字段完整性
# =============================================================


class TestTodaySummaryShape:
    def test_returns_all_fields(self, conn):
        today = date.today().isoformat()
        _insert_focus(conn, 1, f"{today}T10:00:00", 25 * 60)

        svc = CalendarService(conn, user_id=1)
        t = svc.get_today_summary()
        assert set(t.keys()) == {"date", "minutes", "level"}
        assert t["date"] == today
        assert isinstance(t["minutes"], int)
        assert isinstance(t["level"], int)
