"""ReadingQuestionGenerator 单元测试（v3.8 P3.2 Sprint 2 新增）。

覆盖:
1. SECTION_PROFILES:4 个 Section 都有 profile
2. mock 路径(无 client):返回合规占位题
3. mock 路径:tfng → answer 是 T/F/NG,options=None
4. mock 路径:multiple_choice → 4 选项,answer A-D
5. mock 路径:summary/sentence_completion → options=None,answer 是单词
6. 真 LLM 路径:合规 JSON 数组 → 归一化结果
7. 真 LLM 路径:markdown 围栏 → 容错解析
8. 真 LLM 路径:LLM 失败 2 次 → mock 兜底
9. 真 LLM 路径:LLM 抛异常 → mock 兜底
10. 真 LLM 路径:返回 dict 而非 list → 归一化为 items
11. 归一化:tfng answer 'True' → 归一为 'T'
12. 归一化:tfng answer 'False' → 归一为 'F'
13. 归一化:缺 answer 的题被丢掉
14. 归一化:multiple_choice 缺 4 选项的题被丢掉
15. 归一化:question_type 非法 → 跳过
16. generate_full_set:一次返回多 section
"""
from __future__ import annotations

import json
from typing import Any

from ielts_buddy.services.reading_question_generator import (
    SECTION_PROFILES,
    ReadingQuestionGenerator,
)


# =============================================================
# Stub OpenAI-style client
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
    """支持按调用次数返回不同内容。"""

    def __init__(self, contents: list[str] | None = None) -> None:
        self._contents = contents or []
        self.call_count = 0

    @property
    def chat(self) -> Any:
        return _StubChat(self)


# =============================================================
# SECTION_PROFILES
# =============================================================


class TestSectionProfiles:
    def test_four_sections_defined(self) -> None:
        assert set(SECTION_PROFILES.keys()) == {"easy", "medium", "hard", "academic"}

    def test_each_section_has_required_fields(self) -> None:
        for sec, profile in SECTION_PROFILES.items():
            assert profile.section == sec
            assert profile.name
            assert profile.description
            assert profile.topics
            assert len(profile.word_count_range) == 2
            assert profile.word_count_range[0] < profile.word_count_range[1]
            assert profile.question_count >= 10

    def test_difficulty_increases_with_section(self) -> None:
        order = ["easy", "medium", "hard", "academic"]
        counts = [SECTION_PROFILES[s].question_count for s in order]
        # 题目数应该非递减
        assert counts == sorted(counts)


# =============================================================
# Mock 路径(无 LLM)
# =============================================================


class TestMockFallback:
    def test_mock_easy_returns_full_set(self) -> None:
        gen = ReadingQuestionGenerator(llm_client=None)
        out = gen.generate_section("easy")
        assert len(out) == SECTION_PROFILES["easy"].question_count
        for q in out:
            assert q["qid"]
            assert q["section"] == "easy"
            assert q["passage_text"]
            assert q["stem"]
            assert q["answer"]
            assert q["explanation"]

    def test_mock_tfng_has_null_options(self) -> None:
        gen = ReadingQuestionGenerator(llm_client=None)
        out = gen.generate_section("easy")
        tfng = [q for q in out if q["question_type"] == "tfng"]
        assert len(tfng) >= 1
        for q in tfng:
            assert q["options"] is None
            assert q["answer"] in ("T", "F", "NG")

    def test_mock_mc_has_four_options(self) -> None:
        gen = ReadingQuestionGenerator(llm_client=None)
        out = gen.generate_section("easy")
        mc = [q for q in out if q["question_type"] == "multiple_choice"]
        assert len(mc) >= 1
        for q in mc:
            assert q["options"] is not None
            assert len(q["options"]) == 4
            assert q["answer"] in ("A", "B", "C", "D")

    def test_mock_summary_and_sentence_have_null_options(self) -> None:
        gen = ReadingQuestionGenerator(llm_client=None)
        out = gen.generate_section("medium")
        summary = [q for q in out if q["question_type"] == "summary"]
        sent = [q for q in out if q["question_type"] == "sentence_completion"]
        assert len(summary) >= 1
        assert len(sent) >= 1
        for q in summary + sent:
            assert q["options"] is None
            # answer 是单词或短语,不是 A/B/C/D
            assert q["answer"] not in ("A", "B", "C", "D")

    def test_unknown_section_returns_empty(self) -> None:
        gen = ReadingQuestionGenerator(llm_client=None)
        out = gen.generate_section("xx_unknown")
        assert out == []


# =============================================================
# 真 LLM 路径
# =============================================================


