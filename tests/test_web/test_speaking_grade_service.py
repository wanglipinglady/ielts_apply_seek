"""SpeakingGradeService 单元测试（v3.7 P1 新增）。

覆盖:
1. mock fallback(无 client / dry-run) → score_fallback=True
2. 真 LLM 路径(注入 mock client) → score_fallback=False
3. retry-once(第一次 JSON 错,第二次重试成功)
4. JSON 解析容错:```json fence + <think> 块 + 前置文字
5. _normalize_payload:字段补全 + 越界剔除
"""
from __future__ import annotations

from typing import Any

from ielts_buddy.web.speaking_grade_service import (
    SpeakingGradeService,
    _clamp_score,
    extract_json,
)


class _StubMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubChoice:
    def __init__(self, content: str) -> None:
        self.message = _StubMessage(content)


class _StubResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_StubChoice(content)]


class _StubClient:
    """模拟 OpenAI 客户端。支持按调用次数返回不同内容。"""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.call_count = 0
        self.last_kwargs: dict[str, Any] = {}

    class _Completions:
        def __init__(self, outer: "_StubClient") -> None:
            self._outer = outer

        def create(self, **kwargs) -> _StubResponse:
            self._outer.call_count += 1
            self._outer.last_kwargs = kwargs
            content = self._outer._contents[self._outer.call_count - 1]
            return _StubResponse(content)

    class _Chat:
        def __init__(self, outer: "_StubClient") -> None:
            self.completions = _StubClient._Completions(outer)

    @property
    def chat(self) -> Any:
        return _StubClient._Chat(self)


# =============================================================
# 1. mock fallback
# =============================================================


def test_grade_uses_mock_when_no_client() -> None:
    """无 LLM client → 走 mock,score_fallback=True。"""
    svc = SpeakingGradeService(llm_client=None)
    # 屏蔽 LLMService 自动注入(在没装 openai 的环境下 _llm_service=None)
    svc._llm_service = None
    out = svc.grade(
        part=1, topic="Hometown", question="Where is your hometown?",
        transcript="I come from a small town near the coast.",
    )
    assert out["score_fallback"] is True
    assert "scores" in out
    assert out["scores"]["overall_band"] >= 5.0


def test_grade_mock_handles_empty_transcript() -> None:
    """空 transcript → mock 给最低分 + 提示。"""
    svc = SpeakingGradeService(llm_client=None)
    svc._llm_service = None
    out = svc.grade(
        part=1, topic="Hometown", question="?",
        transcript="",
    )
    assert out["score_fallback"] is True
    # overall_band 应该在 5.0
    assert out["scores"]["overall_band"] <= 5.5


# =============================================================
# 2. 真 LLM 路径(mock client)
# =============================================================


def test_grade_uses_real_llm_path_when_client_available() -> None:
    """有 client + 返回合法 JSON → score_fallback=False。"""
    raw_json = (
        '{"scores":{"fluency":7,"lexical":6.5,"grammar":7,'
        '"pronunciation":6.5,"overall_band":6.75},'
        '"word_errors":[{"original":"amound","correction":"amount",'
        '"context":"a large amound"}],'
        '"grammar_errors":[],'
        '"highlights":["good structure"],'
        '"suggestions":["use more connectors"]}'
    )
    client = _StubClient([raw_json])
    svc = SpeakingGradeService(llm_client=client)
    # 屏蔽 LLMService 自动注入
    svc._llm_service = None

    out = svc.grade(
        part=2, topic="Travel", question="Describe a trip.",
        transcript="I went to a place last year and it was very nice",
    )

    assert out["score_fallback"] is False
    assert out["scores"]["fluency"] == 7.0
    # overall_band = mean(7, 6.5, 7, 6.5) = 6.75 → 0.5 精度 → 7.0
    assert out["scores"]["overall_band"] == 7.0
    assert len(out["word_errors"]) == 1
    assert out["word_errors"][0]["correction"] == "amount"
    assert "good structure" in out["highlights"]
    # 重试机制:LLM 只被调 1 次(第一次成功)
    assert client.call_count == 1


def test_grade_retries_on_invalid_json() -> None:
    """第一次 JSON 解析失败 → 重试 1 次,第二次成功 → 走 LLM 路径。"""
    broken = "<think>reasoning...</think>```json\n{scores not valid"
    fixed = (
        '{"scores":{"fluency":6,"lexical":6,"grammar":6,'
        '"pronunciation":6,"overall_band":6},'
        '"word_errors":[],"grammar_errors":[],'
        '"highlights":["ok"], "suggestions":["more"]}'
    )
    client = _StubClient([broken, fixed])
    svc = SpeakingGradeService(llm_client=client)
    svc._llm_service = None

    out = svc.grade(
        part=1, topic="Hometown", question="?",
        transcript="test",
    )
    assert out["score_fallback"] is False
    assert out["scores"]["overall_band"] == 6.0
    assert client.call_count == 2


