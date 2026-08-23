"""Pydantic 数据模型定义"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class Word(BaseModel):
    """词库单词模型"""

    id: Optional[int] = None
    word: str
    phonetic: str = ""
    meaning: str
    pos: str = ""  # 词性: n., v., adj., adv. 等
    band: int = Field(ge=5, le=9)  # 雅思 Band 5-9
    topic: str = ""  # 主题: education, environment, ...
    example: str = ""  # 英文例句
    example_cn: str = ""  # 例句中文翻译
    collocations: list[str] = Field(default_factory=list)  # 常用搭配
    synonyms: list[str] = Field(default_factory=list)  # 同义词
    etymology: str = ""  # 词根词缀/助记
    is_custom: bool = False  # 是否用户自定义
    created_at: Optional[str] = None

    def collocations_json(self) -> str:
        """序列化搭配为 JSON 字符串"""
        return json.dumps(self.collocations, ensure_ascii=False)

    def synonyms_json(self) -> str:
        """序列化同义词为 JSON 字符串"""
        return json.dumps(self.synonyms, ensure_ascii=False)

    @staticmethod
    def parse_json_field(value: str | None) -> list[str]:
        """从 JSON 字符串解析列表字段"""
        if not value:
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []


class LearningRecord(BaseModel):
    """学习记录模型"""

    id: Optional[int] = None
    user_id: int = 1  # 所属用户（v2.2 W1.2 新增；单机模式固定 1，联网模式为 users.id）
    word_id: int
    memory_level: int = Field(default=0, ge=0, le=6)  # 记忆等级 0-6
    next_review: Optional[str] = None  # ISO 日期 YYYY-MM-DD
    learn_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    first_learned: Optional[str] = None  # ISO datetime
    last_reviewed: Optional[str] = None  # ISO datetime
    is_starred: bool = False
    is_difficult: bool = False


class TestSession(BaseModel):
    """测试会话模型"""

    id: Optional[int] = None
    user_id: int = 1  # 所属用户（v2.2 W1.2 新增）
    session_id: str
    test_date: str  # ISO datetime
    test_mode: str  # spelling / meaning / choice / context
    total_count: int
    correct_count: int
    wrong_words: list[str] = Field(default_factory=list)  # 错误的单词列表
    duration: Optional[int] = None  # 秒
    band_filter: Optional[int] = None
    topic_filter: Optional[str] = None

    def wrong_words_json(self) -> str:
        """序列化错误单词为 JSON 字符串"""
        return json.dumps(self.wrong_words, ensure_ascii=False)

    @property
    def accuracy(self) -> float:
        """正确率"""
        if self.total_count == 0:
            return 0.0
        return self.correct_count / self.total_count


class DailySummary(BaseModel):
    """每日学习摘要模型"""

    id: Optional[int] = None
    user_id: int = 1  # 所属用户（v2.2 W1.2 新增）
    date: str  # YYYY-MM-DD
    new_words: int = 0
    reviewed_words: int = 0
    test_accuracy: Optional[float] = None
    study_minutes: int = 0
    streak_days: int = 0


class StudyPlan(BaseModel):
    """学习计划模型"""

    user_id: int = 1  # 所属用户（v2.2 W1.2 新增；单机模式默认 1）
    target_band: int = Field(default=7, ge=5, le=9)
    daily_new: int = Field(default=30, ge=1)
    exam_date: Optional[str] = None  # YYYY-MM-DD
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ExamQuestion(BaseModel):
    """模拟考试单题模型"""

    index: int  # 题号 (0-based)
    word: str  # 原始单词
    mode: str  # "en2zh" 或 "zh2en"
    prompt: str  # 题目显示文本
    answer: str  # 正确答案
    band: int = 5  # 单词 band 等级
    user_answer: Optional[str] = None  # 用户的回答
    is_correct: Optional[bool] = None  # 是否正确


class ExamSession(BaseModel):
    """模拟考试会话模型"""

    id: str  # UUID
    user_id: int = 1  # 所属用户（v2.2 W1.2 新增）
    questions: list[ExamQuestion] = Field(default_factory=list)
    time_limit: int = 20  # 分钟
    started_at: str = ""  # ISO datetime
    finished_at: Optional[str] = None  # ISO datetime
    band_filter: Optional[int] = None


class ExamReport(BaseModel):
    """模拟考试报告模型"""

    session_id: str
    user_id: int = 1  # 所属用户（v2.2 W1.2 新增）
    score: int = 0
    total: int = 0
    accuracy: float = 0.0
    band_breakdown: dict[int, dict[str, int]] = Field(default_factory=dict)
    weak_words: list[str] = Field(default_factory=list)
    duration: int = 0  # 秒
    finished_at: str = ""


class PersonalWord(BaseModel):
    """个人词库单词模型"""

    id: Optional[int] = None
    user_id: int = 1  # 所属用户（v2.2 W1.2 新增）
    word: str
    phonetic: str = ""
    meaning: str = ""
    pos: str = ""
    band: int = Field(default=5, ge=5, le=9)
    topic: str = ""
    example: str = ""
    example_cn: str = ""
    note: str = ""  # 用户笔记
    source: str = "manual"  # manual / quiz_mistake / grading / import
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class VocabCategory(BaseModel):
    """词库分类模型"""

    id: Optional[int] = None
    user_id: int = 1  # 所属用户（v2.2 W1.2 新增；user_id=0 为系统模板）
    name: str
    description: str = ""
    is_system: bool = False  # 系统内置分类不可删除
    word_count: int = 0
    created_at: Optional[str] = None


class GradeDimension(BaseModel):
    """写作批改单维度评分"""

    score: float = Field(ge=1.0, le=9.0)
    comment: str = ""


class SentenceAnnotation(BaseModel):
    """句级标注：标记单句的具体问题"""

    sentence_index: int  # 句子序号（从 0 开始）
    original: str  # 原句
    issue_type: str  # grammar / vocabulary / coherence / style
    severity: str = "minor"  # minor / major / critical
    comment: str  # 问题说明（中文）
    suggestion: str = ""  # 修改建议（英文）


class ParagraphAnalysis(BaseModel):
    """段落结构分析"""

    para_index: int  # 段落序号（从 0 开始）
    role: str  # introduction / body / conclusion
    has_topic_sentence: bool = False
    structure_score: float = Field(default=5.0, ge=1.0, le=9.0)
    cohesion_devices: list[str] = Field(default_factory=list)  # 检测到的衔接词
    comment: str = ""


class GradeResult(BaseModel):
    """AI 写作批改结果"""

    user_id: int = 1  # 所属用户（v2.2 W1.2 新增）
    overall_score: float = Field(ge=1.0, le=9.0)
    task_response: GradeDimension
    coherence: GradeDimension
    lexical_resource: GradeDimension
    grammar: GradeDimension
    suggestions: list[str] = Field(default_factory=list)
    rewrite: str = ""
    essay_text: str = ""
    topic: str = ""
    task_type: str = "task2"  # task1_academic / task1_general / task2
    annotations: list[SentenceAnnotation] = Field(default_factory=list)
    paragraphs: list[ParagraphAnalysis] = Field(default_factory=list)
    error_summary: dict[str, int] = Field(default_factory=dict)  # {"grammar": 5, ...}
    graded_at: Optional[str] = None


class ArticleWord(BaseModel):
    """文章生词标注（Article 分析产出）。

    - word: 单词原形
    - phonetic: 音标（来自内置词库或空）
    - pos: 词性
    - meaning_cn: 中文释义（来自内置词库或 LLM）
    - band: band 等级（内置词库命中才有，1-9）
    - context_sentence: 出现在文章中的原句
    - synonyms: 同义词
    - antonyms: 反义词
    - near_synonyms: 近义词
    - context_meaning: 上下文含义
    - auto_marked: True=LLM/词库自动标注，False=用户手动勾选
    - analysis_source: llm / builtin / fallback
    """

    word: str
    phonetic: str = ""
    pos: str = ""
    meaning_cn: str = ""
    band: Optional[int] = None
    context_sentence: str = ""
    synonyms: list[str] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)
    near_synonyms: list[str] = Field(default_factory=list)
    context_meaning: str = ""
    auto_marked: bool = True
    analysis_source: str = "fallback"  # builtin / llm / fallback


class Article(BaseModel):
    """文章翻译记录（一篇文章的所有元数据）。"""

    id: Optional[int] = None
    user_id: int = 1
    title: str = ""
    source_text: str = ""           # 英文原文
    translation: str = ""           # 中文翻译
    word_count: int = 0             # 原文单词数
    diff_words_json: str = "[]"     # 生词分析结果 JSON（ArticleWord 列表）
    translation_source: str = "llm"  # llm / mock / error
    analysis_source: str = "fallback"  # llm / fallback
    created_at: Optional[str] = None


class TypingRecord(BaseModel):
    """机考打字练习记录（一次完整会话）。

    - mode: "words" / "sentences" / "passage"，与素材粒度对应
    - prompt_text: 用户要打的原文（含空格）
    - typed_text: 用户的实际输入（可能提前结束）
    - duration_sec: 从开始到结束/提交的秒数
    - wpm: 单词/分钟；按标准 5 字符 = 1 词 计算
    - accuracy: 准确率（0-1），按字符匹配（correct_chars / total_chars）
    - error_count: 错误字符数（typed vs prompt 对齐后不一致位置数）
    - completed: 用户是否完成整段（False=中途放弃）
    """

    id: Optional[int] = None
    user_id: int = 1
    mode: str = "words"             # words / sentences / passage
    prompt_text: str
    typed_text: str = ""
    duration_sec: int = Field(default=0, ge=0, le=3600)
    wpm: float = Field(default=0.0, ge=0.0, le=300.0)
    accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    error_count: int = 0
    total_chars: int = 0
    completed: bool = True
    created_at: Optional[str] = None


class FocusSession(BaseModel):
    """番茄钟 / 专注会话记录（v3.6 新增）。

    - activity: 专注类型标签，对齐现有功能模块
        ``vocab`` (背单词) / ``writing`` (写作) / ``exam`` (模考)
        ``typing`` (打字) / ``reading`` (阅读) / ``other``
    - planned_sec: 计划时长（秒），默认 25 min = 1500
    - duration_sec: 实际专注时长；可小于 planned_sec（中途放弃）
    - interrupted: True = 中途放弃 / False = 正常完成
    - note: 用户自定义备注（可选）

    设计要点：
      - 不算 WPM / accuracy（与 typing_history 区分），只记"专注时长 + 活动类型"
      - 支持自定义时长（短休 5min / 长休 15min / 任意值），不限 25min
      - 跨设备同步（v3.6：已加进 SYNC_TABLES，include_id=True）
    """

    id: Optional[int] = None
    user_id: int = 1
    activity: str = "other"          # vocab / writing / exam / typing / reading / other
    planned_sec: int = Field(default=1500, ge=60, le=7200)   # 1min ~ 2h
    duration_sec: int = Field(default=0, ge=0, le=7200)
    interrupted: bool = False
    note: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    created_at: Optional[str] = None
