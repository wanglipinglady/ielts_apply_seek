"""``speaking_practice_service`` 业务层单测（v3.7 P1 Sprint 4 新增）。

覆盖:
1. purge_all_expired_audio 跨用户清理过期录音
2. list_expired_audio_paths SQL 返回正确
3. retention_days=0 边界(清理所有)
4. 物理文件不存在时不抛异常
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ielts_buddy.repositories.fallback_repo import create_fallback_container
from ielts_buddy.services.speaking_practice_service import (
    purge_all_expired_audio,
)


def _make_container(tmp_path: Path):
    """构造 fallback 容器(SQLite-only,无 MySQL)。"""
    sqlite_path = tmp_path / "web.db"
    return create_fallback_container(
        sqlite_db_path=sqlite_path,
        mysql_url="",
        prefer_mode="sqlite",
    )


def _seed_record(
    container, user_id: int, session_id: str,
    audio_path: str | None, days_ago: int,
) -> None:
    """造一条 speaking_practice_records 行(任意 created_at)。"""
    sp = container.speaking_practice
    created = (datetime.now() - timedelta(days=days_ago)).isoformat(
        timespec="seconds"
    )
    sp._conn.execute(
        """INSERT INTO speaking_practice_records
           (user_id, session_id, part, topic_id, topic_name, question,
            audio_path, audio_duration_sec, audio_mime, transcript,
            llm_scores, created_at)
           VALUES (?, ?, 1, 1, 'Topic', 'Q?',
                   ?, 12, 'audio/webm', '',
                   '{}', ?)""",
        (user_id, session_id, audio_path, created),
    )
    sp._conn.commit()


def test_purge_all_expired_audio_deletes_old_files(
    tmp_path: Path, monkeypatch
) -> None:
    """7 天前的录音被物理删除 + DB 标 NULL。"""
    container = _make_container(tmp_path)
    sp = container.speaking_practice

    # 造一个真实的 webm 文件在 audio 目录
    audio_dir = tmp_path / "audio" / "100"
    audio_dir.mkdir(parents=True)
    old_file = audio_dir / "old-sid-1.webm"
    old_file.write_bytes(b"fakewebm")
    recent_file = audio_dir / "recent-sid.webm"
    recent_file.write_bytes(b"fakewebm2")

    # 10 天前的记录(应该清)
    _seed_record(
        container, user_id=100, session_id="old-sid-1",
        audio_path=str(old_file), days_ago=10,
    )
    # 2 天前的记录(保留)
    _seed_record(
        container, user_id=100, session_id="recent-sid",
        audio_path=str(recent_file), days_ago=2,
    )

    # mock WhisperService(避免 import 时找不到 ffmpeg)
    monkeypatch.setattr(
        "ielts_buddy.services.speaking_practice_service._get_whisper",
        lambda: None,
    )

    result = purge_all_expired_audio(container, retention_days=7)

    assert result["files_deleted"] == 1
    assert result["records_audio_nulled"] == 1
    assert result["users_touched"] == 1

    # 旧文件已删
    assert not old_file.exists()
    # 新文件还在
    assert recent_file.exists()

    # DB 旧记录 audio_path 已被 NULL 化
    row = sp._conn.execute(
        "SELECT audio_path FROM speaking_practice_records WHERE session_id=?",
        ("old-sid-1",),
    ).fetchone()
    assert row["audio_path"] is None

    # 新记录 audio_path 还在
    row = sp._conn.execute(
        "SELECT audio_path FROM speaking_practice_records WHERE session_id=?",
        ("recent-sid",),
    ).fetchone()
    assert row["audio_path"] == str(recent_file)


def test_purge_handles_missing_files_gracefully(
    tmp_path: Path, monkeypatch
) -> None:
    """DB 有路径但文件已被外部删除 → 不抛异常,DB 仍标 NULL。"""
    container = _make_container(tmp_path)
    sp = container.speaking_practice

    _seed_record(
        container, user_id=200, session_id="ghost-sid",
        audio_path="/nonexistent/path/ghost.webm",  # 文件不存在
        days_ago=10,
    )

    monkeypatch.setattr(
        "ielts_buddy.services.speaking_practice_service._get_whisper",
        lambda: None,
    )

    result = purge_all_expired_audio(container, retention_days=7)
    assert result["files_deleted"] == 0  # 文件本来就不存在
    assert result["records_audio_nulled"] == 1  # DB 仍然清掉悬空路径
    assert result["users_touched"] == 1


def test_purge_retention_zero_clears_all(
    tmp_path: Path, monkeypatch
) -> None:
    """retention_days=0 → 清掉所有 created_at < now 的记录(含 1 秒前的)。"""
    container = _make_container(tmp_path)
    audio_dir = tmp_path / "audio" / "300"
    audio_dir.mkdir(parents=True)
    f = audio_dir / "x.webm"
    f.write_bytes(b"x")

    _seed_record(
        container, user_id=300, session_id="x",
        audio_path=str(f), days_ago=0,
    )
    # 但手动把 created_at 改到 5 秒前(确保严格小于 now)
    sp = container.speaking_practice
    five_sec_ago = (datetime.now() - timedelta(seconds=5)).isoformat(
        timespec="seconds"
    )
    sp._conn.execute(
        "UPDATE speaking_practice_records SET created_at=? WHERE session_id=?",
        (five_sec_ago, "x"),
    )
    sp._conn.commit()

    monkeypatch.setattr(
        "ielts_buddy.services.speaking_practice_service._get_whisper",
        lambda: None,
    )

    result = purge_all_expired_audio(container, retention_days=0)
    assert result["files_deleted"] == 1
    assert result["records_audio_nulled"] == 1


def test_purge_empty_returns_zero(
    tmp_path: Path, monkeypatch
) -> None:
    """没有任何记录 → 返回零,不抛异常。"""
    container = _make_container(tmp_path)

    monkeypatch.setattr(
        "ielts_buddy.services.speaking_practice_service._get_whisper",
        lambda: None,
    )

    result = purge_all_expired_audio(container, retention_days=7)
    assert result == {"files_deleted": 0, "records_audio_nulled": 0,
                      "users_touched": 0}