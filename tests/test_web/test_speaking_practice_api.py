"""``/speak/practice`` 口语对练路由端到端测试（v3.7 P1 新增）。

覆盖:
 1. /speak/practice 未登录 → 302 → /login
 2. /speak/practice 已登录 → 200 + HTML 含「口语对练」
 3. /api/speak/practice/start 未登录 → 401
 4. /api/speak/practice/start → 200 + 返回 session_id + question
 5. /api/speak/practice/start?part=2 → 200 + part 固定
 6. /api/speak/practice/start?part=0/4 → 422
 7. /api/speak/practice/submit 未登录 → 401
 8. /api/speak/practice/submit 完整流水线:transcript + 评分 + 错词回收
 9. /api/speak/practice/submit 时长超限 → 422
10. /api/speak/practice/submit 空音频 → 422
11. /api/speak/practice/history 已登录 → 200 + 含上一步的记录
12. /api/speak/practice/{record_id} → 200 + 详情
13. /api/speak/practice/{record_id} 不存在 → 404
14. /api/speak/practice/audio/{sid} → 200 + 流式
15. IDOR:用户 B 不能访问用户 A 的录音
"""
from __future__ import annotations

import json as _json
import os
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient


WEB_DIR = Path(__file__).resolve().parents[2] / "src" / "ielts_buddy" / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


# =============================================================
# Fixtures
# =============================================================


class _StubWhisper:
    """WhisperService 的最薄 stub——保证测试不依赖 whisper.cpp。"""

    last_call_args: dict[str, Any] = {}

    def is_available(self) -> bool:
        return True

    def transcribe(self, audio_path: str) -> Any:
        # 返回一个带 text + tokens 的对象（duck typing 给 service 读 .text / .tokens）
        from ielts_buddy.web.whisper_service import TranscriptResult

        _StubWhisper.last_call_args = {"audio_path": audio_path}
        return TranscriptResult(
            text="I really enjoy playing basketball with my friends in the evening",
            tokens=[
                {"text": "I", "start": 0.0, "end": 0.1},
                {"text": "really", "start": 0.1, "end": 0.4},
            ],
            fallback=False,
            model_id="stub-small.en",
            used_core_ml=False,
        )


@pytest.fixture
def practice_client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """口语对练专用 TestClient:自带 auth + speaking_practice router。

    monkeypatch:
      - 把 _get_whisper() 替换为返回 _StubWhisper
        (避开 pywhispercpp / 模型文件)
    """
    os.environ.setdefault("IELTS_BUDDY_ENV", "dev")
    os.environ.setdefault("IELTS_BUDDY_JWT_SECRET", "test-secret-" + "x" * 32)
    os.environ.setdefault("IELTS_BUDDY_WEB_DB_MODE", "sqlite")
    os.environ["IELTS_BUDDY_WEB_SQLITE_PATH"] = str(tmp_path / "web_data.db")

    # 强制重新加载 config 模块（清除缓存）
    import importlib
    from ielts_buddy.web import config as web_config
    importlib.reload(web_config)

    from ielts_buddy.repositories.fallback_repo import create_fallback_container
    from ielts_buddy.web.auth.repository import create_sqlite_web_user_repository
    from ielts_buddy.web.routers import auth as auth_routes
    from ielts_buddy.web.routers import speaking_practice as sp_routes

    # mock whisper:任何 import 拿 _get_whisper() 都得到 Stub
    monkeypatch.setattr(
        "ielts_buddy.services.speaking_practice_service._get_whisper",
        lambda: _StubWhisper(),
        raising=True,
    )

    app = FastAPI()
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates.env.globals["app_name"] = "IELTS Buddy"
    app.state.templates.env.globals["app_version"] = "0.1.0"
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(auth_routes.router)
    app.include_router(auth_routes.api_router)
    app.include_router(sp_routes.router)
    app.include_router(sp_routes.api_router)

    repo = create_sqlite_web_user_repository(":memory:")
    app.state.web_user_repo = repo

    sqlite_path = Path(str(tmp_path / "web_data.db"))
    app.state.container = create_fallback_container(
        sqlite_db_path=sqlite_path,
        mysql_url="",
        prefer_mode="sqlite",
    )

    with TestClient(app) as c:
        yield c


