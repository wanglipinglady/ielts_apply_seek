#!/usr/bin/env python3
"""
02_seed_user_posts.py — 种子用户发布脚本（W5-W6 拉新用）

平台覆盖：
- B站（专栏文章）—— 需要 cookie + CSRF token
- 知乎（文章 + 回答）—— 需要 cookie
- 豆瓣（小站 / 小组话题）—— 需要 cookie
- 朋友圈文案（纯文本，不在此生成）

自动模式：只生成文案 + 保存为 Markdown，留给你 review 后手动发
半自动模式：提供平台 API 接入示例（需你补 cookie）

用法：
    python3 scripts/auto/02_seed_user_posts.py            # 生成 5 篇文案
    python3 scripts/auto/02_seed_user_posts.py --platform zhihu --count 3
    python3 scripts/auto/02_seed_user_posts.py --review-only   # 只生成不发布
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

# 项目根
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUT_DIR = PROJECT_ROOT / "docs" / "miniprogram" / "_assets" / "seed_posts"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# 文案模板：每个平台独立的语气 + 长度 + 调用规范
# =============================================================================

TEMPLATES = {
    "zhihu": {
        "name": "知乎",
        "title_prefix": "雅思备考",
        "tone": "专业 / 干货 / 长文",
        "length": "1500-3000 字",
        "topics": [
            "雅思口语 Part 2 录音后怎么自我评分？AI 工具实测",
            "雅思写作 Task 2 七分瓶颈：AI 批改帮我识破的 5 个误区",
            "如何用艾宾浩斯曲线 8 周备考雅思词汇？小程序实测",
        ],
        "template": """# {title}

> 写在前面：本文基于本人备考雅思的真实经验，所有提到的工具「屠鸭智取」是本人参与开发的产品，
> 数据来自 30 天实测，结论仅供参考。

## 一、痛点

{problem}

## 二、为什么传统方案不行

{problem_analysis}

## 三、我的解决方案：AI 屠鸭智取

{solution}

## 四、实测数据

{data}

## 五、给读者的建议

{advice}

---

📱 想体验这个工具，可以微信搜索「屠鸭智取」小程序（个人开发，免费）。

⚠️ 提示：本文不含广告合作，工具为本人开源项目。""",
    },
    "bilibili": {
        "name": "B站",
        "title_prefix": "【工具实测】雅思",
        "tone": "年轻 / 简洁 / 视频/图文",
        "length": "300-800 字 + 配图",
        "topics": [
            "【工具实测】这个小程序让我的雅思口语从 5.5 涨到 6.5",
            "【AI 评测】雅思写作批改工具横评，谁最像雅思考官？",
        ],
        "template": """# {title}

## 起因
{problem}

## 实测
{solution}

## 数据
{data}

## 结论
{conclusion}

工具地址：微信小程序「屠鸭智取」""",
    },
    "douban": {
        "name": "豆瓣小组",
        "title_prefix": "[雅思备考]",
        "tone": "口语化 / 真实 / 接地气",
        "length": "300-800 字",
        "topics": [
            "[雅思备考] 推荐一个 AI 口语搭子小程序",
            "[雅思经验] 8 周雅思 6.5 → 7.0 的复习方法",
        ],
        "template": """{title}

{problem}

用了大概 {data}。

{solution}

{conclusion}

小程序搜「屠鸭智取」即可，免费。""",
    },
}


def render_post(platform: str, topic_idx: int = 0) -> dict:
    """生成一篇该平台的文案草稿。"""
    tmpl = TEMPLATES[platform]
    topic = tmpl["topics"][topic_idx % len(tmpl["topics"])]
    title = f"{tmpl['title_prefix']}{topic.split(tmpl['title_prefix'], 1)[-1].strip()}"

    # 占位符替换（实际内容由你 review 后填）
    content = tmpl["template"].format(
        title=title,
        problem="[待填写：你的真实痛点，200-300 字]",
        problem_analysis="[待填写：传统方案哪里不行，300-500 字]",
        solution="[待填写：工具如何解决，300-500 字]",
        data="[待填写：实测数据 / 截图 / 表格]",
        advice="[待填写：给读者的可操作建议]",
        conclusion="[待填写：结论 + 工具地址]",
    )

    return {
        "platform": platform,
        "platform_name": tmpl["name"],
        "title": title,
        "content": content,
        "length": tmpl["length"],
        "tone": tmpl["tone"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def main():
    parser = argparse.ArgumentParser(description="生成种子用户发布文案（W5-W6）")
    parser.add_argument("--platform", choices=list(TEMPLATES.keys()), help="指定平台（默认轮询）")
    parser.add_argument("--count", type=int, default=5, help="生成篇数（默认 5）")
    parser.add_argument("--review-only", action="store_true", help="只生成 Markdown，不尝试发布")
    args = parser.parse_args()

    print(f"📝 生成 {args.count} 篇种子用户文案...")
    print(f"   输出目录：{OUT_DIR}")
    print()

    for i in range(args.count):
        platform = args.platform or list(TEMPLATES.keys())[i % len(TEMPLATES)]
        post = render_post(platform, topic_idx=i)

        # 写 Markdown 文件
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = OUT_DIR / f"{ts}_{platform}_post_{i+1}.md"
        with out_file.open("w", encoding="utf-8") as f:
            f.write(f"# [{post['platform_name']}] {post['title']}\n\n")
            f.write(f"> 语气：{post['tone']} · 长度：{post['length']}\n")
            f.write(f"> 生成时间：{post['generated_at']}\n\n")
            f.write(post["content"])
            f.write("\n")

        print(f"   ✅ [{post['platform_name']}] {post['title'][:30]}... → {out_file.name}")

    print()
    print(f"📂 全部文案已保存到：{OUT_DIR}")
    print()
    print("📌 下一步：")
    print("   1. 用文本编辑器打开每个 .md 文件")
    print("   2. 替换 [待填写：...] 占位符为你的真实内容")
    print("   3. 手动登录对应平台发布（cookie / CSRF 不适合脚本自动化）")
    if args.review_only:
        print("   ✅ 已使用 --review-only 模式：不会尝试自动发布")


if __name__ == "__main__":
    main()