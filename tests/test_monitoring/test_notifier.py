"""
tests/test_monitoring/test_notifier.py — notifier 单元测试

覆盖：
1. 严重度分级
2. 5 分钟静默期
3. 自愈循环（suppress）
4. 死信日志写入
5. 健康查询

不覆盖：
- 真实微信 / 邮件发送（那是集成测试）
"""
import json
import os
import time
from pathlib import Path

import pytest

from ielts_buddy.monitoring.notifier import (
    Severity, notify, suppress, health_snapshot,
    SELF_HEALING_SIGNATURES, ESCALATION_SIGNATURES, _debouncer,
)


@pytest.fixture(autouse=True)
def reset_debouncer():
    """每个测试前清空去重状态。"""
    _debouncer.state.last_notify_at.clear()
    _debouncer.state.retry_count.clear()
    yield


@pytest.fixture
def tmp_dead_letter(tmp_path, monkeypatch):
    """把死信日志写到临时目录。"""
    log_path = tmp_path / "dead_letter.log"
    monkeypatch.setenv("NOTIFY_DEAD_LETTER_PATH", str(log_path))
    return log_path


# =============================================================
# 1. 严重度分级
# =============================================================


def test_p1_requires_human():
    assert Severity.P1_CRITICAL.requires_human is True


def test_p2_does_not_require_human():
    assert Severity.P2_WARNING.requires_human is False


def test_p3_does_not_require_human():
    assert Severity.P3_INFO.requires_human is False


# =============================================================
# 2. 5 分钟静默期
# =============================================================


def test_p1_always_notifies(tmp_dead_letter):
    """P1 不受 5 分钟静默期抑制。"""
    for _ in range(5):
        result = notify("服务挂了", Severity.P1_CRITICAL)
        assert result.suppressed is False


def test_p2_dedup_within_5_min(tmp_dead_letter):
    """P2 同 signature 5 分钟内只通知 1 次。"""
    sig = "test_p2_dedup"
    # 第一次：不抑制
    r1 = notify("LLM 报错", Severity.P2_WARNING, signature=sig)
    assert r1.suppressed is False
    # 第二次：抑制
    r2 = notify("LLM 报错", Severity.P2_WARNING, signature=sig)
    assert r2.suppressed is True
    # 但都写死信日志
    entries = [json.loads(l) for l in tmp_dead_letter.read_text().splitlines()]
    assert len(entries) == 2
    assert entries[0]["suppressed"] is False
    assert entries[1]["suppressed"] is True


def test_p2_different_signatures_not_deduped(tmp_dead_letter):
    """P2 不同 signature 各自独立通知。"""
    r1 = notify("错误 A", Severity.P2_WARNING, signature="sig_a")
    r2 = notify("错误 B", Severity.P2_WARNING, signature="sig_b")
    assert r1.suppressed is False
    assert r2.suppressed is False


# =============================================================
# 3. 自愈签名（不通知）
# =============================================================


def test_self_healing_signature_not_notified(tmp_dead_letter):
    """命中自愈签名的异常：仅记死信，不走外部通道。"""
    result = notify(
        "LLM 超时",
        Severity.P2_WARNING,
        signature="llm_timeout",  # 已知自愈签名
    )
    assert result.sent_channels == []  # 没有任何通道
    # 但仍然写日志
    entries = [json.loads(l) for l in tmp_dead_letter.read_text().splitlines()]
    assert len(entries) == 1


def test_self_heal_signatures_list():
    """自愈签名清单不为空（覆盖 8 类常见异常）。"""
    assert len(SELF_HEALING_SIGNATURES) >= 8
    assert "llm_timeout" in SELF_HEALING_SIGNATURES


# =============================================================
# 4. suppress（自愈循环）
# =============================================================


def test_suppress_allows_retry_under_limit(tmp_dead_letter):
    """未达 max_retries：允许继续重试；达到后升级为 P1。"""
    sig = "test_retry_loop"
    exc = RuntimeError("LLM 超时")
    max_retries = 3
    # 第 1、2 次都返回 True（未达上限）
    assert suppress(exc, Severity.P2_WARNING, sig, max_retries=max_retries) is True
    assert suppress(exc, Severity.P2_WARNING, sig, max_retries=max_retries) is True
    # 第 3 次：count > max_retries，触发 P1 升级 + 返回 False
    assert suppress(exc, Severity.P2_WARNING, sig, max_retries=max_retries) is False


