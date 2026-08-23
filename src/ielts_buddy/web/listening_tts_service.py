"""ListeningTTSService — LLM TTS 合成音频（v3.7 P2 新增）。

PRD: docs/web-mvp/plans/phase-9-listening-practice.md §5.2

设计:
- 复用现有 LLMService 的 client(MiniMax / OpenAI 兼容)
- 调用 chat.completions.create with audio modalities
  (MiniMax speech-01/speech-02 端点支持)
- 失败 → 重试 1 次 → 仍失败 → 返回 None
- 落盘 mp3 到 ~/.ielts-buddy/listening/{section}/{qid}.mp3

兼容性:
- 没有 LLM client 时返回 None(让上层降级到「原文台词」)
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================
# 基础路径
# =============================================================


def get_listening_root() -> Path:
    """音频根目录:`~/.ielts-buddy/listening/`。"""
    from ielts_buddy.core.config import get_app_dir
    root = Path(get_app_dir()) / "listening"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_section_audio_dir(section: int) -> Path:
    """按 section 隔离:`~/.ielts-buddy/listening/{section}/`"""
    d = get_listening_root() / str(int(section))
    d.mkdir(parents=True, exist_ok=True)
    return d


def audio_path_for(section: int, question_id: int, ext: str = "mp3") -> Path:
    """单题音频标准路径。"""
    return get_section_audio_dir(section) / f"q{int(question_id)}.{ext}"


# =============================================================
# 解析响应中的 mp3 数据
# =============================================================


def _extract_audio_bytes(text: str) -> Optional[bytes]:
    """从 LLM audio 响应文本中提取 mp3 数据。

    不同 provider 返回格式不同:
    - MiniMax speech-01: 返回 base64 编码的 mp3,放在 ```audio``` 围栏里
      或 JSON 字段 audio.data
    - OpenAI gpt-4o-audio: 返回 audio.data (base64)
    - 兜底: 整个 text 是 base64 编码的 mp3
    """
    t = (text or "").strip()
    if not t:
        return None

    # 1. ```audio ... ``` 围栏
    fence = re.search(r"```(?:audio|base64)?\s*\n([A-Za-z0-9+/=\s]+)\n```",
                     t, re.IGNORECASE)
    if fence:
        import base64
        try:
            return base64.b64decode(fence.group(1))
        except Exception:
            pass

    # 2. JSON 字段 audio.data / audio_url(暂不下载 url,只取 base64)
    try:
        parsed = json.loads(t)
        if isinstance(parsed, dict):
            for key in ("data", "audio", "audio_data", "mp3"):
                if parsed.get(key):
                    import base64
                    try:
                        return base64.b64decode(parsed[key])
                    except Exception:
                        continue
            # 嵌套 audio.data
            nested = parsed.get("audio")
            if isinstance(nested, dict):
                for key in ("data", "audio"):
                    if nested.get(key):
                        import base64
                        try:
                            return base64.b64decode(nested[key])
                        except Exception:
                            continue
    except json.JSONDecodeError:
        pass

    # 3. 兜底:整段是 base64
    import base64
    try:
        decoded = base64.b64decode(t)
        # 简单验证 mp3 文件头(前 3 字节为 "ID3" 或 0xFF 0xFB/0xFA/0xF3/0xF2)
        if decoded[:3] == b"ID3" or (decoded[0] == 0xFF and (decoded[1] & 0xE0) == 0xE0):
            return decoded
    except Exception:
        pass

    return None


# =============================================================
# TTS Service
# =============================================================


class ListeningTTSService:
    """LLM TTS 合成音频服务。

    Args:
        llm_client: 兼容 OpenAI 的 client。None 时走 LLMService 单例。
        model: TTS 模型名(默认 speech-01,MiniMax)
        voice: 声音 ID(默认 male-en-1)
    """

    def __init__(
        self,
        llm_client: Any = None,
        model: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> None:
        from ielts_buddy.web import config as web_config

        self._llm_client = llm_client
        self._model = model or web_config.TTS_MODEL
        self._voice = voice or web_config.TTS_VOICE

        # 拿到 LLMService 单例
        try:
            from ielts_buddy.web.llm_service import get_llm_service
            self._llm_service = get_llm_service()
        except Exception as exc:
            logger.warning("[tts] LLMService init failed: %s", exc)
            self._llm_service = None

    def is_available(self) -> bool:
        client = self._get_client()
        return client is not None

    def _get_client(self) -> Any:
        if self._llm_client is not None:
            return self._llm_client
        if self._llm_service is not None:
            return self._llm_service._ensure_client()
        return None

    def synthesize(self, text: str) -> Optional[bytes]:
        """调 LLM TTS,返回 mp3 字节。失败返回 None。"""
        client = self._get_client()
        if client is None:
            return None
        text = (text or "").strip()
        if not text:
            return None

        last_text = ""
        for attempt in (1, 2):
            try:
                resp = client.chat.post(
                    model=self._model,
                    modalities=["text", "audio"],
                    audio={"voice": self._voice, "format": "mp3"},
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                "Please read the following IELTS listening "
                                "script naturally as an examiner. "
                                "Output ONLY the audio.\n\n" + text
                            ),
                        },
                    ],
                )
                # OpenAI / MiniMax 兼容返回:
                # resp.choices[0].message.audio.data (base64) 或 .content
                choice = resp.choices[0]
                msg = choice.message

                # 1. 直接 audio.data 字段
                audio_obj = getattr(msg, "audio", None)
                if audio_obj is not None:
                    data = getattr(audio_obj, "data", None)
                    if data:
                        import base64
                        try:
                            return base64.b64decode(data)
                        except Exception:
                            pass

                # 2. content 是 base64 字符串
                content = getattr(msg, "content", None)
                if isinstance(content, str) and content.strip():
                    decoded = _extract_audio_bytes(content)
                    if decoded:
                        return decoded

                # 3. content 可能是 list(Multi-modal content)
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "audio" or "audio" in part:
                                a = part.get("audio") or part
                                data = a.get("data") if isinstance(a, dict) else None
                                if data:
                                    import base64
                                    try:
                                        return base64.b64decode(data)
                                    except Exception:
                                        pass
                last_text = str(content)[:200] if content else "(empty)"
            except Exception as exc:
                logger.warning(
                    "[tts] attempt %d failed: %s", attempt, exc
                )
                last_text = str(exc)[:200]
        logger.warning("[tts] both attempts failed: %s", last_text)
        return None

    def synthesize_to_file(
        self,
        text: str,
        section: int,
        question_id: int,
    ) -> Optional[Path]:
        """synthesize + 落盘 mp3。失败返回 None。

        路径:`~/.ielts-buddy/listening/{section}/q{question_id}.mp3`
        """
        audio_bytes = self.synthesize(text)
        if not audio_bytes:
            return None
        target = audio_path_for(section, question_id)
        try:
            target.write_bytes(audio_bytes)
            return target
        except Exception as exc:
            logger.warning(
                "[tts] write failed for %s: %s", target, exc
            )
            return None


@lru_cache(maxsize=1)
def get_listening_tts_service() -> ListeningTTSService:
    """获取 TTS 服务单例。"""
    return ListeningTTSService()


__all__ = [
    "ListeningTTSService",
    "get_listening_tts_service",
    "get_listening_root",
    "get_section_audio_dir",
    "audio_path_for",
    "_extract_audio_bytes",
]