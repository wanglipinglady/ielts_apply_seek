"""学习日历热力图服务（v3.6 新增）。

数据源：聚合两张表的"每日学习强度"——
  - focus_sessions.duration_sec（番茄钟专注秒数，转换为分钟）
  - learning_records.last_reviewed（每日复习单词次数）

返回每日的聚合分钟数，再映射成 0-4 等级用于热力图色块。

设计：
  - 复用 WebStatsService 的 `_exec` 双 backend 适配（SQLite + MySQL 都跑得动）
  - 完全独立于老 ReportService（老 service 的 _conn 是 sqlite3 风格，MySQL 跑不了）
  - 数据隔离：所有查询 WHERE user_id = ?
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional


class CalendarService:
    """学习日历热力图服务。

    Args:
        connection: 业务容器的连接对象
            - SQLite 模式: sqlite3.Connection
            - MySQL 模式: sqlalchemy.Engine
        user_id: 当前 web 用户 id
    """

    def __init__(self, connection, user_id: int) -> None:
        self._conn = connection
        self._user_id = user_id
        import sqlite3 as _sqlite3
        self._is_sqlite = isinstance(connection, _sqlite3.Connection)

    # =============================================================
    # 内部 helper
    # =============================================================

    def _exec(self, sql: str, params: tuple = ()) -> list:
        """SQLite 走原生 sqlite3 + ? 占位符；MySQL 走 SQLAlchemy text() + :param。

        返回 list[dict]，date/datetime 统一规范成 isoformat 字符串。
        """
        if self._is_sqlite:
            cur = self._conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
        else:
            from sqlalchemy import text
            from datetime import date as _date, datetime as _datetime
            with self._conn.connect() as conn:
                result = conn.execute(text(sql), params)
                rows = []
                for row in result:
                    m = dict(row._mapping)
                    for k, v in list(m.items()):
                        if isinstance(v, (_date, _datetime)):
                            m[k] = v.isoformat()
                    rows.append(m)
                return rows

    # =============================================================
    # 业务方法
    # =============================================================

    def get_daily_minutes(self, months: int = 3) -> dict[str, int]:
        """聚合最近 N 月每天的「学习分钟数」。

        数据源合并：
          - focus_sessions: SUM(duration_sec) / 60（专注分钟）
          - learning_records: COUNT(*) × 1（每次复习记 1 分钟，简化）

        Returns:
            {"2026-08-23": 25, "2026-08-22": 0, ...}
            只包含有数据的日期（没数据的不出现在 dict 里）
        """
        from datetime import datetime
        today = date.today()
        start = today - timedelta(days=months * 30)
        start_str = start.isoformat()

        result: dict[str, int] = {}

        # 1) 番茄钟专注分钟
        try:
            rows = self._exec(
                """SELECT substr(started_at, 1, 10) AS study_date,
                          CAST(COALESCE(SUM(duration_sec), 0) AS INTEGER) AS minutes
                   FROM focus_sessions
                   WHERE user_id = ? AND substr(started_at, 1, 10) >= ?
                   GROUP BY substr(started_at, 1, 10)""",
                (self._user_id, start_str),
            )
            for r in rows:
                d = r["study_date"]
                minutes = int(r["minutes"] or 0) // 60
                if minutes > 0:
                    result[d] = result.get(d, 0) + minutes
        except Exception:
            # focus_sessions 表可能不存在（迁移前）—— 静默跳过
            pass

        # 2) 复习次数（简化：每次复习 ≈ 1 分钟）
        try:
            rows = self._exec(
                """SELECT substr(last_reviewed, 1, 10) AS study_date,
                          COUNT(*) AS cnt
                   FROM learning_records
                   WHERE user_id = ? AND substr(last_reviewed, 1, 10) >= ?
                     AND last_reviewed IS NOT NULL AND last_reviewed != ''
                   GROUP BY substr(last_reviewed, 1, 10)""",
                (self._user_id, start_str),
            )
            for r in rows:
                d = r["study_date"]
                cnt = int(r["cnt"] or 0)
                if cnt > 0:
                    result[d] = result.get(d, 0) + cnt
        except Exception:
            # learning_records 表可能不存在
            pass

        return result

    def get_calendar_data(self, months: int = 3) -> list[dict[str, Any]]:
        """生成日历热力图数据。

        Returns:
            [{date: "2026-08-23", minutes: 25, level: 1}, ...]
            覆盖 [today - months*30, today] 全区间，没数据的日期 minutes=0
            level: 0=无 / 1=<15min / 2=<30min / 3=<60min / 4=≥60min
        """
        today = date.today()
        start = today - timedelta(days=months * 30)
        daily = self.get_daily_minutes(months)

        result: list[dict[str, Any]] = []
        current = start
        while current <= today:
            d = current.isoformat()
            minutes = daily.get(d, 0)
            level = self._minutes_to_level(minutes)
            result.append({
                "date": d,
                "minutes": minutes,
                "level": level,
            })
            current += timedelta(days=1)
        return result

    def get_today_summary(self) -> dict[str, Any]:
        """今日学习分钟数（用于侧边栏快速展示）。"""
        daily = self.get_daily_minutes(months=1)
        today_str = date.today().isoformat()
        return {
            "date": today_str,
            "minutes": daily.get(today_str, 0),
            "level": self._minutes_to_level(daily.get(today_str, 0)),
        }

    def get_streak(self) -> dict[str, Any]:
        """连续学习天数（按今日历倒推，每日 minutes > 0 算 1 天）。

        Returns:
            {current: int, max: int}
            current: 含今天的连续天数（今天没学也算 0）
            max: 最近 N 月内最长连续天数
        """
        months = 3
        today = date.today()
        start = today - timedelta(days=months * 30)
        daily = self.get_daily_minutes(months)

        # current streak（从今天往回算）
        cur = 0
        c = today
        while c >= start:
            if daily.get(c.isoformat(), 0) > 0:
                cur += 1
                c -= timedelta(days=1)
            else:
                break

        # max streak（全区间扫一遍）
        max_streak = 0
        run = 0
        c = start
        while c <= today:
            if daily.get(c.isoformat(), 0) > 0:
                run += 1
                if run > max_streak:
                    max_streak = run
            else:
                run = 0
            c += timedelta(days=1)

        return {"current": cur, "max": max_streak}

    @staticmethod
    def _minutes_to_level(minutes: int) -> int:
        """学习分钟数 → 0-4 等级映射。

        阈值（每分钟成本约等于一次单词复习）：
          level 0: 0 分钟（无学习）
          level 1: 1-15 分钟（轻量）
          level 2: 16-30 分钟（中等）
          level 3: 31-60 分钟（较多）
          level 4: >60 分钟（极高）
        """
        if minutes <= 0:
            return 0
        if minutes <= 15:
            return 1
        if minutes <= 30:
            return 2
        if minutes <= 60:
            return 3
        return 4


__all__ = ["CalendarService"]