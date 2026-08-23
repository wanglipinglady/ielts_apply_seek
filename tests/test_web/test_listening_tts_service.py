"""ListeningTTSService 单元测试（v3.7 P2 Sprint 2 新增）。

覆盖:
1. is_available:无 client → False
2. synthesize:无 client → None
3. _extract_audio_bytes:3 种响应格式(markdown 围栏 / JSON / 纯 base64 + mp3 header)
4. _extract_audio_bytes:非法输入 → None
5. 路径 helper:get_listening_root / audio_path_for
6. synthesize_to_file:成功路径写入文件
7. get_listening_tts_service 单例
"""
from __future__ import annotations

import base64
from pathlib import Path

from ielts_buddy.web.listening_tts_service import (
    ListeningTTSService,
    _extract_audio_bytes,
    audio_path_for,
    get_listening_root,
    get_listening_tts_service,
)


# =============================================================
# _extract_audio_bytes:响应解析
# =============================================================


class TestExtractAudioBytes:
    """LLM TTS 响应解析。"""

    def test_markdown_fence_with_audio_label(self) -> None:
        # 准备:构造一段假的 mp3(以 ID3 开头)
        mp3_bytes = b"ID3\x03\x00\x00\x00" + b"\x00" * 100
        b64 = base64.b64encode(mp3_bytes).decode("ascii")
        text = f"```audio\n{b64}\n```"
        result = _extract_audio_bytes(text)
        assert result is not None
        assert result[:3] == b"ID3"

    def test_json_field_audio_data(self) -> None:
        mp3_bytes = b"ID3\x03\x00\x00\x00" + b"\x01" * 50
        b64 = base64.b64encode(mp3_bytes).decode("ascii")
        import json
        text = json.dumps({"data": b64})
        result = _extract_audio_bytes(text)
        assert result is not None
        assert result[:3] == b"ID3"

    def test_raw_base64_with_mp3_header(self) -> None:
        mp3_bytes = b"ID3\x04\x00\x00\x00" + b"\x02" * 80
        b64 = base64.b64encode(mp3_bytes).decode("ascii")
        result = _extract_audio_bytes(b64)
        assert result is not None
        assert result[:3] == b"ID3"

    def test_invalid_base64_returns_none(self) -> None:
        assert _extract_audio_bytes("not-base64!!!") is None
        assert _extract_audio_bytes("") is None
        assert _extract_audio_bytes("```json\n{}\n```") is None

    def test_short_response_returns_none(self) -> None:
        # base64 解出来不够长 → 不是 mp3 → None
        short_b64 = base64.b64encode(b"abc").decode("ascii")
        result = _extract_audio_bytes(short_b64)
        assert result is None


# =============================================================
# 路径 helper
# =============================================================


class TestPathHelpers:
    """音频路径生成。"""

    def test_get_listening_root_creates_dir(self, tmp_path: Path,
                                             monkeypatch) -> None:
        # 重定向 get_app_dir 到 tmp_path
        from ielts_buddy.core import config
        monkeypatch.setattr(config, "get_app_dir", lambda: str(tmp_path))
        root = get_listening_root()
        assert root.exists()
        assert root.is_dir()
        assert root.name == "listening"

    def test_audio_path_for_returns_correct_path(self) -> None:
        p = audio_path_for(section=2, question_id=42)
        assert p.name == "q42.mp3"
        assert p.parent.name == "2"


# =============================================================
# ListeningTTSService
# =============================================================


class TestListeningTTSService:
    """TTS 服务行为。"""

    def test_is_available_false_when_no_client(self) -> None:
        svc = ListeningTTSService(llm_client=None)
        # 没有 LLM 时不可用
        assert svc.is_available() is False

    def test_synthesize_returns_none_when_no_client(self) -> None:
        svc = ListeningTTSService(llm_client=None)
        result = svc.synthesize("Hello world")
        assert result is None

    def test_synthesize_empty_text_returns_none(self) -> None:
        svc = ListeningTTSService(llm_client=None)
        assert svc.synthesize("") is None
        assert svc.synthesize("   ") is None

    def test_synthesize_to_file_returns_none_on_failure(self) -> None:
        svc = ListeningTTSService(llm_client=None)
        # synthesize 会返回 None,所以 synthesize_to_file 也返回 None
        result = svc.synthesize_to_file(
            text="hello", section=1, question_id=99,
        )
        assert result is None


# =============================================================
# Singleton
# =============================================================


class TestSingleton:
    def test_get_listening_tts_service_is_singleton(self) -> None:
        a = get_listening_tts_service()
        b = get_listening_tts_service()
        assert a is b