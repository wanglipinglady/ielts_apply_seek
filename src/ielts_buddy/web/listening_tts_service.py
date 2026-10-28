"""ListeningTTSService — LLM TTS 合成音频（v3.7 P2 新增）。

PRD: docs/web-mvp/plans/phase-9-listening-practice.md §5.2

设计:
- 调 MiniMax **T2A (text-to-audio) v2** 端点 ``POST /v1/t2a_v2``
  （v3.7 初版错误地用了 OpenAI 兼容的 ``chat.completions.create`` +
  ``modalities=["text","audio"]``，而 MiniMax 的 chat 端点根本不支持音频模态，
  线上一直报 ``'Chat' object has no attribute 'post'`` / ``unknown model 'speech-01'``）
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


def _decode_hex_audio(hex_str: str) -> Optional[bytes]:
    """把 T2A v2 返回的 hex 编码音频解成 mp3 字节。

    MiniMax t2a_v2 的 ``data.audio`` 是 **hex 字符串**（不是 base64）。
    线上验证：hex 长度 181992 → 90996 字节，开头是 ``ID3\\x04``（标准 mp3 头）。
    """
    if not hex_str:
        return None
    try:
        raw = bytes.fromhex(hex_str)
    except (ValueError, TypeError):
        return None
    if not raw:
        return None
    # 校验 mp3 文件头
    if raw[:3] == b"ID3" or (raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0):
        return raw
    # 头不对也返回（交给上层判断），但要确保不是垃圾
    return raw


# =============================================================
# TTS Service
# =============================================================


class ListeningTTSService:
    """LLM TTS 合成音频服务（MiniMax T2A v2）。

    Args:
        llm_client: 兼容 OpenAI 的 client。None 时走 LLMService 单例。
        model: TTS 模型名(默认 speech-02-hd,MiniMax)
        voice: 声音 ID(默认 English_Trustworth_Man)
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
        self._api_base = web_config.TTS_API_BASE
        self._timeout = web_config.TTS_TIMEOUT_SECONDS

        # 拿到 LLMService 单例（拿 API key + base_url 用）
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

    def _api_key(self) -> str:
        """取 API key（LLMService 持有）。"""
        if self._llm_service is not None:
            key = getattr(self._llm_service, "api_key", "")
            if key:
                return key
        from ielts_buddy.web import config as web_config
        return web_config.LLM_API_KEY

    def synthesize(self, text: str) -> Optional[bytes]:
        """调 MiniMax T2A v2,返回 mp3 字节。失败返回 None。"""
        text = (text or "").strip()
        if not text:
            return None

        api_key = self._api_key()
        if not api_key:
            logger.warning("[tts] 无 LLM API key，跳过合成")
            return None

        last_err = ""
        for attempt in (1, 2):
            try:
                payload = {
                    "model": self._model,
                    "text": text,
                    "stream": False,
                    "voice_setting": {
                        "voice_id": self._voice,
                        "speed": 1,
                        "vol": 1,
                        "pitch": 0,
                    },
                    "audio_setting": {
                        "sample_rate": 32000,
                        "bitrate": 128000,
                        "format": "mp3",
                    },
                }
                resp = self._post_t2a(payload, api_key)
                if resp is None:
                    last_err = "HTTP 请求失败"
                    continue

                data = resp.get("data") or {}
                audio_hex = data.get("audio") or ""
                if not audio_hex:
                    base_resp = resp.get("base_resp") or {}
                    last_err = (
                        f"无音频数据 (status={base_resp.get('status_code')}, "
                        f"msg={base_resp.get('status_msg')})"
                    )
                    continue

                audio_bytes = _decode_hex_audio(audio_hex)
                if audio_bytes:
                    return audio_bytes

                # 兜底：万一某天返回的是 base64 而不是 hex
                fallback = _extract_audio_bytes(audio_hex)
                if fallback:
                    return fallback

                last_err = "音频解码失败"
            except Exception as exc:
                logger.warning("[tts] attempt %d failed: %s", attempt, exc)
                last_err = str(exc)[:200]
        logger.warning("[tts] both attempts failed: %s", last_err)
        return None

    def _post_t2a(self, payload: dict, api_key: str) -> Optional[dict]:
        """POST /v1/t2a_v2，返回解析后的 JSON。

        用 httpx 直连（而不是 openai SDK）——T2A 是 MiniMax 私有端点，
        openai SDK 的 `client.post()` 也能用，但 httpx 更直白且不依赖 SDK 版本。
        """
        import httpx

        url = self._api_base.rstrip("/") + "/t2a_v2"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

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
    "_decode_hex_audio",
]
