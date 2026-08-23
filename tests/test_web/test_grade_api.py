"""``/api/grade/*`` AI 批改端到端测试。

覆盖场景：
1. 未登录 → 401
2. essay 太短 → 422 (FastAPI Form 校验)
3. LLM 失败时 degrade 到 mock(200, ``source=mock``)
4. LLM 成功时返回真实结果(200, ``source=llm``);数据库有记录(user_id 隔离)
5. /api/grade/history 按 user 隔离,支持 task_type 过滤
6. /api/grade/stats 默认值 (total_count=0)

所有 LLM 调用都被 monkeypatch 阻断 —— 真实模型再快也只让测试跑本地的 mock。
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ielts_buddy.core.models import (
    GradeDimension,
    GradeResult,
    ParagraphAnalysis,
    SentenceAnnotation,
)


# =============================================================
# Fixtures
# =============================================================


ESSAY = (
    "Nowadays, an increasing number of people are concerned about the importance "
    "of environmental protection. There is a widespread debate about whether "
    "individual actions or government policies play a more critical role in "
    "addressing climate change. From my perspective, both are equally vital, "
    "and this essay will discuss the reasons in detail. "
    "Firstly, individual behaviour matters because every small action counts. "
    "When people reduce the use of plastic bags or switch to public transport, "
    "the cumulative impact is significant. Secondly, governments have the "
    "resources to introduce large-scale regulations that individuals alone could "
    "never achieve. In conclusion, both individual responsibility and "
    "government intervention are indispensable for solving environmental problems."
) * 2    # ≥50 字符;长一些更贴合真实 (200+ words)


def _register(client: TestClient, email: str = "grader@example.com", password: str = "password123") -> dict:
    r = client.post(
        "/api/auth/register",
        data={"email": email, "password": password},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "user_id": body["user"]["id"],
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
    }


def _login(client: TestClient, email: str, password: str) -> dict:
    r = client.post(
        "/api/auth/login",
        data={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return {
        "user_id": body["user"]["id"],
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
    }


def _make_fake_grade_result() -> GradeResult:
    """手工构造一个真实 LLM 才会返回的 GradeResult。"""
    return GradeResult(
        user_id=1,
        overall_score=6.5,
        task_response=GradeDimension(score=6.5, comment="审题清晰"),
        coherence=GradeDimension(score=6.0, comment="衔接可加强"),
        lexical_resource=GradeDimension(score=7.0, comment="词汇丰富"),
        grammar=GradeDimension(score=6.5, comment="基本准确"),
        suggestions=["多用复杂句式", "丰富高级词汇", "注意段落过渡"],
        rewrite="In contemporary society, environmental protection is of utmost importance.",
        essay_text=ESSAY,
        topic="environment",
        task_type="task2",
        annotations=[
            SentenceAnnotation(
                sentence_index=0,
                original="There is a widespread debate",
                issue_type="grammar",
                severity="minor",
                comment="there is 句型偏口语",
                suggestion="There exists a widespread debate / A widespread debate exists",
            ),
            SentenceAnnotation(
                sentence_index=2,
                original="individual actions or government policies",
                issue_type="coherence",
                severity="major",
                comment="缺少并列连词",
                suggestion="individual actions, rather than government policies, ..."  ,
            ),
        ],
        paragraphs=[
            ParagraphAnalysis(
                para_index=0,
                role="introduction",
                has_topic_sentence=True,
                structure_score=7.0,
                cohesion_devices=["furthermore"],
                comment="清晰的引言 + 立场",
            ),
        ],
        error_summary={"grammar": 1, "coherence": 1, "vocabulary": 0},
        graded_at="2026-08-23T10:00:00",
    )


# =============================================================
# 1. 鉴权 / 校验
# =============================================================


def test_grade_submit_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    """无登录态 → 401。"""
    r = client_with_db.post(
        "/api/grade/submit",
        data={"essay": ESSAY, "task_type": "task2"},
    )
    assert r.status_code == 401


def test_grade_submit_too_short_essay_returns_422(client_with_db: TestClient) -> None:
    """作文 < 50 字符 → 422。"""
    user = _register(client_with_db, email="short@example.com")
    r = client_with_db.post(
        "/api/grade/submit",
        data={"essay": "too short", "task_type": "task2"},
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert r.status_code == 422


# =============================================================
# 2. LLM 失败 degrade 到 mock
# =============================================================


def test_grade_submit_degrades_to_mock_when_llm_raises(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 抛 RuntimeError → degrade 到 mock,HTTP 200,source=mock。"""
    user = _register(client_with_db, email="mock-llm@example.com")

    # 阻断真实 LLM 调用：让 _call_llm_grader 抛 RuntimeError
    async def _fake_call_llm_grader(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("LLM unavailable (mocked)")

    monkeypatch.setattr(
        "ielts_buddy.web.routers.grade._call_llm_grader",
        _fake_call_llm_grader,
    )

    r = client_with_db.post(
        "/api/grade/submit",
        data={"essay": ESSAY, "task_type": "task2", "topic": "environment"},
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    meta = body["_meta"]
    assert meta["source"] == "mock"
    assert "LLM" in meta["error"] or "不可用" in meta["error"]
    # result schema 兼容前端
    result = body["result"]
    assert "overall_score" in result
    assert "band_scores" in result
    assert all(k in result["band_scores"] for k in ["task_response", "coherence", "lexical_resource", "grammar"])
    assert "error_summary" in result
    assert "suggestions" in result
    # 即便降级,数据库仍应保存(mock 路径也走 save_result)
    history = client_with_db.get(
        "/api/grade/history",
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert history.status_code == 200
    assert len(history.json()) >= 1


def test_grade_submit_degrades_on_timeout(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """asyncio.wait_for 抛 TimeoutError 时同样 degrade 到 mock。"""
    import asyncio

    user = _register(client_with_db, email="timeout@example.com")

    async def _fake_call_llm_grader(*args: Any, **kwargs: Any) -> None:
        raise asyncio.TimeoutError()

    monkeypatch.setattr(
        "ielts_buddy.web.routers.grade._call_llm_grader",
        _fake_call_llm_grader,
    )

    r = client_with_db.post(
        "/api/grade/submit",
        data={"essay": ESSAY, "task_type": "task2"},
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert r.status_code == 200
    assert r.json()["_meta"]["source"] == "mock"
    assert "超时" in r.json()["_meta"]["error"]


# =============================================================
# 3. LLM 成功路径 + user 隔离
# =============================================================


def test_grade_submit_real_llm_path(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 返回真实结果 → source=llm + 数据库有记录 + user_id 正确写入。"""
    user_alice = _register(client_with_db, email="alice@example.com")

    fake_result = _make_fake_grade_result()

    async def _fake_call_llm_grader(*args: Any, **kwargs: Any):
        # 返回真实 GradeResult 对象（替代 doc.grok.py subprocess + JSON 解析）
        return fake_result

    monkeypatch.setattr(
        "ielts_buddy.web.routers.grade._call_llm_grader",
        _fake_call_llm_grader,
    )

    r = client_with_db.post(
        "/api/grade/submit",
        data={"essay": ESSAY, "task_type": "task2", "topic": "environment"},
        headers={"Authorization": f"Bearer {user_alice['access_token']}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["_meta"]["source"] == "llm"
    result = body["result"]
    assert result["overall_score"] == 6.5
    assert result["task_type"] == "task2"
    assert result["topic"] == "environment"
    # LLM 路径下 annotations 应该被传出来
    assert len(result["annotations"]) == 2
    assert result["annotations"][0]["issue_type"] == "grammar"
    # rewrite 也应有
    assert "environmental" in result["rewrite"]
    # error_summary 应按 issue_type 分组
    assert "grammar" in result["error_summary"]
    assert len(result["error_summary"]["grammar"]) >= 1

    # 历史记录查得到
    hist = client_with_db.get(
        "/api/grade/history",
        headers={"Authorization": f"Bearer {user_alice['access_token']}"},
    )
    assert hist.status_code == 200
    hist_body = hist.json()
    assert len(hist_body) == 1
    assert hist_body[0]["task_type"] == "task2"
    assert hist_body[0]["overall_score"] == 6.5


def test_grade_history_user_isolation(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 用户的批改记录 B 用户看不到。

    通过给 Alice/Bob 各自提交不同 ``task_type`` 来观察：B 提交 task2、A 提交
    task1_academic,他们各自的 history 长度=1,但 API 不能 leak 对方的 task。
    若 ``WHERE user_id=?`` 漏写,A 会看到 B 的 task2 记录。
    """
    alice = _register(client_with_db, email="alice-iso@example.com")
    bob = _register(client_with_db, email="bob-iso@example.com")

    async def _fake_call_llm_grader(*args: Any, **kwargs: Any):
        return _make_fake_grade_result()

    monkeypatch.setattr(
        "ielts_buddy.web.routers.grade._call_llm_grader",
        _fake_call_llm_grader,
    )

    # Alice 提交 task1_academic,Bob 提交 task2 —— 不同 task_type 互相能区分
    for token, tt in (
        (alice["access_token"], "task1_academic"),
        (bob["access_token"], "task2"),
    ):
        client_with_db.post(
            "/api/grade/submit",
            data={"essay": ESSAY, "task_type": tt},
            headers={"Authorization": f"Bearer {token}"},
        )

    # Alice 不应看到 Bob 的 task2 → task_type 过滤
    alice_only = client_with_db.get(
        "/api/grade/history?task_type=task2",
        headers={"Authorization": f"Bearer {alice['access_token']}"},
    ).json()
    assert alice_only == []    # Alice 没有 task2 记录 → 隔离生效

    # Bob 不应看到 Alice 的 task1_academic
    bob_only = client_with_db.get(
        "/api/grade/history?task_type=task1_academic",
        headers={"Authorization": f"Bearer {bob['access_token']}"},
    ).json()
    assert bob_only == []     # Bob 没有 task1_academic 记录

    # 各自的全量 history 都只有自己那条
    alice_all = client_with_db.get(
        "/api/grade/history",
        headers={"Authorization": f"Bearer {alice['access_token']}"},
    ).json()
    bob_all = client_with_db.get(
        "/api/grade/history",
        headers={"Authorization": f"Bearer {bob['access_token']}"},
    ).json()
    assert len(alice_all) == 1
    assert alice_all[0]["task_type"] == "task1_academic"
    assert len(bob_all) == 1
    assert bob_all[0]["task_type"] == "task2"


def test_grade_history_task_type_filter(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """task_type 过滤可用。"""
    user = _register(client_with_db, email="filter@example.com")

    async def _fake(*args: Any, **kwargs: Any):
        return _make_fake_grade_result()

    monkeypatch.setattr(
        "ielts_buddy.web.routers.grade._call_llm_grader",
        _fake,
    )

    # 提交 task2 与 task1_academic 各一次
    for tt in ("task2", "task1_academic"):
        client_with_db.post(
            "/api/grade/submit",
            data={"essay": ESSAY, "task_type": tt},
            headers={"Authorization": f"Bearer {user['access_token']}"},
        )

    # 不带过滤 → 2 条
    all_h = client_with_db.get(
        "/api/grade/history",
        headers={"Authorization": f"Bearer {user['access_token']}"},
    ).json()
    assert len(all_h) == 2

    # 过滤 task2 → 1 条
    only_task2 = client_with_db.get(
        "/api/grade/history?task_type=task2",
        headers={"Authorization": f"Bearer {user['access_token']}"},
    ).json()
    assert len(only_task2) == 1
    assert only_task2[0]["task_type"] == "task2"


def test_grade_invalid_task_type_falls_back_to_task2(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非法 task_type 不报错,内部规范化成 task2。"""
    user = _register(client_with_db, email="bad-tt@example.com")

    captured_args: list[tuple] = []

    async def _fake(*args: Any, **kwargs: Any):
        captured_args.append((args, kwargs))
        return _make_fake_grade_result()

    monkeypatch.setattr(
        "ielts_buddy.web.routers.grade._call_llm_grader",
        _fake,
    )

    r = client_with_db.post(
        "/api/grade/submit",
        data={"essay": ESSAY, "task_type": "task_unknown"},
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert r.status_code == 200
    # _call_llm_grader 的第 5 个位置参数是 task_type
    call_args, call_kwargs = captured_args[0]
    if "task_type" in call_kwargs:
        # 传成 kwargs
        assert call_kwargs["task_type"] == "task2"
    else:
        # 位置参数：(container, user_id, essay, topic, task_type)
        assert call_args[4] == "task2"
    # response 的 _meta.task_type 也应是 task2
    assert r.json()["_meta"]["task_type"] == "task2"


# =============================================================
# 4. /api/grade/stats
# =============================================================


def test_grade_stats_empty_returns_zero(client_with_db: TestClient) -> None:
    """从未批改过 → total=0 / average=0.0,不抛 500。"""
    user = _register(client_with_db, email="empty@example.com")
    r = client_with_db.get(
        "/api/grade/stats",
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_count"] == 0
    assert body["average_score"] == 0.0


def test_grade_stats_after_one_grading(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """批改一次后 total=1,平均分=6.5。"""
    user = _register(client_with_db, email="one@example.com")

    async def _fake(*args: Any, **kwargs: Any):
        return _make_fake_grade_result()    # overall=6.5

    monkeypatch.setattr(
        "ielts_buddy.web.routers.grade._call_llm_grader",
        _fake,
    )

    client_with_db.post(
        "/api/grade/submit",
        data={"essay": ESSAY, "task_type": "task2"},
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    r = client_with_db.get(
        "/api/grade/stats",
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_count"] == 1
    assert body["average_score"] == 6.5


def test_grade_stats_unauthenticated_returns_401(client_with_db: TestClient) -> None:
    r = client_with_db.get("/api/grade/stats")
    assert r.status_code == 401


# =============================================================
# 5. 模板兼容：mock fallback 字段
# =============================================================


def test_grade_result_shape_contains_frontend_required_keys(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """前端依赖的字段在两种 source 下都不能缺失。"""
    user = _register(client_with_db, email="shape@example.com")

    # ---- 走 LLM 路径 ----
    async def _fake_llm(*args: Any, **kwargs: Any):
        return _make_fake_grade_result()

    monkeypatch.setattr(
        "ielts_buddy.web.routers.grade._call_llm_grader",
        _fake_llm,
    )
    r = client_with_db.post(
        "/api/grade/submit",
        data={"essay": ESSAY, "task_type": "task2"},
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    result = r.json()["result"]
    frontend_required = {"overall_score", "band_scores", "error_summary", "suggestions", "word_count"}
    assert frontend_required <= set(result.keys())
    assert set(result["band_scores"].keys()) == {
        "task_response", "coherence", "lexical_resource", "grammar"
    }

    # ---- 走 mock fallback ----
    async def _fake_err(*args: Any, **kwargs: Any):
        raise RuntimeError("")

    monkeypatch.setattr(
        "ielts_buddy.web.routers.grade._call_llm_grader",
        _fake_err,
    )
    r2 = client_with_db.post(
        "/api/grade/submit",
        data={"essay": ESSAY, "task_type": "task2"},
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    result2 = r2.json()["result"]
    assert frontend_required <= set(result2.keys())
    assert r2.json()["_meta"]["source"] == "mock"
