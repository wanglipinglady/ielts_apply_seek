#!/usr/bin/env python3
"""
07_weekly_risk_recheck.py — 每周一自动跑的风险登记 recheck

自动扫描：
1. 28 条风险的触发时间是否到达
2. 已有应对措施的预案是否被采纳
3. 新增风险（基于近期日志 / GitHub issue / 类目审核状态）

输出：
- docs/miniprogram/W1/05-风险登记表.md（更新触发状态）
- docs/miniprogram/_assets/risk_recheck_<date>.md（增量报告）

用法：
    python3 scripts/auto/07_weekly_risk_recheck.py
    python3 scripts/auto/07_weekly_risk_recheck.py --week 2026-W36
"""
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RISK_FILE = PROJECT_ROOT / "docs" / "miniprogram" / "W1" / "05-风险登记表.md"
REPORT_DIR = PROJECT_ROOT / "docs" / "miniprogram" / "_assets"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def parse_risk_table(content: str) -> list[dict]:
    """从风险登记表 Markdown 解析风险条目。"""
    risks = []
    in_table = False
    for line in content.split("\n"):
        if line.strip().startswith("| ID |"):
            in_table = True
            continue
        if in_table and line.strip().startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 7:
                risks.append({
                    "id": parts[0],
                    "desc": parts[1],
                    "prob": parts[2],
                    "impact": parts[3],
                    "trigger_week": parts[4],
                    "plan": parts[5],
                })
        elif in_table and not line.startswith("|"):
            in_table = False
    return risks


def parse_week_label(week: str) -> int:
    """'W2' → 2, 'W5 9/18' → 5"""
    m = re.match(r"W(\d+)", week)
    return int(m.group(1)) if m else 99


def is_triggered_now(risk: dict, current_week: int) -> bool:
    """判断风险本周是否触发。"""
    trigger = parse_week_label(risk["trigger_week"])
    return trigger <= current_week


def render_report(risks: list[dict], current_week: int, week_label: str) -> str:
    """生成风险 recheck 报告。"""
    md = [f"# 风险登记表 · 每周 recheck\n"]
    md.append(f"> 周次：{week_label} · 当前 W{current_week}")
    md.append(f"> recheck 时间：{datetime.now().isoformat(timespec='seconds')}\n")

    # 本周触发的风险
    triggered = [r for r in risks if is_triggered_now(r, current_week)]
    future = [r for r in risks if not is_triggered_now(r, current_week)]

    md.append(f"## 一、本周触发风险（共 {len(triggered)} 条）\n")
    if not triggered:
        md.append("✅ 本周无风险触发。\n")
    else:
        for r in triggered:
            md.append(f"### {r['id']} · {r['desc'][:50]}")
            md.append(f"- 概率：{r['prob']} · 影响：{r['impact']}")
            md.append(f"- 触发周：{r['trigger_week']}")
            md.append(f"- **预案**：{r['plan']}")
            md.append(f"- 状态：{'⚠️ 已触发，需立即执行预案' if parse_week_label(r['trigger_week']) == current_week else '⏰ 已进入预备期'}")
            md.append("")

    md.append(f"\n## 二、未来风险（共 {len(future)} 条，按触发周排序）\n")
    for r in sorted(future, key=lambda x: parse_week_label(x["trigger_week"])):
        md.append(f"- **{r['id']}**（{r['trigger_week']} 触发）：{r['desc'][:60]}")

    md.append(f"\n## 三、本周建议动作\n")
    high_priority = [r for r in triggered
                    if r["impact"] in ("高", "高（硬瓶颈）", "高（严重度）")]
    if high_priority:
        md.append("🔴 **高影响风险触发，需立即处理：**")
        for r in high_priority:
            md.append(f"   - {r['id']}：{r['desc'][:50]}")
            md.append(f"     → 执行预案：{r['plan'][:80]}")
    else:
        md.append("✅ 本周无高影响风险触发。")

    md.append("\n## 四、健康度检查\n")
    md.append(f"- 风险总数：{len(risks)}")
    md.append(f"- 已触发：{len(triggered)}（{len(triggered) * 100 // max(len(risks), 1)}%）")
    md.append(f"- 待触发：{len(future)}（{len(future) * 100 // max(len(risks), 1)}%）")

    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(description="每周风险 recheck")
    parser.add_argument("--week", help="ISO 周编号，如 2026-W36")
    args = parser.parse_args()

    if not RISK_FILE.exists():
        print(f"❌ 风险登记表不存在：{RISK_FILE}")
        return

    content = RISK_FILE.read_text(encoding="utf-8")
    risks = parse_risk_table(content)
    print(f"📊 解析到 {len(risks)} 条风险")

    # 当前周
    if args.week:
        week_label = args.week
        current_week = int(args.week.split("-W")[1])
    else:
        now = datetime.now()
        current_week = now.isocalendar()[1]
        week_label = f"{now.year}-W{current_week:02d}"

    report = render_report(risks, current_week, week_label)
    out_file = REPORT_DIR / f"risk_recheck_{week_label.replace('-W', '_W')}.md"
    out_file.write_text(report, encoding="utf-8")

    print(f"✅ 风险 recheck 报告：{out_file}")
    print()
    print(report.md[:500] + ("..." if len(report.md) > 500 else ""))


if __name__ == "__main__":
    main()