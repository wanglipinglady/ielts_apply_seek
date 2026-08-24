#!/usr/bin/env python3
"""
04_weekly_report.py — 学习数据周报生成（W7 收尾用，可每周跑）

输入：MySQL / SQLite 数据库
输出：PDF（学习数据可视化 + 文字复盘）

前置：
    pip install --break-system-packages reportlab matplotlib pymysql

用法：
    python3 scripts/auto/04_weekly_report.py            # 默认当前周
    python3 scripts/auto/04_weekly_report.py --week 2026-W35
    python3 scripts/auto/04_weekly_report.py --db-url 'mysql+pymysql://...'
    python3 scripts/auto/04_weekly_report.py --out docs/miniprogram/_assets/weekly_report.pdf
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUT_DIR = PROJECT_ROOT / "docs" / "miniprogram" / "_assets"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_stats(db_url: str, start: datetime, end: datetime) -> dict:
    """从 DB 拉本周学习数据。

    优雅降级：DB 不可达时返回空 dict，脚本不崩。
    """
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url)
        with engine.connect() as conn:
            # 累计学习词数
            total_words = conn.execute(text(
                "SELECT COUNT(*) FROM learning_records WHERE user_id > 0"
            )).scalar() or 0

            # 本周新学词数
            new_words = conn.execute(text("""
                SELECT COUNT(DISTINCT word) FROM learning_records
                WHERE created_at >= :start AND created_at < :end
            """), {"start": start, "end": end}).scalar() or 0

            # 本周复习次数
            reviews = conn.execute(text("""
                SELECT COUNT(*) FROM learning_records
                WHERE updated_at >= :start AND updated_at < :end
                  AND learn_count > 0
            """), {"start": start, "end": end}).scalar() or 0

            # 本周正确率（如果有 wrong_count 字段）
            try:
                accuracy = conn.execute(text("""
                    SELECT
                        CAST(SUM(correct_count) AS REAL) / NULLIF(SUM(learn_count), 0)
                    FROM learning_records
                    WHERE updated_at >= :start AND updated_at < :end
                """), {"start": start, "end": end}).scalar()
                accuracy = f"{accuracy * 100:.1f}%" if accuracy else "N/A"
            except Exception:
                accuracy = "N/A"

            # 错词总数
            mistakes = conn.execute(text("""
                SELECT COUNT(*) FROM personal_vocab
                WHERE category = 'mistakes'
            """)).scalar() or 0

            # 注册用户数（最近 7 天）
            new_users = conn.execute(text("""
                SELECT COUNT(*) FROM users
                WHERE created_at >= :start
            """), {"start": start}).scalar() or 0

            engine.dispose()
            return {
                "total_words": total_words,
                "new_words": new_words,
                "reviews": reviews,
                "accuracy": accuracy,
                "mistakes": mistakes,
                "new_users": new_users,
            }
    except Exception as e:
        print(f"⚠️ 数据库查询失败（继续生成报告骨架）: {e}")
        return {}


def generate_chart(stats: dict, out_png: Path) -> bool:
    """生成数据可视化图（matplotlib）。失败不阻断报告生成。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4))
        labels = ["累计学习词数", "本周新学词数", "本周复习次数", "错词数", "新增用户"]
        values = [
            stats.get("total_words", 0),
            stats.get("new_words", 0),
            stats.get("reviews", 0),
            stats.get("mistakes", 0),
            stats.get("new_users", 0),
        ]
        colors = ["#07C160", "#10AE55", "#06A050", "#F56565", "#5B6CFF"]
        bars = ax.bar(labels, values, color=colors)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    str(val), ha="center", fontsize=11)
        ax.set_title("雅思搭子 · 周数据复盘", fontsize=14, fontweight="bold")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        plt.tight_layout()
        plt.savefig(out_png, dpi=150, bbox_inches="tight")
        plt.close()
        return True
    except ImportError:
        print("⚠️ matplotlib 未安装，跳过图表")
        return False


