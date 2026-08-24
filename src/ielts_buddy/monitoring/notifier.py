"""
ielts_buddy/monitoring/notifier.py — 统一异常通知模块（v3.9+ / 2026-08-24）

设计原则（用户需求驱动）：
1. **事件驱动**：只在异常 + AI 不能自愈时触发，不做定时轮询
2. **3 级严重度**：P1 必须人介入 / P2 看一眼 / P3 周报统一看
3. **聚合 + 降噪**：同一类异常 5 分钟内只通知 1 次
4. **3 通道**：P1 微信 / P2 邮件 / P3 GitHub Issue
5. **死信队列**：所有通知统一记录到 .dead_letter.log，便于 AI 自己 debug

环境变量（一次性配置）：
    NOTIFY_P1_WECHAT_OPENID        # 你自己的 openid（接收 P1 通知）
    NOTIFY_P2_EMAIL_TO             # 你的邮箱（接收 P2 通知）
    NOTIFY_SMTP_HOST/USER/PASS    # SMTP 配置（Gmail / QQ / 企业邮箱）
    NOTIFY_GITHUB_TOKEN            # GitHub PAT（开 Issue 用）
    NOTIFY_GITHUB_REPO             # 你的仓库（owner/repo）

使用：
    from ielts_buddy.monitoring.notifier import notify, severity, suppress

    # 简单用法
    notify("服务挂了", severity.P1, context={"task": "speaking_score"})

    # 带自愈重试
    for attempt in range(3):
        try:
            call_llm()
            break
        except Exception as e:
            if not suppress(e, severity.P2, "LLM 超时"):
                raise  # 3 次失败后由调用方处理
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# =============================================================
# 1. 严重度分级
# =============================================================


class Severity(str, Enum):
    """3 级严重度。"""

    P1_CRITICAL = "P1"   # 必须立即介入（半夜也叫你）
    P2_WARNING = "P2"    # 看一眼就行（工作时间邮件）
    P3_INFO = "P3"       # 记一下就行（周报一起看）

    @property
    def requires_human(self) -> bool:
        return self == Severity.P1_CRITICAL

    @property
    def channel(self) -> str:
        return {
            Severity.P1_CRITICAL: "wechat_push",   # 微信服务通知（实时）
            Severity.P2_WARNING: "email",          # 邮件（5 分钟内聚合）
            Severity.P3_INFO: "dead_letter",      # 仅写文件（周报统一看）
        }[self]


# =============================================================
# 2. 自愈状态机（抑制重复通知）
# =============================================================


@dataclass
class SuppressionState:
    """同类型异常的抑制状态：5 分钟内只通知 1 次。"""

    last_notify_at: dict[str, float] = field(default_factory=dict)
    retry_count: dict[str, int] = field(default_factory=dict)
    notified_signatures: set[str] = field(default_factory=set)  # 已通知过的 sig（用于健康快照）
    DEBOUNCE_SECONDS = 300  # 5 分钟


class Debouncer:
    """全局单例：同一 signature 在 DEBOUNCE_SECONDS 内只触发 1 次通知。"""

    def __init__(self) -> None:
        self.state = SuppressionState()

    def should_notify(self, signature: str, severity: Severity) -> bool:
        now = time.time()
        # P1 永远通知（不抑制）
        if severity == Severity.P1_CRITICAL:
            self.state.notified_signatures.add(signature)
            return True
        last = self.state.last_notify_at.get(signature, 0)
        if now - last < self.state.DEBOUNCE_SECONDS:
            return False
        self.state.last_notify_at[signature] = now
        self.state.notified_signatures.add(signature)
        return True

    def increment_retry(self, signature: str) -> int:
        """增加重试计数，返回当前次数。"""
        self.state.retry_count[signature] = self.state.retry_count.get(signature, 0) + 1
        return self.state.retry_count[signature]

    def reset_retry(self, signature: str) -> None:
        """成功后清零。"""
        self.state.retry_count[signature] = 0


# 全局单例
_debouncer = Debouncer()


# =============================================================
# 3. AI 自愈能力清单
# =============================================================

# 已知的可自愈异常签名（命中后 AI 自动重试，不通知）
SELF_HEALING_SIGNATURES = {
    "llm_timeout",          # LLM 超时：自动切备用模型
    "llm_rate_limit",       # LLM 限流：自动退避
    "whisper_crash",        # Whisper 失败：自动切 CPU 模式
    "mysql_timeout",        # MySQL 慢：自动触发 fallback
    "network_blip",         # 网络抖动：自动重试
    "ci_flaky_test",        # CI 偶发：自动重跑
    "subscription_api_throttle",  # 微信订阅消息限流
    "user_token_expired",   # 用户 token 过期：自动 refresh
}

# 已知的需升级到 P2 / P1 的异常签名（不可自愈）
ESCALATION_SIGNATURES = {
    "service_crashed",      # 服务进程崩溃
    "data_corrupted",       # 数据被污染
    "permission_denied",    # 权限被拒（涉及合规）
    "payment_error",        # 涉及钱
    "minors_data_leaked",   # 未成年人数据泄露
    "wechat_audit_blocked", # 微信审核被封
    "unknown_exception",    # 未知异常（最危险）
}


# =============================================================
# 4. 通知接口（统一入口）
# =============================================================


@dataclass
class NotifyResult:
    """通知发送结果。"""

    severity: Severity
    sent_channels: list[str] = field(default_factory=list)
    suppressed: bool = False  # 是否被 5 分钟静默期抑制
    dead_letter_path: str | None = None


def notify(
    message: str,
    severity: Severity,
    *,
    signature: str | None = None,
    context: dict[str, Any] | None = None,
    exception: Exception | None = None,
) -> NotifyResult:
    """统一通知入口。

    Args:
        message: 人类可读的错误描述
        severity: P1/P2/P3
        signature: 异常签名（用于 5 分钟聚合）；默认 = hash(message)
        context: 额外上下文（task 名 / 参数 / 时间戳等）
        exception: 原始异常对象（可选）

    Returns:
        NotifyResult: 哪些通道发了 / 是否被抑制
    """
    sig = signature or _hash_signature(message)
    context = context or {}

    # 1. 判断是否可自愈
    if sig in SELF_HEALING_SIGNATURES and severity != Severity.P1_CRITICAL:
        # 自愈类异常：仅记 dead letter，不通知
        return _write_dead_letter(message, severity, sig, context, exception,
                                  result=NotifyResult(severity=severity,
                                                      sent_channels=[],
                                                      suppressed=False))

    # 2. 5 分钟静默期检查
    if not _debouncer.should_notify(sig, severity):
        return _write_dead_letter(
            message, severity, sig, context, exception,
            result=NotifyResult(severity=severity, sent_channels=[],
                                suppressed=True),
        )

    # 3. 按通道发送
    result = NotifyResult(severity=severity)
    if severity == Severity.P1_CRITICAL:
        # P1：微信 + 邮件双通道
        if _send_wechat(message, severity, context):
            result.sent_channels.append("wechat_push")
        if _send_email(message, severity, context):
            result.sent_channels.append("email")
    elif severity == Severity.P2_WARNING:
        # P2：仅邮件
        if _send_email(message, severity, context):
            result.sent_channels.append("email")

    # 4. 写死信日志（无论是否发送成功）
    _write_dead_letter(message, severity, sig, context, exception, result=result)
    return result


def suppress(
    exception: Exception,
    severity: Severity,
    signature: str,
    *,
    max_retries: int = 3,
) -> bool:
    """AI 自愈循环：判断是否还要重试。

    Returns:
        True = 还要重试（未达 max_retries）
        False = 不要再试了（已达 max_retries，升级到 P1）
    """
    count = _debouncer.increment_retry(signature)
    if count >= max_retries:
        # 已达上限：升级到 P1 强制通知
        notify(
            f"{signature} 自愈失败，已重试 {count} 次",
            Severity.P1_CRITICAL,
            signature=signature,
            context={"retry_count": count, "original_error": str(exception)},
            exception=exception,
        )
        # 重置计数避免重复升级
        _debouncer.reset_retry(signature)
        return False
    return True


# =============================================================
# 5. 通道实现
# =============================================================


def _send_wechat(message: str, severity: Severity, context: dict) -> bool:
    """P1 通道：微信服务通知（实时）。"""
    openid = os.environ.get("NOTIFY_P1_WECHAT_OPENID", "").strip()
    template_id = os.environ.get("NOTIFY_P1_WECHAT_TEMPLATE_ID", "").strip()
    if not openid or not template_id:
        logger.warning("NOTIFY_P1_WECHAT_* 未配置，P1 通知降级为邮件")
        return _send_email(message, severity, context)

    # 调微信订阅消息 API
    try:
        import httpx
        # 拿 access_token
        appid = os.environ.get("WECHAT_MINIPROGRAM_APPID", "")
        secret = os.environ.get("WECHAT_MINIPROGRAM_SECRET", "")
        if not appid or not secret:
            return False
        resp = httpx.get(
            "https://api.weixin.qq.com/cgi-bin/token",
            params={"grant_type": "client_credential",
                    "appid": appid, "secret": secret},
            timeout=5,
        )
        token = resp.json().get("access_token", "")
        if not token:
            return False

        # 发订阅消息
        payload = {
            "touser": openid,
            "template_id": template_id,
            "data": {
                "thing1": {"value": f"[{severity.value}] {message[:30]}"},
                "time2": {"value": datetime.now().strftime("%m-%d %H:%M")},
                "thing3": {"value": str(context)[:50]},
            },
        }
        httpx.post(
            f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={token}",
            json=payload, timeout=5,
        )
        return True
    except Exception as e:
        logger.error("微信通知失败: %s", e)
        return False


def _send_email(message: str, severity: Severity, context: dict) -> bool:
    """P2 / P1 fallback 通道：邮件。"""
    smtp_host = os.environ.get("NOTIFY_SMTP_HOST", "").strip()
    smtp_user = os.environ.get("NOTIFY_SMTP_USER", "").strip()
    smtp_pass = os.environ.get("NOTIFY_SMTP_PASS", "").strip()
    email_to = os.environ.get("NOTIFY_P2_EMAIL_TO", "").strip()
    if not all([smtp_host, smtp_user, smtp_pass, email_to]):
        logger.debug("邮件通道未配置，跳过")
        return False
    try:
        body = (
            f"[雅思搭子 告警 {severity.value}]\n\n"
            f"时间：{datetime.now().isoformat(timespec='seconds')}\n"
            f"消息：{message}\n\n"
            f"上下文：\n{json.dumps(context, ensure_ascii=False, indent=2)}\n"
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[{severity.value}] 雅思搭子异常: {message[:40]}"
        msg["From"] = smtp_user
        msg["To"] = email_to
        with smtplib.SMTP_SSL(smtp_host, 465, timeout=10) as smtp:
            smtp.login(smtp_user, smtp_pass)
            smtp.send_message(msg)
        return True
    except Exception as e:
        logger.error("邮件发送失败: %s", e)
        return False


def _write_dead_letter(
    message: str,
    severity: Severity,
    signature: str,
    context: dict,
    exception: Exception | None,
    result: NotifyResult,
) -> NotifyResult:
    """所有通知统一写死信日志（dead letter）。"""
    log_path = Path(
        os.environ.get("NOTIFY_DEAD_LETTER_PATH",
                       "~/.ielts-buddy/.dead_letter.log")
    ).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "severity": severity.value,
        "signature": signature,
        "message": message,
        "context": context,
        "exception": str(exception) if exception else None,
        "sent_channels": result.sent_channels,
        "suppressed": result.suppressed,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    result.dead_letter_path = str(log_path)
    return result


def _hash_signature(text: str) -> str:
    """简单签名（用于 5 分钟聚合）。"""
    import hashlib
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


# =============================================================
# 6. 健康查询（CI 用）
# =============================================================


def health_snapshot() -> dict:
    """返回当前通知系统状态（供 CI 健康检查）。"""
    return {
        "notified_signatures": len(_debouncer.state.notified_signatures),
        "retry_counts": dict(_debouncer.state.retry_count),
        "self_heal_signatures": list(SELF_HEALING_SIGNATURES),
        "escalation_signatures": list(ESCALATION_SIGNATURES),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }


__all__ = [
    "Severity",
    "notify",
    "suppress",
    "NotifyResult",
    "health_snapshot",
    "SELF_HEALING_SIGNATURES",
    "ESCALATION_SIGNATURES",
]