def test_grade_falls_back_to_mock_when_both_attempts_fail() -> None:
    """两次都解析失败 → mock fallback。"""
    client = _StubClient(["not json", "still not json"])
    svc = SpeakingGradeService(llm_client=client)
    svc._llm_service = None

    out = svc.grade(
        part=1, topic="x", question="?",
        transcript="hello world",
    )
    assert out["score_fallback"] is True
    assert client.call_count == 2


def test_grade_falls_back_on_llm_exception() -> None:
    """LLM 抛异常 → mock fallback。"""

    class _ExplodingClient:
        class _ChatCompletions:
            def create(self, **kwargs):
                raise RuntimeError("network error")

        @property
        def chat(self):
            return _ExplodingClient._ChatCompletions()

    svc = SpeakingGradeService(llm_client=_ExplodingClient())
    svc._llm_service = None

    out = svc.grade(
        part=1, topic="x", question="?",
        transcript="hi",
    )
    assert out["score_fallback"] is True


# =============================================================
# 3. JSON 解析容错
# =============================================================


def test_extract_json_strips_markdown_fence() -> None:
    raw = (
        "```json\n"
        '{"scores":{"fluency":7},"word_errors":[],"grammar_errors":[],'
        '"highlights":[],"suggestions":[]}\n'
        "```"
    )
    parsed = extract_json(raw)
    assert parsed is not None
    assert parsed["scores"]["fluency"] == 7


def test_extract_json_strips_think_block() -> None:
    raw = (
        "<think>\nlet me think carefully...\nstill thinking\n</think>\n"
        '{"scores":{"fluency":6.5},"word_errors":[],"grammar_errors":[],'
        '"highlights":[],"suggestions":[]}'
    )
    parsed = extract_json(raw)
    assert parsed is not None
    assert parsed["scores"]["fluency"] == 6.5


def test_extract_json_handles_pre_and_post_text() -> None:
    raw = (
        "Here is my assessment:\n"
        '{"scores":{"fluency":7},"word_errors":[],"grammar_errors":[],'
        '"highlights":["ok"],"suggestions":["more"]}\n'
        "Hope this helps!"
    )
    parsed = extract_json(raw)
    assert parsed is not None
    assert "ok" in parsed["highlights"]


def test_extract_json_returns_none_for_garbage() -> None:
    assert extract_json("") is None
    assert extract_json("no json at all") is None
    assert extract_json("{broken") is None


# =============================================================
# 4. _normalize_payload & _clamp_score
# =============================================================


def test_clamp_score_rounds_to_half() -> None:
    assert _clamp_score(7.4) == 7.5
    assert _clamp_score(7.2) == 7.0
    assert _clamp_score(6.75) == 7.0
    assert _clamp_score(6.0) == 6.0


def test_clamp_score_rejects_out_of_range() -> None:
    assert _clamp_score(-1) is None
    assert _clamp_score(10) is None
    assert _clamp_score(None) is None
    assert _clamp_score("abc") is None


def test_normalize_fills_missing_overall_band_with_mean() -> None:
    """LLM 没填 overall_band → 自动均值。"""
    svc = SpeakingGradeService(llm_client=None)
    svc._llm_service = None
    raw = {
        "scores": {
            "fluency": 7, "lexical": 6,
            "grammar": 8, "pronunciation": 7,
            # overall_band 故意缺失
        },
        "word_errors": [{"original": "x", "correction": "y", "context": ""}],
        "grammar_errors": "not-a-list",  # 非法类型
        "highlights": [1, 2, 3],  # int 而非 str
        "suggestions": ["valid"],
    }
    out = svc._normalize_payload(raw)
    # mean = (7+6+8+7)/4 = 7.0
    assert out["scores"]["overall_band"] == 7.0
    assert len(out["word_errors"]) == 1
    # grammar_errors 非 list → 清空
    assert out["grammar_errors"] == []
    # highlights 被强转 str
    assert out["highlights"] == ["1", "2", "3"]
    assert out["score_fallback"] is False


def test_normalize_rejects_out_of_range_scores() -> None:
    """某个维度分数越界 → 设为 None,overall 用剩下维度的均值。"""
    svc = SpeakingGradeService(llm_client=None)
    svc._llm_service = None
    raw = {
        "scores": {
            "fluency": 7, "lexical": 6,
            "grammar": 99,    # 越界
            "pronunciation": 7,
            # 故意不给 overall_band → 触发重算
        },
        "word_errors": [], "grammar_errors": [],
        "highlights": [], "suggestions": [],
    }
    out = svc._normalize_payload(raw)
    # grammar 越界被丢,overall 用剩余 (7+6+7)/3
    assert out["scores"]["grammar"] is None
    assert out["scores"]["overall_band"] == 6.5  # 20/3=6.67 → 6.5
    assert out["score_fallback"] is False