def generate_pdf(stats: dict, chart_png: Path | None, out_pdf: Path,
                 week_label: str) -> None:
    """生成 PDF 报告。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    )

    # 注册中文字体
    try:
        pdfmetrics.registerFont(TTFont("PingFang", "/System/Library/Fonts/PingFang.ttc"))
        FONT = "PingFang"
    except Exception:
        FONT = "Helvetica"

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"],
                                  fontName=FONT, fontSize=20, leading=24,
                                  textColor=HexColor("#07C160"), alignment=1,
                                  spaceAfter=14)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"],
                               fontName=FONT, fontSize=13, leading=18,
                               textColor=HexColor("#06A050"), spaceBefore=10,
                               spaceAfter=6)
    body_style = ParagraphStyle("Body", parent=styles["Normal"],
                                fontName=FONT, fontSize=10.5, leading=15,
                                spaceAfter=5, textColor=HexColor("#333333"))

    doc = SimpleDocTemplate(str(out_pdf), pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    story = []
    story.append(Paragraph(f"雅思搭子 · 周数据复盘报告", title_style))
    story.append(Paragraph(f"周次：{week_label} · 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
                           body_style))
    story.append(Spacer(1, 0.4*cm))

    # 数据卡
    story.append(Paragraph("一、核心数据", h2_style))
    data_rows = [
        ["指标", "数值"],
        ["累计学习词数", str(stats.get("total_words", "N/A"))],
        ["本周新学词数", str(stats.get("new_words", "N/A"))],
        ["本周复习次数", str(stats.get("reviews", "N/A"))],
        ["本周正确率", stats.get("accuracy", "N/A")],
        ["错词本总数", str(stats.get("mistakes", "N/A"))],
        ["本周新增用户", str(stats.get("new_users", "N/A"))],
    ]
    tbl = Table(data_rows, colWidths=[6*cm, 8*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#E8F7EE")),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.5*cm))

    # 图表
    if chart_png and chart_png.exists():
        story.append(Paragraph("二、数据可视化", h2_style))
        story.append(Image(str(chart_png), width=15*cm, height=8*cm))
        story.append(Spacer(1, 0.5*cm))

    # 文字复盘（AI 后补）
    story.append(Paragraph("三、本周亮点", h2_style))
    story.append(Paragraph("[待 AI review 后补充：本周产品迭代 / 用户反馈 / 数据亮点]",
                           body_style))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("四、问题与改进", h2_style))
    story.append(Paragraph("[待 AI review 后补充：本周遇到的问题 + 解决思路]",
                           body_style))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("五、下周计划", h2_style))
    story.append(Paragraph("[待 AI review 后补充：下周 3 个核心目标 + 验收标准]",
                           body_style))

    doc.build(story)
    print(f"✅ PDF 生成完成：{out_pdf}")


def main():
    parser = argparse.ArgumentParser(description="雅思搭子周数据报告生成")
    parser.add_argument("--week", help="ISO 周编号，如 2026-W35（默认上周）")
    parser.add_argument("--db-url", help="SQLAlchemy URL（默认走项目 .env）")
    parser.add_argument("--out", help="输出 PDF 路径")
    args = parser.parse_args()

    # 默认输出路径
    if args.out:
        out_pdf = Path(args.out)
    else:
        week = args.week or datetime.now().strftime("%Y-W%V")
        out_pdf = OUT_DIR / f"weekly_report_{week}.pdf"

    # 时间窗
    now = datetime.now()
    if args.week:
        # ISO 周解析
        year, w = args.week.split("-W")
        monday = datetime.strptime(f"{year}-W{int(w)}-1", "%Y-W%W-%w")
    else:
        monday = now - timedelta(days=now.weekday() + 7)  # 上周一
    sunday = monday + timedelta(days=7)

    week_label = monday.strftime("%Y-W%V") + f" ({monday.strftime('%m/%d')} - {sunday.strftime('%m/%d')})"
    print(f"📊 生成周报：{week_label}")
    print(f"   时间窗：{monday.date()} ~ {sunday.date()}")

    # 数据库 URL
    db_url = args.db_url or os.environ.get("IELTS_BUDDY_WEB_DB_URL", "")
    if not db_url:
        # 退到本地 SQLite
        db_url = "sqlite:///" + str(Path.home() / ".ielts-buddy" / "web_data.db")

    # 拉数据
    stats = fetch_stats(db_url, monday, sunday)
    print(f"   数据：{stats}")

    # 生成图表
    chart_png = OUT_DIR / f"weekly_chart_{week_label.split()[0]}.png"
    if not generate_chart(stats, chart_png):
        chart_png = None

    # 生成 PDF
    generate_pdf(stats, chart_png, out_pdf, week_label.split()[0])

    # 清理临时图
    if chart_png and chart_png.exists():
        print(f"   临时图表：{chart_png}")


if __name__ == "__main__":
    main()