def _build_valid_items(section: str, count: int) -> list[dict]:
    """生成合规的 LLM 返回 JSON。"""
    items = []
    # 至少覆盖 5 种题型
    qtypes = ["tfng", "multiple_choice", "matching", "summary", "sentence_completion"]
    for i in range(1, count + 1):
        qtype = qtypes[(i - 1) % len(qtypes)]
        passage_num = ((i - 1) // 5) + 1
        if passage_num > 3:
            passage_num = 3
        item: dict[str, Any] = {
            "qid": i,
            "passage_number": passage_num,
            "title": f"Title for Q{i}",
            "topic": SECTION_PROFILES[section].topics[0],
            "question_type": qtype,
            "word_count": 700,
            "passage_text": (
                f"This is a passage about topic. "
                f"It discusses several points relevant to question {i}. "
                f"The conclusion summarizes the main idea."
            ),
            "stem": f"Question {i}: What does the passage say?",
            "answer": "T" if qtype == "tfng" else (
                "A" if qtype in ("multiple_choice", "matching") else "key_term"
            ),
            "explanation": f"Explanation for Q{i}.",
            "source_line": i,
        }
        if qtype in ("multiple_choice", "matching"):
            item["options"] = ["A opt", "B opt", "C opt", "D opt"]
        else:
            item["options"] = None
        items.append(item)
    return items


class TestRealLLMPath:
    def test_llm_returns_valid_json_array(self) -> None:
        valid = _build_valid_items("easy", SECTION_PROFILES["easy"].question_count)
        client = _StubClient(contents=[json.dumps(valid)])
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("easy")
        assert len(out) == SECTION_PROFILES["easy"].question_count

    def test_llm_returns_markdown_fence(self) -> None:
        valid = _build_valid_items("medium", SECTION_PROFILES["medium"].question_count)
        content = "```json\n" + json.dumps(valid) + "\n```"
        client = _StubClient(contents=[content])
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("medium")
        assert len(out) == SECTION_PROFILES["medium"].question_count

    def test_llm_returns_think_block_then_json(self) -> None:
        valid = _build_valid_items("hard", SECTION_PROFILES["hard"].question_count)
        content = "<think>思考中</think>\n" + json.dumps(valid)
        client = _StubClient(contents=[content])
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("hard")
        assert len(out) == SECTION_PROFILES["hard"].question_count

    def test_llm_fails_twice_falls_back_to_mock(self) -> None:
        client = _StubClient(contents=["not json", "still not json"])
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("academic")
        # 兜底 mock
        assert len(out) == SECTION_PROFILES["academic"].question_count

    def test_llm_returns_dict_instead_of_list_recovers(self) -> None:
        """LLM 偶尔返回 dict(以 qid 为 key),容忍这种情况。"""
        valid = _build_valid_items("easy", SECTION_PROFILES["easy"].question_count)
        wrapped = {str(item["qid"]): item for item in valid}
        client = _StubClient(contents=[json.dumps(wrapped)])
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("easy")
        assert len(out) >= SECTION_PROFILES["easy"].question_count - 1

    def test_llm_raises_exception_falls_back_to_mock(self) -> None:
        """模拟网络异常 → 走 mock。"""

        class _RaisingClient(_StubClient):
            class _Completions:
                def __init__(self, outer): self._outer = outer

                def create(self, **kwargs):
                    raise RuntimeError("network down")

            class _Chat:
                def __init__(self, outer):
                    self.completions = _RaisingClient._Completions(outer)

            @property
            def chat(self):
                return _RaisingClient._Chat(self)

        client = _RaisingClient()
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("easy")
        # 走 mock
        assert len(out) == SECTION_PROFILES["easy"].question_count


# =============================================================
# 归一化
# =============================================================


class TestNormalization:
    def test_tfng_answer_normalizes_true_to_t(self) -> None:
        items = [{
            "qid": 1, "passage_number": 1, "title": "T",
            "topic": "Test", "question_type": "tfng",
            "word_count": 600, "passage_text": "passage text here",
            "stem": "Q1", "options": None,
            "answer": "True", "explanation": "ok", "source_line": 1,
        }, {
            "qid": 2, "passage_number": 1, "title": "F",
            "topic": "Test", "question_type": "tfng",
            "word_count": 600, "passage_text": "passage text here",
            "stem": "Q2", "options": None,
            "answer": "False", "explanation": "ok", "source_line": 2,
        }, {
            "qid": 3, "passage_number": 1, "title": "NG",
            "topic": "Test", "question_type": "tfng",
            "word_count": 600, "passage_text": "passage text here",
            "stem": "Q3", "options": None,
            "answer": "NG", "explanation": "ok", "source_line": 3,
        }]
        client = _StubClient(contents=[json.dumps(items)])
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("easy")
        answers = [q["answer"] for q in out if q["question_type"] == "tfng"]
        assert "T" in answers
        assert "F" in answers
        assert "NG" in answers

    def test_drops_questions_missing_answer(self) -> None:
        items = _build_valid_items("easy", SECTION_PROFILES["easy"].question_count)
        items[0]["answer"] = ""  # 空答案
        client = _StubClient(contents=[json.dumps(items)])
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("easy")
        assert len(out) == SECTION_PROFILES["easy"].question_count - 1

    def test_drops_mc_with_wrong_options_count(self) -> None:
        items = _build_valid_items("easy", SECTION_PROFILES["easy"].question_count)
        # 找一个 multiple_choice
        for it in items:
            if it["question_type"] == "multiple_choice":
                it["options"] = ["A", "B"]  # 只 2 个
                break
        client = _StubClient(contents=[json.dumps(items)])
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("easy")
        # 至少掉 1 道
        assert len(out) <= SECTION_PROFILES["easy"].question_count - 1

    def test_drops_questions_with_invalid_qtype(self) -> None:
        items = _build_valid_items("easy", SECTION_PROFILES["easy"].question_count)
        items[0]["question_type"] = "totally_invalid"
        client = _StubClient(contents=[json.dumps(items)])
        gen = ReadingQuestionGenerator(llm_client=client)
        out = gen.generate_section("easy")
        assert len(out) == SECTION_PROFILES["easy"].question_count - 1


# =============================================================
# generate_full_set
# =============================================================


class TestFullSet:
    def test_full_set_returns_all_four_sections(self) -> None:
        gen = ReadingQuestionGenerator(llm_client=None)
        out = gen.generate_full_set()
        assert set(out.keys()) == {"easy", "medium", "hard", "academic"}
        for sec, items in out.items():
            assert len(items) == SECTION_PROFILES[sec].question_count

    def test_full_set_with_subset(self) -> None:
        gen = ReadingQuestionGenerator(llm_client=None)
        out = gen.generate_full_set(sections=["easy", "hard"])
        assert set(out.keys()) == {"easy", "hard"}
