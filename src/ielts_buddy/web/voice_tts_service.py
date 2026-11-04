"""语音训练工坊 TTS 服务（v3.9 W11）。

PRD: docs/web-mvp/plans/phase-11-voice-training-prd.md §5.2

回退链（设计文档 §5.2）：
    edge-tts（免费微软神经音，主路径）
      → MiniMax T2A v2（复用 listening_tts_service.ListeningTTSService）
      → TTSServiceUnavailable

缓存：key = sha256(text + voice + speed)，命中不重复合成。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 音色白名单（edge-tts 神经音）
EDGE_VOICES = {
    "en-US-AriaNeural",    # 美音女声（默认，教学腔清晰）
    "en-US-GuyNeural",     # 美音男声
    "en-GB-SoniaNeural",   # 英音女声（对齐剑桥/新概念英音素材）
}


class TTSServiceUnavailable(Exception):
    """edge-tts 与 MiniMax 均失败时抛出。"""


@dataclass
class SynthResult:
    path: Path          # mp3 文件绝对路径
    provider: str       # edge | minimax
    cached: bool        # 是否命中缓存


def get_voice_root() -> Path:
    """语音训练文件根目录: ``~/.ielts-buddy/voice/``。"""
    from ielts_buddy.core.config import get_app_dir
    root = Path(get_app_dir()) / "voice"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_tts_dir() -> Path:
    d = get_voice_root() / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_recordings_dir() -> Path:
    d = get_voice_root() / "recordings"
    d.mkdir(parents=True, exist_ok=True)
    return d


class VoiceTTSService:
    """免费优先的 TTS 合成：edge-tts → MiniMax 回退。"""

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._minimax = None  # lazy

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        voice: str = "en-US-AriaNeural",
        speed: float = 1.0,
    ) -> SynthResult:
        """合成整段英文语音，返回本地 mp3 路径。

        speed: 0.5 ~ 2.0，1.0 为常速。缓存命中直接返回。
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("text 为空")
        if voice not in EDGE_VOICES:
            voice = "en-US-AriaNeural"
        speed = min(max(speed, 0.5), 2.0)

        key = hashlib.sha256(
            f"{text}|{voice}|{speed:.2f}".encode("utf-8")
        ).hexdigest()
        out_path = get_tts_dir() / f"{key}.mp3"
        if out_path.exists() and out_path.stat().st_size > 0:
            return SynthResult(path=out_path, provider="edge", cached=True)

        # ---- 主路径: edge-tts ----
        mp3_bytes = await self._edge_tts(text, voice, speed)
        provider = "edge"
        if mp3_bytes is None:
            # ---- 回退: MiniMax T2A ----
            mp3_bytes = await asyncio.to_thread(self._minimax_tts, text)
            provider = "minimax"
        if mp3_bytes is None:
            raise TTSServiceUnavailable(
                "edge-tts 与 MiniMax TTS 均不可用，请稍后重试"
            )

        out_path.write_bytes(mp3_bytes)
        return SynthResult(path=out_path, provider=provider, cached=False)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _edge_tts(
        self, text: str, voice: str, speed: float
    ) -> Optional[bytes]:
        """edge-tts 主路径。返回 mp3 bytes；失败返回 None（不打断流程）。"""
        try:
            import edge_tts
        except ImportError:
            logger.warning("[voice-tts] edge-tts 未安装")
            return None
        rate = f"+{int(round((speed - 1.0) * 100))}%"
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            data = b"".join(chunks)
            return data if data else None
        except asyncio.TimeoutError:
            logger.warning("[voice-tts] edge-tts 超时(%ss)", self._timeout)
            return None
        except Exception as exc:  # 网络错误 / 微软接口变动等
            logger.warning("[voice-tts] edge-tts 失败: %s", exc)
            return None

    def _minimax_tts(self, text: str) -> Optional[bytes]:
        """MiniMax T2A 回退（复用既有 ListeningTTSService）。"""
        try:
            if self._minimax is None:
                from ielts_buddy.web.listening_tts_service import ListeningTTSService
                self._minimax = ListeningTTSService()
            if not self._minimax.is_available():
                logger.warning("[voice-tts] MiniMax 回退不可用(无 API key)")
                return None
            data = self._minimax.synthesize(text)
            return data
        except Exception as exc:
            logger.warning("[voice-tts] MiniMax 回退失败: %s", exc)
            return None


# ---- 单例 ----
_voice_tts_service: Optional[VoiceTTSService] = None


def get_voice_tts_service() -> VoiceTTSService:
    global _voice_tts_service
    if _voice_tts_service is None:
        from ielts_buddy.web import config as web_config
        _voice_tts_service = VoiceTTSService(
            timeout=web_config.VOICE_TTS_TIMEOUT,
        )
    return _voice_tts_service