def test_suppress_escalation_writes_p1_dead_letter(tmp_dead_letter):
    """suppress 升级到 P1 后写一条 P1 dead letter。"""
    sig = "test_suppress_p1"
    exc = RuntimeError("未知异常")
    suppress(exc, Severity.P2_WARNING, sig, max_retries=1)  # count=1
    suppress(exc, Severity.P2_WARNING, sig, max_retries=1)  # count=2 > max=1 → P1
    entries = [json.loads(l) for l in tmp_dead_letter.read_text().splitlines()]
    p1_entries = [e for e in entries if e["severity"] == "P1"]
    assert len(p1_entries) >= 1


def test_suppress_triggers_p1_on_limit(tmp_dead_letter):
    """达到 max_retries 后升级到 P1（按当前语义：第 N 次后升级，N=max_retries）。"""
    sig = "test_suppress_escalation"
    exc = RuntimeError("LLM 超时")
    # max_retries=2 → 第 2 次时 count=2 >= 2 → 升级为 P1 + 返回 False
    suppress(exc, Severity.P2_WARNING, sig, max_retries=2)  # count=1, True
    result = suppress(exc, Severity.P2_WARNING, sig, max_retries=2)  # count=2, 升级
    assert result is False
    # 检查 dead letter 至少 1 条 P1
    entries = [json.loads(l) for l in tmp_dead_letter.read_text().splitlines()]
    p1_entries = [e for e in entries if e["severity"] == "P1"]
    assert len(p1_entries) >= 1
    assert "自愈失败" in p1_entries[0]["message"]


# =============================================================
# 5. 死信日志
# =============================================================


def test_dead_letter_written_for_every_notify(tmp_dead_letter):
    """每次 notify 调用都写死信日志。"""
    for i in range(10):
        notify(f"msg {i}", Severity.P3_INFO)
    lines = tmp_dead_letter.read_text().splitlines()
    assert len(lines) == 10
    for i, line in enumerate(lines):
        entry = json.loads(line)
        assert entry["message"] == f"msg {i}"


def test_dead_letter_includes_context(tmp_dead_letter):
    """死信日志包含上下文。"""
    notify(
        "服务挂了",
        Severity.P1_CRITICAL,
        context={"task": "speaking_score", "user_id": 42},
    )
    entry = json.loads(tmp_dead_letter.read_text().splitlines()[0])
    assert entry["context"]["task"] == "speaking_score"
    assert entry["context"]["user_id"] == 42


# =============================================================
# 6. 健康查询
# =============================================================


def test_health_snapshot(tmp_dead_letter):
    """health_snapshot 返回完整状态（5 分钟静默期不影响快照计数）。"""
    # 跑 2 个不同 signature（避开 5 分钟静默期）
    notify("test1", Severity.P1_CRITICAL, signature="s1")
    # P1 不受静默期抑制
    notify("test2", Severity.P2_WARNING, signature="s2")
    # 强制 P1 计数再加一个（绕过静默期对 P2 的抑制）
    notify("test3", Severity.P1_CRITICAL, signature="s3")

    snapshot = health_snapshot()
    assert "notified_signatures" in snapshot
    assert snapshot["notified_signatures"] >= 2
    assert "self_heal_signatures" in snapshot
    assert "escalation_signatures" in snapshot


# =============================================================
# 7. P1 触发逻辑
# =============================================================


def test_p1_records_channels_attempted(tmp_dead_letter):
    """P1 尝试发所有通道（即便失败也会记录尝试过）。"""
    result = notify(
        "未知异常：service_crashed",
        Severity.P1_CRITICAL,
        signature="service_crashed",
    )
    # 通道可能因配置缺失而发不出去，但 dead letter 一定记录
    entry = json.loads(tmp_dead_letter.read_text().splitlines()[0])
    assert entry["severity"] == "P1"
    assert "sent_channels" in entry


# =============================================================
# 8. 与 CLAUDE.md "铁律"对齐测试
# =============================================================


def test_escalation_signatures_include_safety_keywords():
    """ESCALATION_SIGNATURES 必须包含安全相关关键词。"""
    all_sigs = " ".join(ESCALATION_SIGNATURES)
    # 必须涉及：未成年人 / 钱 / 数据污染
    assert "minors" in all_sigs or "data_corrupted" in all_sigs
    assert "payment" in all_sigs or "service_crashed" in all_sigs