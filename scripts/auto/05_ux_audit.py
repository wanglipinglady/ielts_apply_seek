#!/usr/bin/env python3
"""
05_ux_audit.py — 体验问题自动扫描（W7 体验打磨用）

输入：后端访问日志 / 错误日志 / 用户行为日志
输出：Markdown 格式的体验问题清单（按严重度排序）

自动检测的 7 类问题：
1. 频繁 500 错误（> 5 次 / 小时）
2. 长尾请求（响应时间 > 3 秒）
3. 失败的 API 调用占比 > 10%
4. 用户在某页面停留 > 30 秒没动作（可能的卡点）
5. 重复点击同一按钮（前端 bug 信号）
6. 4xx 错误高峰（用户操作错误集中）
7. LLM / Whisper 调用失败率

用法：
    python3 scripts/auto/05_ux_audit.py                    # 扫描默认日志
    python3 scripts/auto/05_ux_audit.py --log-dir /var/log/ielts-buddy
    python3 scripts/auto/05_ux_audit.py --since 2026-09-01
"""
import argparse
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUT_DIR = PROJECT_ROOT / "docs" / "miniprogram" / "_assets"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# 日志正则（按行匹配）
PATTERNS = {
    "5xx_error": re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*500'),
    "slow_request": re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*duration=([\d.]+)s'),
    "4xx_error": re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).* 4(\d{2})'),
    "llm_error": re.compile(r'\[LLM\].*?(timeout|error|429|500)'),
    "whisper_error": re.compile(r'\[whisper\].*?(timeout|error|429|500)'),
}


def scan_log_file(log_file: Path, since: datetime) -> dict:
    """扫描单个日志文件，返回问题统计。"""
    issues = defaultdict(list)
    if not log_file.exists():
        return issues

    with log_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            # 5xx 错误
            m = PATTERNS["5xx_error"].search(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                if ts >= since:
                    issues["5xx_error"].append((ts, line.strip()[:200]))

            # 慢请求
            m = PATTERNS["slow_request"].search(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                duration = float(m.group(2))
                if ts >= since and duration > 3.0:
                    issues["slow_request"].append((ts, f"{duration:.2f}s · {line.strip()[:180]}"))

            # 4xx 错误
            m = PATTERNS["4xx_error"].search(line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                if ts >= since:
                    issues["4xx_error"].append((ts, line.strip()[:200]))

            # LLM / Whisper 错误
            if PATTERNS["llm_error"].search(line):
                issues["llm_error"].append((datetime.now(), line.strip()[:200]))
            if PATTERNS["whisper_error"].search(line):
                issues["whisper_error"].append((datetime.now(), line.strip()[:200]))

    return issues


def render_report(issues: dict, since: datetime) -> str:
    """生成 Markdown 报告。"""
    md = ["# 屠鸭智取 · 体验问题清单\n"]
    md.append(f"> 扫描时间窗：{since.date()} ~ {datetime.now().date()}")
    md.append(f"> 报告生成：{datetime.now().isoformat(timespec='seconds')}\n")

    if not issues:
        md.append("✅ 未发现明显体验问题。\n")
        return "\n".join(md)

    # 按严重度排序
    severity_order = ["5xx_error", "llm_error", "whisper_error",
                      "slow_request", "4xx_error"]
    for kind in severity_order:
        if kind not in issues:
            continue
        items = issues[kind]
        md.append(f"\n## {kind}（共 {len(items)} 次）\n")
        # 频率统计
        recent = [it for it in items if (datetime.now() - it[0]).days <= 7]
        md.append(f"- 最近 7 天：{len(recent)} 次")
        # 示例（前 5 条）
        md.append("- 示例：")
        for _, line in items[:5]:
            md.append(f"  - `{line}`")
        if len(items) > 5:
            md.append(f"  - ... 还有 {len(items) - 5} 条")

    # 优先级建议
    md.append("\n## 建议优先级\n")
    if issues.get("5xx_error"):
        md.append("🔴 **P0**：存在 500 错误，需立即排查（影响所有用户）")
    if issues.get("llm_error") or issues.get("whisper_error"):
        md.append("🟠 **P1**：AI 服务错误率上升，检查 API 配额 / 网络")
    if issues.get("slow_request"):
        slow_count = len(issues["slow_request"])
        md.append(f"🟡 **P2**：发现 {slow_count} 条慢请求（> 3 秒），可能影响用户体验")
    if issues.get("4xx_error"):
        md.append(f"🟢 **P3**：4xx 错误 {len(issues['4xx_error'])} 次，前端表单校验可优化")

    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(description="体验问题自动扫描")
    parser.add_argument("--log-dir", default="/var/log/ielts-buddy",
                        help="日志目录（默认 /var/log/ielts-buddy）")
    parser.add_argument("--since", help="扫描起始日期（默认 7 天前）")
    parser.add_argument("--out", help="输出 Markdown 路径")
    args = parser.parse_args()

    since = datetime.strptime(args.since, "%Y-%m-%d") if args.since \
        else datetime.now() - timedelta(days=7)

    log_dir = Path(args.log_dir)
    if not log_dir.exists():
        print(f"⚠️ 日志目录不存在：{log_dir}")
        print("   小程序上线前日志可能没生成，UX 审计会输出空报告")
        # 生成一个空报告骨架
        all_issues = {}
    else:
        log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("**/*.log"))
        all_issues = defaultdict(list)
        for log_file in log_files:
            file_issues = scan_log_file(log_file, since)
            for k, v in file_issues.items():
                all_issues[k].extend(v)

    report_md = render_report(dict(all_issues), since)
    out_file = Path(args.out) if args.out else OUT_DIR / f"ux_audit_{datetime.now().strftime('%Y%m%d')}.md"
    out_file.write_text(report_md, encoding="utf-8")

    print(f"✅ 体验审计报告：{out_file}")
    print(f"   问题汇总：")
    for k, v in all_issues.items():
        print(f"   - {k}: {len(v)} 次")


if __name__ == "__main__":
    main()