"""ListeningQuestionGenerator 单元测试（v3.7 P2 Sprint 2 新增）。

覆盖:
1. mock 路径:无 client → 返回占位题(每 Section 必填字段)
2. mock 路径:form_completion → options=None
3. mock 路径:multiple_choice → options=[A,B,C,D]
4. 真 LLM 路径:mock client 返回合规 JSON 数组 → 归一化结果
5. 真 LLM 路径:LLM 返回 markdown 围栏 → 容错解析
6. 真 LLM 路径:LLM 失败 2 次 → mock 兜底
7. SECTION_PROFILES:4 个 Section 都有 profile
"""
from __future__ import annotations

import json
from typing import Any

from ielts_buddy.services.listening_question_generator import (
    SECTION_PROFILES,
    ListeningQuestionGenerator,
)


# =============================================================
# Stub:mock OpenAI client
# =============================================================


class _StubMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubChoice:
    def __init__(self, content: str) -> None:
        self.message = _StubMessage(content)


class _StubResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_StubChoice(content)]


class _StubCompletions:
    def __init__(self, outer: "_StubClient") -> None:
        self._outer = outer

    def create(self, **kwargs) -> _StubResponse:
        self._outer.call_count += 1
        content = self._outer._contents[self._outer.call_count - 1]
        return _StubResponse(content)


class _StubChat:
    def __init__(self, outer: "_StubClient") -> None:
        self.completions = _StubCompletions(outer)


class _StubClient:
    """支持按调用次数返回不同内容 + 模拟失败。"""

    def __init__(
        self,
        contents: list[str] | None = None,
        raise_on_calls: list[int] | None = None,
    ) -> None:
        self._contents = contents or []
        self._raise_on_calls = raise_on_calls or []
        self.call_count = 0

    @property
    def chat(self) -> Any:
        return _StubChat(self)


# =============================================================
# SECTION_PROFILES
# =============================================================


class TestSectionProfiles:
    def test_four_sections_defined(self) -> None:
        assert set(SECTION_PROFILES.keys()) == {1, 2, 3, 4}

    def test_each_section_has_required_fields(self) -> None:
        for sec, profile in SECTION_PROFILES.items():
            assert profile.section == sec
            assert profile.name
            assert profile.description
            assert profile.question_types
            assert profile.question_count >= 4


# =============================================================
# Mock 路径(无 LLM)
# =============================================================


class TestMockFallback:
    def test_mock_section1_returns_form_completion(self) -> None:
        gen = ListeningQuestionGenerator(llm_client=None)
        # Section 1 第一种题型是 form_completion
        out = gen.generate_section(1)
        assert len(out) == SECTION_PROFILES[1].question_count
        # 至少有 1 道 form_completion
        fc = [q for q in out if q["question_type"] == "form_completion"]
        assert len(fc) >= 1
        for q in fc:
            assert q["options"] is None
            assert q["stem"]
            assert q["answer"]
            assert q["transcript"]

    def test_mock_section2_returns_multiple_choice(self) -> None:
        gen = ListeningQuestionGenerator(llm_client=None)
        out = gen.generate_section(2)
        assert len(out) == SECTION_PROFILES[2].question_count
        # 全部 options 都是 4 个
        for q in out:
            assert q["options"] is not None
            assert len(q["options"]) == 4
            assert q["answer"] in ("A", "B", "C", "D")

    def test_mock_unknown_section_returns_empty(self) -> None:
        gen = ListeningQuestionGenerator(llm_client=None)
        out = gen.generate_section(99)
        assert out == []


# =============================================================
# 真 LLM 路径
# =============================================================


def _build_valid_questions(section: int = 1) -> list[dict]:
    profile = SECTION_PROFILES[section]
    items: list[dict] = []
    for i in range(1, profile.question_count + 1):
        if profile.question_types[0] == "form_completion":
            items.append({
                "qid": i,
                "section": section,
                "scenario": "Test scenario",
                "question_type": "form_completion",
                "stem": f"Q{i} The price is _____.",
                "options": None,
                "answer": "fifteen",
                "explanation": "Because the speaker said fifteen.",
                "transcript": f"This is the transcript for question {i}.",
            })
        else:
            items.append({
                "qid": i,
                "section": section,
                "scenario": "Test scenario",
                "question_type": profile.question_types[0],
                "stem": f"Q{i} Which option?",
                "options": ["A opt", "B opt", "C opt", "D opt"],
                "answer": "A",
                "explanation": "Option A is correct.",
                "transcript": f"This is the transcript for question {i}.",
            })
    return items


