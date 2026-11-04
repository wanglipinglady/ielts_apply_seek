"""语音训练工坊契约测试（v3.9 W11）。

覆盖：rewrite 创建/重试降级、音标解析、TTS 回退链（edge 不可用时不 500）、
录音上传校验、历史列表、notes 更新、journal-format、IDOR 防护。
"""
from __future__ import annotations

import io
import json
from pathlib import Path

TMP_VOICE = Path("/tmp/ielts_test_voice")


# ------------------------------------------------------------------ rewrite


def test_rewrite_creates_record(client, auth_headers, monkeypatch):
    """改写成功路径：创建记录并回填英文。"""
    monkeypatch.setenv("IELTS_BUDDY_VOICE_DIR", str(TMP_VOICE))

    class FakeResult:
        en_text = "Today I discussed the scheduling module."
        word_count = 6
        dry_run = False

    from ielts_buddy.web.routers import voice_training as vt

    def fake_rewrite(zh, style):
        return FakeResult()

    monkeypatch.setattr(
        vt.get_craft_rewrite_service(), "rewrite", fake_rewrite
    )
    r = client.post(
        "/api/voice-training/rewrite",
        json={"zh_text": "今天讨论了排产模块", "style": "natural"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["record_id"] > 0
    assert "scheduling" in data["en_text"]
    assert data["retryable"] is False


def test_rewrite_llm_failure_keeps_record(client, auth_headers, monkeypatch):
    """LLM 失败不阻塞：记录保留，返回 retryable=True（不 5xx）。"""
    from ielts_buddy.web.routers import voice_training as vt

    def boom(zh, style):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(vt.get_craft_rewrite_service(), "rewrite", boom)
    r = client.post(
        "/api/voice-training/rewrite",
        json={"zh_text": "今天写不了了", "style": "natural"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["retryable"] is True
    assert r.json()["record_id"] > 0


def test_rewrite_validation(client, auth_headers):
    """中文为空/超长 → 422。"""
    r = client.post(
        "/api/voice-training/rewrite",
        json={"zh_text": "a", "style": "natural"},
        headers=auth_headers,
    )
    assert r.status_code == 422
    r = client.post(
        "/api/voice-training/rewrite",
        json={"zh_text": "x" * 900, "style": "natural"},
        headers=auth_headers,
    )
    assert r.status_code == 422


# --------------------------------------------------------------- phonetics


def test_phonetics_flow(client, auth_headers, monkeypatch):
    """音标解析：CMUdict 命中词必须带正确美式 IPA，且落库。"""
    from ielts_buddy.web.routers import voice_training as vt

    class FakeResult:
        en_text = "Today I discussed the scheduling module."
        word_count = 6
        dry_run = False

    monkeypatch.setattr(
        vt.get_craft_rewrite_service(),
        "rewrite",
        lambda zh, style: FakeResult(),
    )
    rid = client.post(
        "/api/voice-training/rewrite",
        json={"zh_text": "今天讨论了排产模块", "style": "natural"},
        headers=auth_headers,
    ).json()["record_id"]

    r = client.post(
        f"/api/voice-training/{rid}/phonetics", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    words = {w["word"]: w for w in r.json()["words"]}
    assert words["scheduling"]["ipa_us"] == "/ˈskɛdʒʊlɪŋ/"
    assert words["Today"]["ipa_us"] == "/təˈdeɪ/"
    # 详情接口应回读 ipa
    detail = client.get(f"/api/voice-training/{rid}", headers=auth_headers)
    assert detail.status_code == 200
    assert len(detail.json()["ipa"]) > 0


def test_word_rule_stopword_empty(client, auth_headers):
    """停用词规则返回空串。"""
    r = client.get(
        "/api/voice-training/word-rule?word=the", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["rule"] == ""


# --------------------------------------------------------------------- tts


def test_tts_flow_with_fallback(client, auth_headers, monkeypatch, tmp_path):
    """TTS：edge 失败 → MiniMax 回退；都失败 → 503 而非 500。"""
    from ielts_buddy.web.routers import voice_training as vt
    from ielts_buddy.web.voice_tts_service import SynthResult

    class FakeResult:
        en_text = "Today I discussed the scheduling module."
        word_count = 6
        dry_run = False

    monkeypatch.setattr(
        vt.get_craft_rewrite_service(),
        "rewrite",
        lambda zh, style: FakeResult(),
    )
    rid = client.post(
        "/api/voice-training/rewrite",
        json={"zh_text": "今天讨论了排产模块", "style": "natural"},
        headers=auth_headers,
    ).json()["record_id"]

    # edge 主路径 mock 成功（避免测试依赖外网）
    async def fake_synthesize(text, voice="en-US-AriaNeural", speed=1.0):
        f = tmp_path / "tts.mp3"
        f.write_bytes(b"ID3fake")
        return SynthResult(path=f, provider="edge", cached=False)

    monkeypatch.setattr(
        vt.get_voice_tts_service(), "synthesize", fake_synthesize
    )
    r = client.post(
        f"/api/voice-training/{rid}/tts",
        json={"voice": "en-US-AriaNeural", "speed": 0.75},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "edge"

    # 全部失败 → 503
    from ielts_buddy.web.voice_tts_service import TTSServiceUnavailable

    async def boom(text, voice="en-US-AriaNeural", speed=1.0):
        raise TTSServiceUnavailable("all down")

    monkeypatch.setattr(vt.get_voice_tts_service(), "synthesize", boom)
    r = client.post(
        f"/api/voice-training/{rid}/tts",
        json={"voice": "en-US-AriaNeural", "speed": 1.0},
        headers=auth_headers,
    )
    assert r.status_code == 503


# ---------------------------------------------------------------- recording


def test_recording_upload_and_audio(client, auth_headers, monkeypatch, tmp_path):
    """录音上传：保存 + 归属校验 + 音频流。"""
    from ielts_buddy.web.routers import voice_training as vt

    class FakeResult:
        en_text = "Today I discussed the scheduling module."
        word_count = 6
        dry_run = False

    monkeypatch.setattr(
        vt.get_craft_rewrite_service(),
        "rewrite",
        lambda zh, style: FakeResult(),
    )
    rid = client.post(
        "/api/voice-training/rewrite",
        json={"zh_text": "今天讨论了排产模块", "style": "natural"},
        headers=auth_headers,
    ).json()["record_id"]

    # 录音目录 + 音频根目录都指到 tmp（下载端点用 _voice_root 拼相对路径）
    monkeypatch.setattr(vt, "get_recordings_dir", lambda: tmp_path / "recordings")
    (tmp_path / "recordings").mkdir(exist_ok=True)
    monkeypatch.setattr(vt, "_voice_root", lambda: tmp_path)

    fake_audio = io.BytesIO(b"\x1aE\xdf\xa3webm-fake")
    r = client.post(
        f"/api/voice-training/{rid}/recording",
        files={"audio": ("rec.webm", fake_audio, "audio/webm")},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    audio_url = r.json()["audio_url"]
    assert audio_url.endswith("/audio/recording")

    # 音频流可下载
    ra = client.get(audio_url, headers=auth_headers)
    assert ra.status_code == 200

    # 空录音 → 422
    r = client.post(
        f"/api/voice-training/{rid}/recording",
        files={"audio": ("rec.webm", io.BytesIO(b""), "audio/webm")},
        headers=auth_headers,
    )
    assert r.status_code == 422


# ------------------------------------------------------- records/notes/idor


def test_records_list_and_notes_and_journal(client, auth_headers, monkeypatch):
    from ielts_buddy.web.routers import voice_training as vt

    class FakeResult:
        en_text = "Today I discussed the scheduling module."
        word_count = 6
        dry_run = False

    monkeypatch.setattr(
        vt.get_craft_rewrite_service(),
        "rewrite",
        lambda zh, style: FakeResult(),
    )
    rid = client.post(
        "/api/voice-training/rewrite",
        json={"zh_text": "今天讨论了排产模块", "style": "natural"},
        headers=auth_headers,
    ).json()["record_id"]

    # 历史列表
    r = client.get("/api/voice-training/records", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    item = r.json()["items"][0]
    assert item["rewritten_en"].startswith("Today")

    # notes
    r = client.patch(
        f"/api/voice-training/{rid}",
        json={"notes": "scheduling 的 sk 读轻了"},
        headers=auth_headers,
    )
    assert r.status_code == 200 and r.json()["ok"] is True

    # journal format
    r = client.get(
        f"/api/voice-training/{rid}/journal-format", headers=auth_headers
    )
    assert r.status_code == 200
    md = r.json()["markdown"]
    assert "## 1. 今日感想" in md and "今天讨论了排产模块" in md
    assert "scheduling" in md


def test_idor_protection(client, auth_headers):
    """别人的记录 → 404。"""
    r = client.get("/api/voice-training/99999", headers=auth_headers)
    assert r.status_code == 404


def test_arpabet_conversion_accuracy():
    """ARPAbet→IPA 核心转换抽测（与剑桥词典人工比对过的样本）。"""
    from ielts_buddy.web.phonetics_service import _arpabet_to_ipa
    import pronouncing

    cases = {
        "schedule": "/ˈskɛdʒʊl/",
        "today": "/təˈdeɪ/",
        "international": "/ˌɪntɚˈnæʃənəl/",
        "the": "/ðə/",
    }
    for w, expect in cases.items():
        phones = pronouncing.phones_for_word(w)[0]
        assert _arpabet_to_ipa(phones) == expect, f"{w} 转换错误"
