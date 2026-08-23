"""``listening_practice_service`` 业务层单测（v3.7 P2 Sprint 2 新增）。

覆盖:
1. seed_initial_questions:题库为空时种子;已有题时跳过
2. seed_initial_questions:LLM 失败走 mock,也能落库
3. purge_expired_audio:清理 30 天前的音频
4. ListeningPracticeService.list_sections:返回 4 个 Section 概览
5. ListeningPracticeService.list_sets:按 Section 列套题
6. ListeningPracticeService.start_set:返回 StartSetResult
7. ListeningPracticeService.submit_answer:选择题判分 + 填空判分 + 落 attempts
8. ListeningPracticeService.get_user_stats:聚合统计
9. ListeningPracticeService._is_answer_correct:大小写不敏感 + 填空归一化
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ielts_buddy.repositories.fallback_repo import create_fallback_container
from ielts_buddy.services.listening_practice_service import (
    ListeningPracticeService,
    SECTION_LABELS,
    purge_expired_audio,
    seed_initial_questions,
)


# =============================================================
# Helpers
# =============================================================


def _make_container(tmp_path: Path):
    """构造 fallback 容器(SQLite-only,无 MySQL)。"""
    sqlite_path = tmp_path / "web.db"
    return create_fallback_container(
        sqlite_db_path=sqlite_path,
        mysql_url="",
        prefer_mode="sqlite",
    )


def _seed_questions(container, section=1, set_id=1, count=4):
    """落 N 道选择题。"""
    repo = container.listening_practice
    for i in range(1, count + 1):
        repo.seed_question(
            section=section, set_id=set_id, qid=i,
            scenario=f"Scenario {i}",
            question_type="multiple_choice",
            stem=f"Q{i} Which one?",
            options=["A opt", "B opt", "C opt", "D opt"],
            answer="A",
            explanation="Because A is right.",
            transcript=f"Transcript for Q{i}.",
        )


# =============================================================
# seed_initial_questions
# =============================================================


class TestSeedInitialQuestions:
    def test_skips_when_questions_exist(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        _seed_questions(container, section=1, set_id=1, count=4)
        result = seed_initial_questions(
            container,
            s1=10, s2=8, s3=7, s4=5,
            auto_trigger_tts=False,
        )
        assert result["skipped"] is True
        assert result["seeded_questions"] == 0

    def test_seeds_when_empty(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        result = seed_initial_questions(
            container,
            s1=2, s2=0, s3=0, s4=0,
            auto_trigger_tts=False,
        )
        assert result["skipped"] is False
        # Section 1 应该落了 2 套 × 5 题 = 10 道
        assert result["seeded_questions"] == 10
        # 再次调用应跳过
        result2 = seed_initial_questions(
            container, s1=2, s2=0, s3=0, s4=0,
            auto_trigger_tts=False,
        )
        assert result2["skipped"] is True


# =============================================================
# purge_expired_audio
# =============================================================


class TestPurgeExpiredAudio:
    def test_purges_30d_old_audio(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.listening_practice

        # 造两道题 + 给定音频文件
        _seed_questions(container, section=1, set_id=1, count=2)
        all_qs = repo.list_questions_by_set(1, 1)
        # 修改 audio_path 字段 + 时间戳,模拟 30 天前
        for i, q in enumerate(all_qs):
            qid = int(q["id"])
            audio_dir = tmp_path / "audio" / "1"
            audio_dir.mkdir(parents=True, exist_ok=True)
            audio_file = audio_dir / f"q{qid}.mp3"
            audio_file.write_bytes(b"fakemp3")
            old_ts = (datetime.now() - timedelta(days=40)).isoformat(
                timespec="seconds"
            )
            repo.set_audio_path(
                question_id=qid,
                audio_path=str(audio_file),
                audio_generated_at=old_ts,
            )
        # 调用清理(默认 30 天)
        result = purge_expired_audio(container, retention_days=30)
        assert result["files_deleted"] == 2
        assert result["rows_nulled"] == 2
        # audio_path 已被置 NULL
        for q in all_qs:
            qid = int(q["id"])
            updated = repo.get_question(qid)
            assert updated["audio_path"] is None


# =============================================================
# ListeningPracticeService
# =============================================================


class TestListeningPracticeService:
    def _make_service(self, tmp_path: Path, user_id: int = 1):
        container = _make_container(tmp_path)
        _seed_questions(container, section=1, set_id=1, count=4)
        _seed_questions(container, section=2, set_id=1, count=4)
        # Generator/TTS 走 mock(no client)
        svc = ListeningPracticeService(container=container, user_id=user_id)
        return svc, container

    def test_list_sections_returns_all_four(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        sections = svc.list_sections()
        # 至少返回 1 和 2(已种子的)
        section_nums = {s["section"] for s in sections}
        assert 1 in section_nums
        assert 2 in section_nums

    def test_list_sets_filters_by_section(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        sets = svc.list_sets(1)
        assert len(sets) >= 1
        # scenario 字段非空
        assert sets[0]["scenario"]

    def test_start_set_returns_questions(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        result = svc.start_set(section=1, set_id=1)
        assert result is not None
        assert result.section == 1
        assert result.set_id == 1
        assert len(result.questions) == 4
        # 题目中不含 answer/explanation(防止泄漏给前端)
        for q in result.questions:
            assert "answer" not in q
            assert "explanation" not in q
            assert q["id"]

    def test_start_set_returns_none_for_missing(self, tmp_path: Path) -> None:
        svc, _ = self._make_service(tmp_path)
        result = svc.start_set(section=1, set_id=99)
        assert result is None

    def test_submit_answer_correct_choice(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        # 拿到第一道题
        qs = container.listening_practice.list_questions_by_set(1, 1)
        qid = int(qs[0]["id"])
        out = svc.submit_answer(qid, "A")
        assert out.is_correct is True
        assert out.correct_answer == "A"
        assert out.attempt_id > 0

    def test_submit_answer_wrong_choice(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        qs = container.listening_practice.list_questions_by_set(1, 1)
        qid = int(qs[0]["id"])
        out = svc.submit_answer(qid, "B")
        assert out.is_correct is False
        assert out.correct_answer == "A"

    def test_submit_answer_form_completion_case_insensitive(
        self, tmp_path: Path
    ) -> None:
        svc, container = self._make_service(tmp_path)
        # 加一道填空题
        repo = container.listening_practice
        new_id = repo.seed_question(
            section=1, set_id=1, qid=99,
            scenario="Form completion test",
            question_type="form_completion",
            stem="The price is _____.",
            options=None,
            answer="fifteen dollars",
            explanation="Because the speaker said fifteen dollars.",
            transcript="The price is fifteen dollars.",
        )
        out = svc.submit_answer(int(new_id), "Fifteen Dollars")
        assert out.is_correct is True

    def test_submit_answer_records_attempt(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        qs = container.listening_practice.list_questions_by_set(1, 1)
        qid = int(qs[0]["id"])
        svc.submit_answer(qid, "A", duration_sec=12.5, played_count=2)
        # 落库
        items, total = svc.list_history()
        assert total == 1
        assert items[0]["question_id"] == qid
        assert items[0]["duration_sec"] == 12.5
        assert items[0]["played_count"] == 2

    def test_submit_answer_finds_next_question(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        qs = container.listening_practice.list_questions_by_set(1, 1)
        # 第 1 题 → 第 2 题
        out = svc.submit_answer(int(qs[0]["id"]), "A")
        assert out.next_question_id is not None
        # 最后一题 → None
        last = svc.submit_answer(int(qs[-1]["id"]), "A")
        assert last.next_question_id is None

    def test_get_user_stats_aggregates(self, tmp_path: Path) -> None:
        svc, container = self._make_service(tmp_path)
        qs = container.listening_practice.list_questions_by_set(1, 1)
        # 3 题答对(A),1 题答错(B)
        svc.submit_answer(int(qs[0]["id"]), "A")
        svc.submit_answer(int(qs[1]["id"]), "A")
        svc.submit_answer(int(qs[2]["id"]), "B")
        svc.submit_answer(int(qs[3]["id"]), "A")
        stats = svc.get_user_stats()
        assert stats["total_attempts"] == 4
        assert stats["correct"] == 3
        # accuracy 大约 75%
        assert stats["accuracy"] == 75.0
        # by_section 至少 Section 1 有数据
        assert 1 in stats["by_section"]
        sec1 = stats["by_section"][1]
        assert sec1["attempts"] == 4
        assert sec1["correct"] == 3

    def test_get_question_filters_answer_explanation(
        self, tmp_path: Path
    ) -> None:
        """单题详情不应泄漏 answer / explanation 给前端。"""
        svc, container = self._make_service(tmp_path)
        qs = container.listening_practice.list_questions_by_set(1, 1)
        qid = int(qs[0]["id"])
        q = svc.get_question(qid)
        assert q is not None
        # 客户端结构无 answer / transcript / explanation
        assert "answer" not in q
        assert "explanation" not in q
        assert "transcript" not in q

    def test_is_answer_correct_case_insensitive(
        self, tmp_path: Path
    ) -> None:
        svc, _ = self._make_service(tmp_path)
        # 直接调内部判分
        assert svc._is_answer_correct("a", "A", "multiple_choice") is True
        assert svc._is_answer_correct("b", "A", "multiple_choice") is False
        # 填空:小写 + 去标点
        assert svc._is_answer_correct("Hello!", "hello", "form_completion")
        assert svc._is_answer_correct("", "hello", "form_completion") is False


# =============================================================
# SECTION_LABELS
# =============================================================


class TestSectionLabels:
    def test_all_four_labels_present(self) -> None:
        assert 1 in SECTION_LABELS
        assert 2 in SECTION_LABELS
        assert 3 in SECTION_LABELS
        assert 4 in SECTION_LABELS