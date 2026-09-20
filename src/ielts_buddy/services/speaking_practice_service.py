"""口语对练业务服务（v3.7 P1 新增）。

PRD: docs/web-mvp/plans/phase-8-speaking-practice.md §5

业务层封装 calling chain:
  1) 抽题（来自现有 SpeakingService.get_topics / get_random_topic）
  2) 落盘录音到 ~/.ielts-buddy/audio/{user_id}/{session_id}.webm
  3) 调 WhisperService.transcribe 转写
  4) 调 SpeakingGradeService.grade 评分（mock / LLM）
  5) 回收错词:LearningRepository.record_speaking_error
     + PersonalVocabRepository.add_mistake
  6) 落 speaking_practice_records 完整记录
  7) 7 天自动清理(web 启动期调用一次)

设计:
- 同步实现,web 端走 asyncio.to_thread 转异步
- 完全 traceable:任何 step 失败 → log warning,UI 仍收到部分结果
  (如转写失败 → transcript="" 但评分继续走 mock)
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from ielts_buddy.core.config import get_app_dir
from ielts_buddy.core.repository import (
    LearningRepository,
    PersonalVocabRepository,
    SpeakingPracticeRepository,
)
from ielts_buddy.services.personal_vocab_service import PersonalVocabService
from ielts_buddy.services.speaking_service import SpeakingService
from ielts_buddy.web.whisper_service import WhisperService, TranscriptResult

logger = logging.getLogger(__name__)


_PART_LABELS = {
    1: "Part 1 (日常话题)",
    2: "Part 2 (个人陈述)",
    3: "Part 3 (深入讨论)",
}


@dataclass
class PracticeStartResult:
    """抽题的响应(浏览器会用来展示题目 + 启动录音 UI)。"""
    session_id: str
    part: int
    part_label: str
    topic_id: int
    topic: str
    question: str
    vocab: list[str]
    sample_answer: str
    tips: str


@dataclass
class SubmitResult:
    """完整 submit 响应(浏览器一次性拿到全部结果)。"""
    record_id: int
    session_id: str
    transcript: str
    tokens: list[dict] = field(default_factory=list)
    scores: dict = field(default_factory=lambda: {
        "fluency": 6.0, "lexical": 6.0, "grammar": 6.0,
        "pronunciation": 6.0, "overall_band": 6.0,
    })
    word_errors: list[dict] = field(default_factory=list)
    grammar_errors: list[dict] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    whisper_fallback: bool = False
    score_fallback: bool = False


def get_audio_root() -> Path:
    """录音文件根目录:`~/.ielts-buddy/audio/`。"""
    root = Path(get_app_dir()) / "audio"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_user_audio_dir(user_id: int) -> Path:
    """用户隔离的录音目录:`~/.ielts-buddy/audio/{user_id}/`。"""
    d = get_audio_root() / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


class SpeakingPracticeService:
    """口语对练业务服务。绑定业务容器 + 用户 ID。"""

    def __init__(
        self,
        container: Any,
        user_id: int,
        whisper: Optional[WhisperService] = None,
    ) -> None:
        self._container = container
        self._user_id = int(user_id)
        self._whisper = whisper  # 延迟注入,默认走 get_whisper_service()
        # Lazy import:避免循环依赖
        from ielts_buddy.web.speaking_grade_service import SpeakingGradeService
        self._grade = SpeakingGradeService()

    # =============================================================
    # 抽题 (无需落盘,纯查 SpeakingService)
    # =============================================================

    def start_practice(self, part: Optional[int] = None) -> Optional[PracticeStartResult]:
        """抽一道口语题,生成新 session_id 返回。

        session_id 用 UUIDv4 保证全局唯一;浏览器缓存这个 id,
        提交录音时带回服务端。
        """
        topic_svc = SpeakingService()
        all_topics = topic_svc.get_topics()
        topic = topic_svc.get_random_topic(part)
        if topic is None or not all_topics:
            return None

        topic_id = all_topics.index(topic) + 1  # 1-based
        part_int = topic["part"]
        return PracticeStartResult(
            session_id=str(uuid.uuid4()),
            part=part_int,
            part_label=_PART_LABELS.get(part_int, f"Part {part_int}"),
            topic_id=topic_id,
            topic=topic["topic"],
            question=topic["questions"][0]
                if topic["questions"] else topic["topic"],
            vocab=topic.get("vocab", []),
            sample_answer=topic.get("sample_answer", ""),
            tips=topic.get("tips", ""),
        )

    # =============================================================
    # 提交录音: 完整端到端管线
    # =============================================================

    def submit(
        self,
        session_id: str,
        part: int,
        topic_id: int,
        topic_name: str,
        question: str,
        audio_bytes: bytes,
        audio_mime: str,
        actual_duration_sec: float = 0.0,
        vocab_hints: Optional[list[str]] = None,
        sample_answer: Optional[str] = None,
    ) -> SubmitResult:
        """完整流水线。

        Args:
            session_id: start_practice 返回的 UUID。
            part / topic_id / topic_name / question: 用于落库,前端从
                start_practice 拿到,提交时带回。
            audio_bytes: 浏览器采集的 webm/opus/mp4 二进制。
            audio_mime: 浏览器原始 MIME。
            actual_duration_sec: 浏览器记录的秒数,做兜底校验。
            vocab_hints: 词汇提示,主要用于评分 prompt。
            sample_answer: 参考答案,评分 prompt 用。

        Returns:
            SubmitResult 含 record_id + 转写 + 评分 + 错词 + 改进建议。
        """
        sp_repo: SpeakingPracticeRepository = self._container.speaking_practice
        learning: LearningRepository = self._container.learning
        personal_vocab: PersonalVocabRepository = self._container.personal_vocab

        # 1) 落盘
        audio_path = self._save_audio(session_id, audio_bytes, audio_mime)
        # 2) 建/更新 record
        #    session_id 唯一约束:同一 session 重提交（重新录制）必须复用现有 record,
        #    否则 UNIQUE 冲突会 500。
        existing = sp_repo.get_practice_by_session(
            user_id=self._user_id, session_id=session_id
        )
        if existing is not None:
            # 重录场景:覆盖 audio + 清空旧转写/评分
            sp_repo.update_practice_audio(
                user_id=self._user_id,
                session_id=session_id,
                audio_path=str(audio_path) if audio_path else None,
                audio_duration_sec=float(actual_duration_sec),
                audio_mime=audio_mime or "audio/webm",
            )
            record_id = int(existing["id"])
        else:
            # 首次提交:建初稿,后面 update
            record_id = sp_repo.create_practice_record(
                user_id=self._user_id,
                session_id=session_id,
                part=int(part),
                topic_id=topic_id,
                topic_name=topic_name,
                question=question,
                audio_path=str(audio_path) if audio_path else None,
                audio_duration_sec=float(actual_duration_sec),
                audio_mime=audio_mime or "audio/webm",
            )

        # 3) 转写
        whisper = self._whisper or _get_whisper()
        if audio_path and whisper and whisper.is_available():
            transcript_result = whisper.transcribe(str(audio_path))
            # 回填 transcript
            sp_repo.update_practice_transcript(
                user_id=self._user_id,
                session_id=session_id,
                transcript=transcript_result.text,
                transcript_tokens=transcript_result.tokens,
                whisper_model=transcript_result.model_id,
                used_core_ml=transcript_result.used_core_ml,
            )
        else:
            # whisper 不可用或音频落盘失败 → mock
            transcript_result = TranscriptResult(text="", tokens=[],
                                                fallback=True, model_id="")

        # 4) 评分 (用真实 transcript 评分,即使 transcript 是空也走 mock)
        #    sample_answer / vocab_hints 给评分 prompt 用
        grade_result = self._grade.grade(
            part=part,
            topic=topic_name,
            question=question,
            transcript=transcript_result.text or "(no speech detected)",
            sample_answer=sample_answer,
            vocab_hints=vocab_hints or [],
        )

        # 5) 错词回收(对 LLM 给的 word_errors 过滤 + 回填)
        recovered = self._recover_word_errors(
            word_errors=grade_result["word_errors"],
            learning=learning,
            personal_vocab=personal_vocab,
        )
        grade_result["word_errors"] = recovered["word_errors"]

        # 6) 回填评分
        sp_repo.update_practice_score(
            user_id=self._user_id,
            session_id=session_id,
            scores=grade_result["scores"],
            word_errors=grade_result["word_errors"],
            grammar_errors=grade_result["grammar_errors"],
            highlights=grade_result["highlights"],
            suggestions=grade_result["suggestions"],
            score_fallback=grade_result["score_fallback"],
        )

        return SubmitResult(
            record_id=record_id,
            session_id=session_id,
            transcript=transcript_result.text,
            tokens=transcript_result.tokens,
            scores=grade_result["scores"],
            word_errors=grade_result["word_errors"],
            grammar_errors=grade_result["grammar_errors"],
            highlights=grade_result["highlights"],
            suggestions=grade_result["suggestions"],
            whisper_fallback=transcript_result.fallback,
            score_fallback=grade_result["score_fallback"],
        )

    # =============================================================
    # 错词回收:过滤 + 调 learning.record_speaking_error + 个人词库
    # =============================================================

    def _recover_word_errors(
        self,
        word_errors: list[dict],
        learning: LearningRepository,
        personal_vocab: PersonalVocabRepository,
    ) -> dict[str, Any]:
        """过滤 LLM 给的 word_errors + 落库。

        过滤规则(PRD §5.4.3):
        - correction 优先;为空则取 original
        - 只接受字母 + 短横杠组成的"单词";跳过非单词(句子、标点、中文)
        """
        kept: list[dict] = []
        for we in word_errors or []:
            original = (we.get("original") or "").strip()
            correction = (we.get("correction") or "").strip()
            context = (we.get("context") or "").strip()

            target_word = correction or original
            if not _looks_like_word(target_word):
                continue

            # 归一化
            target_word_norm = target_word.lower()
            # 去 learning_records
            try:
                learning.record_speaking_error(
                    user_id=self._user_id, word=target_word_norm, source="speaking"
                )
            except Exception as exc:
                logger.warning("[speaking] record_speaking_error failed: %s", exc)

            # 去 personal_vocab.mistakes 分类
            try:
                from ielts_buddy.core.models import PersonalWord
                pw = PersonalWord(
                    word=target_word_norm,
                    meaning=correction or original,
                    band=5,
                )
                personal_vocab.add_mistake(self._user_id, pw, source="speaking")
            except Exception as exc:
                logger.warning(
                    "[speaking] personal_vocab.add_mistake failed: %s", exc
                )

            # 更新 we 的 returned fields
            we = {
                "original": original,
                "correction": correction,
                "context": context,
                "word": target_word_norm,
            }
            kept.append(we)

        return {"word_errors": kept}

    # =============================================================
    # 历史回看
    # =============================================================

    def list_history(
        self,
        part: Optional[int] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict], int]:
        sp_repo = self._container.speaking_practice
        return sp_repo.list_practice_history(
            user_id=self._user_id, part=part, page=page, size=size
        )

    def get_record(self, record_id: int) -> Optional[dict]:
        sp_repo = self._container.speaking_practice
        return sp_repo.get_practice_record(self._user_id, record_id)

    def get_audio_path(self, session_id: str) -> Optional[Path]:
        """用 session_id 找文件路径(限自己 user_id)。"""
        user_dir = get_user_audio_dir(self._user_id)
        candidate = user_dir / f"{session_id}.webm"
        if candidate.exists():
            return candidate
        # 兼容老格式 mp4 / wav
        for ext in (".mp4", ".wav", ".mp3", ".ogg"):
            c = user_dir / f"{session_id}{ext}"
            if c.exists():
                return c
        return None

    # =============================================================
    # 落盘 + 清理
    # =============================================================

    def _save_audio(
        self, session_id: str, audio_bytes: bytes, audio_mime: str
    ) -> Optional[Path]:
        """按 mime 推断扩展名,把二进制落到用户隔离目录。"""
        if not audio_bytes:
            return None
        user_dir = get_user_audio_dir(self._user_id)
        ext = _mime_to_ext(audio_mime)
        target = user_dir / f"{session_id}{ext}"
        try:
            target.write_bytes(audio_bytes)
            return target
        except Exception as exc:
            logger.warning("[speaking] save_audio failed: %s", exc)
            return None

    def purge_expired_audio(self, retention_days: int = 7) -> dict[str, int]:
        """清理 retention_days 天前的录音物理文件,同时把 DB 中 audio_path 置 NULL。

        Returns:
            {
                "files_deleted": int,
                "records_audio_nulled": int,
                "rows_deleted": int,
            }
        """
        sp_repo = self._container.speaking_practice
        items, _ = sp_repo.list_practice_history(
            user_id=self._user_id, page=1, size=10000
        )

        cutoff = datetime.now() - timedelta(days=retention_days)
        files_deleted = 0
        records_nulled = 0

        for item in items:
            try:
                created = datetime.fromisoformat(item["created_at"])
            except Exception:
                continue
            if created >= cutoff:
                continue
            session_id = item["session_id"]
            audio_path = self.get_audio_path(session_id)
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                    files_deleted += 1
                except Exception:
                    pass
            if sp_repo.set_audio_null(self._user_id, session_id):
                records_nulled += 1

        return {
            "files_deleted": files_deleted,
            "records_audio_nulled": records_nulled,
            "rows_deleted": 0,
        }


# =============================================================
# 模块级入口:跨用户清理(供 web 启动期 lifespan 调用)
# =============================================================


def purge_all_expired_audio(
    container: Any,
    retention_days: int = 7,
) -> dict[str, int]:
    """跨所有用户的过期录音清理入口。

    Args:
        container: 业务容器(拿到 .speaking_practice)
        retention_days: 保留天数(默认 7)

    Returns:
        {"files_deleted", "records_audio_nulled", "users_touched"}
    """
    sp_repo = container.speaking_practice
    try:
        expired = sp_repo.list_expired_audio_paths(retention_days)
    except Exception as exc:
        logger.warning("[speaking] list_expired_audio_paths failed: %s", exc)
        return {"files_deleted": 0, "records_audio_nulled": 0,
                "users_touched": 0}

    files_deleted = 0
    records_nulled = 0
    users_touched: set[int] = set()

    for user_id, session_id, audio_path in expired:
        users_touched.add(user_id)
        if audio_path:
            p = Path(audio_path)
            if p.exists():
                try:
                    p.unlink()
                    files_deleted += 1
                except Exception:
                    pass
        try:
            if sp_repo.set_audio_null(user_id, session_id):
                records_nulled += 1
        except Exception:
            pass

    return {
        "files_deleted": files_deleted,
        "records_audio_nulled": records_nulled,
        "users_touched": len(users_touched),
    }

# =============================================================
# Helpers
# =============================================================


def _looks_like_word(s: str) -> bool:
    """判断 s 是否像"单词"。只接受字母 + 短横杠 + 撇号(+空格分词可考虑)。

    拒绝:
      - 空字符串
      - 含中文 / 全角字符 / 纯数字 / 句子级标点(逗号、句号、感叹号)
    """
    s = (s or "").strip()
    if not s:
        return False
    # 长度:1-40 字符(足够长也拒绝,认为不是单词)
    if len(s) > 40:
        return False
    # 必须含字母(排除纯数字/纯标点)
    if not any(c.isascii() and c.isalpha() for c in s):
        return False
    # 不允许 ASCII 之外的字符
    try:
        s.encode("ascii")
    except UnicodeEncodeError:
        return False
    # 拒绝纯标点串
    return any(c.isalpha() for c in s)


def _mime_to_ext(mime: str) -> str:
    m = (mime or "").lower()
    if "webm" in m:
        return ".webm"
    if "ogg" in m:
        return ".ogg"
    if "mp4" in m:
        return ".mp4"
    if "wav" in m:
        return ".wav"
    if "mpeg" in m or "mp3" in m:
        return ".mp3"
    return ".webm"  # 默认 fallback


def _get_whisper() -> Optional[WhisperService]:
    """延迟拿 WhisperService 单例(避免 import 时的循环)。"""
    try:
        from ielts_buddy.web.whisper_service import get_whisper_service
        svc = get_whisper_service()
        if svc.is_available():
            return svc
    except Exception as exc:
        logger.warning("[speaking] whisper init failed: %s", exc)
    return None


__all__ = [
    "SpeakingPracticeService",
    "PracticeStartResult",
    "SubmitResult",
    "get_audio_root",
    "get_user_audio_dir",
    "purge_all_expired_audio",
]