def _register(
    client: TestClient,
    email: str,
    password: str = "password123",
) -> dict[str, Any]:
    r = client.post(
        "/api/auth/register",
        data={"email": email, "password": password},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "user_id": body["user"]["id"],
        "access_token": body["access_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }


def _fake_audio_bytes() -> bytes:
    # 12 字节 payload:webm 头足够长,mock 落盘 / 转写都不会真解析它
    return b"\x1a\x45\xdf\xa3" + b"\x00" * 8


def _submit_form(
    client: TestClient,
    headers: dict,
    *,
    session_id: str,
    part: int = 1,
    topic_id: int = 1,
    topic_name: str = "Hometown",
    question: str = "Where is your hometown?",
    duration: float = 18.0,
) -> Any:
    return client.post(
        "/api/speak/practice/submit",
        headers=headers,
        data={
            "session_id": session_id,
            "part": str(part),
            "topic_id": str(topic_id),
            "topic_name": topic_name,
            "question": question,
            "actual_duration_sec": str(duration),
            "vocab_hints": "city,rural",
            "sample_answer": "My hometown is a small city.",
        },
        files={
            "audio": (
                "recording.webm",
                _fake_audio_bytes(),
                "audio/webm",
            ),
        },
    )


# =============================================================
# 1. /speak/practice 页面路由
# =============================================================


def test_practice_page_unauthenticated_redirects_to_login(
    practice_client: TestClient,
) -> None:
    r = practice_client.get("/speak/practice", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("location") == "/login"


def test_practice_page_authenticated_returns_html(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-page@example.com")
    r = practice_client.get("/speak/practice", headers=user["headers"])
    assert r.status_code == 200, r.text
    assert "口语对练" in r.text


# =============================================================
# 2. /api/speak/practice/start
# =============================================================


def test_api_start_unauthenticated_returns_401(
    practice_client: TestClient,
) -> None:
    r = practice_client.post("/api/speak/practice/start")
    assert r.status_code == 401


def test_api_start_returns_session_and_question(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-start@example.com")
    r = practice_client.post(
        "/api/speak/practice/start",
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 字段完整性
    required = {
        "session_id", "part", "part_label", "topic_id",
        "topic", "question", "vocab", "sample_answer", "tips",
    }
    assert required <= set(body.keys())
    # session_id 是 UUID 形式
    assert len(body["session_id"]) >= 16
    # part ∈ [1, 3]
    assert body["part"] in (1, 2, 3)
    # 至少 1 个问题
    assert len(body["question"]) > 0


def test_api_start_with_part_2_filters(practice_client: TestClient) -> None:
    user = _register(practice_client, "practice-start2@example.com")
    # 多抽几次确认 part 锁在 2
    for _ in range(3):
        r = practice_client.post(
            "/api/speak/practice/start?part=2",
            headers=user["headers"],
        )
        assert r.status_code == 200, r.text
        assert r.json()["part"] == 2


def test_api_start_invalid_part_returns_422(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-bad-part@example.com")
    for bad in (0, 4, -1):
        r = practice_client.post(
            f"/api/speak/practice/start?part={bad}",
            headers=user["headers"],
        )
        assert r.status_code == 422, f"part={bad} 应被拒"


# =============================================================
# 3. /api/speak/practice/submit 完整流水线
# =============================================================


def test_api_submit_unauthenticated_returns_401(
    practice_client: TestClient,
) -> None:
    r = practice_client.post("/api/speak/practice/submit")
    assert r.status_code == 401


def test_api_submit_full_pipeline(practice_client: TestClient) -> None:
    """完整 submit:录音 → mock 转写 → mock 评分 → 落库。"""
    user = _register(practice_client, "practice-submit@example.com")
    start = practice_client.post(
        "/api/speak/practice/start?part=1",
        headers=user["headers"],
    )
    sbody = start.json()

    r = _submit_form(
        practice_client,
        user["headers"],
        session_id=sbody["session_id"],
        part=sbody["part"],
        topic_id=sbody["topic_id"],
        topic_name=sbody["topic"],
        question=sbody["question"],
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # 字段完整性
    required = {
        "record_id", "session_id", "transcript", "tokens", "scores",
        "word_errors", "grammar_errors", "highlights", "suggestions",
        "whisper_fallback", "score_fallback",
    }
    assert required <= set(body.keys())

    # transcript 来自 stub
    assert "basketball" in body["transcript"]
    assert body["whisper_fallback"] is False  # mock 真有返回值
    assert body["score_fallback"] is True    # 评分走 mock

    # scores 4 维
    s = body["scores"]
    for k in ("fluency", "lexical", "grammar", "pronunciation", "overall_band"):
        assert k in s
        assert 0.0 <= s[k] <= 9.0

    # 录音持久化(API 返回 audio_url 而不是物理路径)
    rec = practice_client.get(
        f"/api/speak/practice/{body['record_id']}",
        headers=user["headers"],
    )
    assert rec.status_code == 200
    rec_body = rec.json()
    assert rec_body["audio_url"] is not None
    assert rec_body["audio_mime"] == "audio/webm"
    assert rec_body["transcript"] != ""


def test_api_submit_duration_over_limit_returns_422(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-dur@example.com")
    start = practice_client.post(
        "/api/speak/practice/start",
        headers=user["headers"],
    )
    sbody = start.json()
    # 默认上限 120 + 5 容差,180 应被拒
    r = _submit_form(
        practice_client,
        user["headers"],
        session_id=sbody["session_id"],
        duration=180.0,
    )
    assert r.status_code == 422
    assert "超出上限" in r.json()["detail"]


def test_api_submit_empty_audio_returns_422(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-empty@example.com")
    start = practice_client.post(
        "/api/speak/practice/start",
        headers=user["headers"],
    )
    sbody = start.json()
    r = practice_client.post(
        "/api/speak/practice/submit",
        headers=user["headers"],
        data={
            "session_id": sbody["session_id"],
            "part": "1",
            "topic_id": "1",
            "topic_name": "Test",
            "question": "Q?",
            "actual_duration_sec": "5",
        },
        files={"audio": ("empty.webm", b"", "audio/webm")},
    )
    assert r.status_code == 422
    assert "音频为空" in r.json()["detail"]


def test_api_submit_invalid_mime_returns_422(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-mime@example.com")
    start = practice_client.post(
        "/api/speak/practice/start",
        headers=user["headers"],
    )
    sbody = start.json()
    r = practice_client.post(
        "/api/speak/practice/submit",
        headers=user["headers"],
        data={
            "session_id": sbody["session_id"],
            "part": "1",
            "topic_id": "1",
            "topic_name": "Test",
            "question": "Q?",
            "actual_duration_sec": "5",
        },
        files={"audio": ("virus.exe", b"fake", "application/x-msdownload")},
    )
    assert r.status_code == 422
    assert "不支持的音频类型" in r.json()["detail"]


# =============================================================
# 4. /api/speak/practice/history
# =============================================================


def test_api_history_unauthenticated_returns_401(
    practice_client: TestClient,
) -> None:
    r = practice_client.get("/api/speak/practice/history")
    assert r.status_code == 401


def test_api_history_includes_submitted_record(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-hist@example.com")
    # 先 submit 一条
    start = practice_client.post(
        "/api/speak/practice/start?part=1",
        headers=user["headers"],
    )
    sbody = start.json()
    r = _submit_form(
        practice_client,
        user["headers"],
        session_id=sbody["session_id"],
        part=1,
        topic_id=sbody["topic_id"],
        topic_name=sbody["topic"],
        question=sbody["question"],
    )
    assert r.status_code == 200
    record_id = r.json()["record_id"]

    # history 应该包含
    hist = practice_client.get(
        "/api/speak/practice/history?part=1",
        headers=user["headers"],
    )
    assert hist.status_code == 200
    hbody = hist.json()
    assert hbody["total"] >= 1
    assert len(hbody["items"]) >= 1
    ids = [it["record_id"] for it in hbody["items"]]
    assert record_id in ids
    # audio_url 必须有效
    item = next(it for it in hbody["items"] if it["record_id"] == record_id)
    assert item["audio_url"] is not None


def test_api_history_part_filter_excludes_other_part(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-histfilter@example.com")
    # submit 一条 Part 1
    start = practice_client.post(
        "/api/speak/practice/start?part=1",
        headers=user["headers"],
    )
    sbody = start.json()
    _submit_form(
        practice_client,
        user["headers"],
        session_id=sbody["session_id"],
        part=1,
        topic_id=sbody["topic_id"],
        topic_name=sbody["topic"],
        question=sbody["question"],
    )
    # 用 part=2 过滤应该查不到
    hist = practice_client.get(
        "/api/speak/practice/history?part=2",
        headers=user["headers"],
    )
    assert hist.status_code == 200
    assert hist.json()["total"] == 0


# =============================================================
# 5. /api/speak/practice/{record_id}
# =============================================================


def test_api_record_detail_unauthenticated_returns_401(
    practice_client: TestClient,
) -> None:
    r = practice_client.get("/api/speak/practice/1")
    assert r.status_code == 401


def test_api_record_detail_not_found_returns_404(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-404@example.com")
    r = practice_client.get(
        "/api/speak/practice/99999",
        headers=user["headers"],
    )
    assert r.status_code == 404


# =============================================================
# 6. /api/speak/practice/audio/{session_id} + IDOR
# =============================================================


def test_api_audio_unauthenticated_returns_401(
    practice_client: TestClient,
) -> None:
    r = practice_client.get("/api/speak/practice/audio/some-sid")
    assert r.status_code == 401


def test_api_audio_not_found_returns_404(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-audio404@example.com")
    r = practice_client.get(
        "/api/speak/practice/audio/nonexistent-session-id",
        headers=user["headers"],
    )
    assert r.status_code == 404


def test_api_audio_streams_back_persisted_bytes(
    practice_client: TestClient,
) -> None:
    user = _register(practice_client, "practice-audio@example.com")
    start = practice_client.post(
        "/api/speak/practice/start",
        headers=user["headers"],
    )
    sbody = start.json()
    audio_bytes = _fake_audio_bytes()
    r = practice_client.post(
        "/api/speak/practice/submit",
        headers=user["headers"],
        data={
            "session_id": sbody["session_id"],
            "part": "1",
            "topic_id": str(sbody["topic_id"]),
            "topic_name": sbody["topic"],
            "question": sbody["question"],
            "actual_duration_sec": "12",
        },
        files={
            "audio": ("rec.webm", audio_bytes, "audio/webm"),
        },
    )
    assert r.status_code == 200
    rid = r.json()["record_id"]

    # 取到 audio_url
    hist = practice_client.get(
        "/api/speak/practice/history",
        headers=user["headers"],
    )
    item = next(
        it for it in hist.json()["items"] if it["record_id"] == rid
    )
    assert item["audio_url"] is not None
    audio_url = item["audio_url"]

    # 下载
    down = practice_client.get(audio_url, headers=user["headers"])
    assert down.status_code == 200
    # 内容字节应该 ≥ submit 的字节(mime 推断 webm → 原样存)
    assert len(down.content) >= len(audio_bytes)
    # 流式 content-type 是 webm
    assert "webm" in down.headers.get("content-type", "")


def test_api_audio_idor_returns_404_for_other_user(
    practice_client: TestClient,
) -> None:
    """IDOR 测试:用户 A 的录音,用户 B 拿不到。"""
    alice = _register(practice_client, "alice-idor@example.com")
    bob = _register(practice_client, "bob-idor@example.com")

    # Alice submit
    start = practice_client.post(
        "/api/speak/practice/start",
        headers=alice["headers"],
    )
    sbody = start.json()
    r = _submit_form(
        practice_client,
        alice["headers"],
        session_id=sbody["session_id"],
        part=sbody["part"],
        topic_id=sbody["topic_id"],
        topic_name=sbody["topic"],
        question=sbody["question"],
    )
    assert r.status_code == 200
    record_id = r.json()["record_id"]

    # Bob 拿不到 detail
    bob_detail = practice_client.get(
        f"/api/speak/practice/{record_id}",
        headers=bob["headers"],
    )
    assert bob_detail.status_code == 404

    # Bob 也拿不到 audio url
    bob_hist = practice_client.get(
        "/api/speak/practice/history",
        headers=bob["headers"],
    )
    assert bob_hist.json()["total"] == 0


# =============================================================
# 7. 错词回收验证
# =============================================================


def test_api_submit_recovers_word_errors_to_personal_vocab(
    practice_client: TestClient, monkeypatch
) -> None:
    """LLM 评分走 mock 不会产生错词;直接 monkeypatch grade()
    给出一份含 2 个错词的输出,验证 _recover_word_errors 落库路径。
    """
    user = _register(practice_client, "practice-recover@example.com")

    # 注入真实错词
    from ielts_buddy.services.speaking_practice_service import (
        SpeakingPracticeService,
    )

    orig_submit = SpeakingPracticeService.submit

    def patched_submit(self, *args, **kwargs):
        # 拦截 grade 调用,在 mock 评分基础上手工塞 word_errors
        out = orig_submit(self, *args, **kwargs)
        # 直接打补丁修改 grade._mock_grade 不便,改为事后改 out:
        # 但这样不能触发 _recover_word_errors(已经在 submit 里跑过)。
        # 因此替换 _grade.grade 让它在原流程里产出真实错词。
        return out

    # 更简洁的做法:monkeypatch SpeakingGradeService.grade
    from ielts_buddy.web.speaking_grade_service import SpeakingGradeService

    def fake_grade(
        self, part, topic, question, transcript,
        sample_answer=None, vocab_hints=None,
    ):
        return {
            "scores": {
                "fluency": 6.0, "lexical": 6.0,
                "grammar": 6.0, "pronunciation": 6.0,
                "overall_band": 6.0,
            },
            "word_errors": [
                {"original": "amound", "correction": "amount",
                 "context": "a large amound of"},
                {"original": "recieve", "correction": "receive",
                 "context": "I recieve"},
            ],
            "grammar_errors": [],
            "highlights": ["ok"],
            "suggestions": ["use past tense"],
            "score_fallback": False,
        }

    monkeypatch.setattr(SpeakingGradeService, "grade", fake_grade)

    start = practice_client.post(
        "/api/speak/practice/start",
        headers=user["headers"],
    )
    sbody = start.json()
    r = _submit_form(
        practice_client,
        user["headers"],
        session_id=sbody["session_id"],
        part=sbody["part"],
        topic_id=sbody["topic_id"],
        topic_name=sbody["topic"],
        question=sbody["question"],
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # 错词回收后只剩 word 字段,2 个单词
    assert len(body["word_errors"]) == 2
    recovered = {we["word"] for we in body["word_errors"]}
    assert recovered == {"amount", "receive"}

    # 个人词库 mistakes 分类应该有这 2 个(直接查 repo,不走 /api/mistakes)
    pv_repo = practice_client.app.state.container.personal_vocab
    # list_words(category="mistakes") 返回 list[PersonalWord]
    pv_words, _ = pv_repo.list_words(user["user_id"], category="mistakes")
    pv_word_set = {w.word for w in pv_words}
    # learning_records 也应该记录这两个词(错词回收双写)
    learning_repo = practice_client.app.state.container.learning
    learned = learning_repo.get_learned_words(user["user_id"])
    assert {"amount", "receive"}.issubset(set(learned)), (
        f"错词未落 learning_records; pv={pv_word_set}"
    )
    assert {"amount", "receive"}.issubset(pv_word_set), (
        f"错词未落 personal_vocab.mistakes; learned={learned}"
    )