class TestRealLLMPath:
    def test_llm_returns_valid_json_array(self) -> None:
        valid = _build_valid_questions(1)
        client = _StubClient(contents=[json.dumps(valid)])
        gen = ListeningQuestionGenerator(llm_client=client)
        out = gen.generate_section(1)
        assert len(out) == SECTION_PROFILES[1].question_count
        for q in out:
            assert q["stem"]
            assert q["answer"]
            assert q["transcript"]

    def test_llm_returns_markdown_fence(self) -> None:
        valid = _build_valid_questions(2)
        # 用 markdown 围栏 + 前置文字
        content = "Sure, here are the questions:\n```json\n" + \
                  json.dumps(valid) + "\n```\n"
        client = _StubClient(contents=[content])
        gen = ListeningQuestionGenerator(llm_client=client)
        out = gen.generate_section(2)
        assert len(out) == SECTION_PROFILES[2].question_count
        # Section 2 是 multiple_choice → answer 必须 A/B/C/D
        for q in out:
            assert q["answer"] in ("A", "B", "C", "D")
            assert q["options"] is not None
            assert len(q["options"]) == 4

    def test_llm_fails_twice_falls_back_to_mock(self) -> None:
        # 两次都返回非 JSON
        client = _StubClient(contents=["not json", "still not json"])
        gen = ListeningQuestionGenerator(llm_client=client)
        out = gen.generate_section(3)
        # 兜底 mock
        assert len(out) == SECTION_PROFILES[3].question_count
        assert out[0]["scenario"]  # mock 也填了 scenario

    def test_llm_returns_think_block_then_json(self) -> None:
        valid = _build_valid_questions(4)
        content = "<think>思考中</think>\n" + json.dumps(valid)
        client = _StubClient(contents=[content])
        gen = ListeningQuestionGenerator(llm_client=client)
        out = gen.generate_section(4)
        assert len(out) == SECTION_PROFILES[4].question_count

    def test_llm_returns_dict_instead_of_list_recovers(self) -> None:
        """LLM 偶尔返回 dict 而非 list,容忍这种情况。"""
        valid = _build_valid_questions(1)
        # 把 list 包成 dict:key 是 qid,value 是 item
        wrapped = {str(item["qid"]): item for item in valid}
        client = _StubClient(contents=[json.dumps(wrapped)])
        gen = ListeningQuestionGenerator(llm_client=client)
        out = gen.generate_section(1)
        # items 仍能拿到
        assert len(out) >= 1

    def test_llm_raises_exception_falls_back(self) -> None:
        """模拟网络异常 → 走 mock。"""
        # raise_on_calls=[1, 2] → 两次都抛
        class _RaisingStubClient(_StubClient):
            class _Completions:
                def __init__(self, outer): self._outer = outer
                def create(self, **kwargs):
                    raise RuntimeError("network down")

            class _Chat:
                def __init__(self, outer):
                    self.completions = _RaisingStubClient._Completions(outer)

            @property
            def chat(self):
                return _RaisingStubClient._Chat(self)

        client = _RaisingStubClient()
        gen = ListeningQuestionGenerator(llm_client=client)
        out = gen.generate_section(1)
        # 走 mock
        assert len(out) == SECTION_PROFILES[1].question_count


# =============================================================
# 归一化校验
# =============================================================


class TestNormalization:
    def test_drops_questions_missing_answer(self) -> None:
        bad = _build_valid_questions(2)
        bad[0]["answer"] = ""  # 空答案
        client = _StubClient(contents=[json.dumps(bad)])
        gen = ListeningQuestionGenerator(llm_client=client)
        out = gen.generate_section(2)
        # 第一条被丢掉,返回 N-1
        assert len(out) == SECTION_PROFILES[2].question_count - 1

    def test_drops_questions_with_wrong_options_count(self) -> None:
        bad = _build_valid_questions(2)
        bad[0]["options"] = ["A", "B"]  # 只 2 个选项
        client = _StubClient(contents=[json.dumps(bad)])
        gen = ListeningQuestionGenerator(llm_client=client)
        out = gen.generate_section(2)
        assert len(out) == SECTION_PROFILES[2].question_count - 1

    def test_normalizes_invalid_qtype_to_first_allowed(self) -> None:
        bad = _build_valid_questions(2)
        bad[0]["question_type"] = "totally_invalid"
        client = _StubClient(contents=[json.dumps(bad)])
        gen = ListeningQuestionGenerator(llm_client=client)
        out = gen.generate_section(2)
        # question_type 归类为第一个允许的(multiple_choice)
        assert out[0]["question_type"] == "multiple_choice"


# =============================================================
# generate_full_set
# =============================================================


class TestGenerateFullSet:
    def test_generate_all_four_sections(self) -> None:
        gen = ListeningQuestionGenerator(llm_client=None)
        out = gen.generate_full_set()
        # 4 个 Section 都应有题
        assert set(out.keys()) == {1, 2, 3, 4}
        for sec, items in out.items():
            assert len(items) == SECTION_PROFILES[sec].question_count