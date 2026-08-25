#!/usr/bin/env python3
"""
06_pack_submission.py — 大赛提报材料打包（W8 收尾用）

6 项提报材料：
1. 参赛者身份证件（每人 1 张图片）
2. 小程序名称
3. AppID
4. 小程序二维码
5. 小程序说明文档 PDF
6. 参赛授权书 PDF

输出：
- docs/miniprogram/W8/submission/
  ├── 01_id_card_<姓名>.jpg
  ├── 04_qrcode.png
  ├── 05_description.pdf
  ├── 06_authorization_<姓名>.pdf
  ├── README.txt（提报清单）
  └── submission_package.zip（最终打包）

前置：
- 提前准备好：身份证扫描件、二维码图片（已在 _assets/）、说明文档 PDF
- 签字授权书（脚本只生成模板，签字由你补）

用法：
    python3 scripts/auto/06_pack_submission.py --members "张三,李四"
    python3 scripts/auto/06_pack_submission.py --members "张三" --description docs/miniprogram/W8/description.pdf
"""
import argparse
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUT_DIR = PROJECT_ROOT / "docs" / "miniprogram" / "W8" / "submission"
TEMPLATE_DIR = PROJECT_ROOT / "docs" / "miniprogram" / "W8" / "templates"


def check_materials(members: list[str], description_pdf: Path | None) -> dict:
    """检查所有必需材料是否就位。返回就位状态。"""
    status = {}

    # 1. 身份证扫描件：每个成员 1 张
    for m in members:
        for ext in ("jpg", "jpeg", "png", "pdf"):
            candidate = OUT_DIR / f"01_id_card_{m}.{ext}"
            if candidate.exists():
                status[f"id_card_{m}"] = candidate
                break
        else:
            status[f"id_card_{m}"] = None  # 缺失

    # 2. 小程序名称：从配置读取
    status["name"] = "英语干中学"  # 2026-08-24 定名

    # 3. AppID：从配置读取
    status["appid"] = "wx286309bc641b1d79"

    # 4. 二维码
    qrcode = PROJECT_ROOT / "docs" / "miniprogram" / "_assets" / "qrcode.png"
    status["qrcode"] = qrcode if qrcode.exists() else None

    # 5. 说明文档 PDF
    desc_default = OUT_DIR / "05_description.pdf"
    status["description"] = description_pdf or (desc_default if desc_default.exists() else None)

    # 6. 授权书
    for m in members:
        candidate = OUT_DIR / f"06_authorization_{m}.pdf"
        status[f"authorization_{m}"] = candidate if candidate.exists() else None

    return status


def render_readme(status: dict, members: list[str]) -> str:
    """生成提报清单 README。"""
    md = [
        "# 英语干中学 · 2026 微信小程序开发大赛 提报材料包\n",
        f"> 打包时间：{datetime.now().isoformat(timespec='seconds')}\n",
        f"> 大赛：2026 微信小程序开发大赛",
        f"> 提报截止：2026-10-17\n",
        "## 6 项提报材料状态\n",
    ]
    items = [
        ("1. 参赛者身份证件", [status.get(f"id_card_{m}") for m in members]),
        ("2. 小程序名称", [status["name"]]),
        ("3. AppID", [status["appid"]]),
        ("4. 小程序二维码", [status["qrcode"]]),
        ("5. 小程序说明文档 PDF", [status["description"]]),
        ("6. 参赛授权书 PDF", [status.get(f"authorization_{m}") for m in members]),
    ]
    for label, files in items:
        if all(files):
            md.append(f"✅ **{label}**：{len(files)} 份就位")
        elif any(files):
            md.append(f"⚠️ **{label}**：{sum(1 for f in files if f)}/{len(files)} 就位")
        else:
            md.append(f"❌ **{label}**：缺失")

    md.append("\n## 缺失材料清单\n")
    missing = False
    for m in members:
        if not status.get(f"id_card_{m}"):
            md.append(f"- 缺失：01_id_card_{m}.jpg")
            missing = True
        if not status.get(f"authorization_{m}"):
            md.append(f"- 缺失：06_authorization_{m}.pdf（请下载模板签字）")
            missing = True
    if not missing:
        md.append("（无）")

    md.append("\n## 提交流程\n")
    md.append("1. 把所有缺失材料补齐到 `docs/miniprogram/W8/submission/`")
    md.append("2. 重新跑此脚本打包")
    md.append("3. 登录 2026 微信小程序开发大赛提报系统")
    md.append("4. 上传 submission_package.zip + 各材料单独上传")
    md.append(f"5. 截止时间：2026-10-17 23:59")
    return "\n".join(md)


def make_zip(out_dir: Path, zip_path: Path) -> None:
    """打包 submission 目录为 zip。"""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in out_dir.rglob("*"):
            if file.is_file() and file.name != zip_path.name:
                zf.write(file, file.relative_to(out_dir.parent))


def main():
    parser = argparse.ArgumentParser(description="2026 大赛提报材料打包")
    parser.add_argument("--members", required=True,
                        help="参赛成员姓名，逗号分隔，如 '张三,李四'")
    parser.add_argument("--description", help="说明文档 PDF 路径")
    args = parser.parse_args()

    members = [m.strip() for m in args.members.split(",") if m.strip()]
    print(f"📦 提报材料打包")
    print(f"   参赛成员：{members}")
    print(f"   输出目录：{OUT_DIR}")

    description = Path(args.description) if args.description else None
    status = check_materials(members, description)

    # 生成 README
    readme = render_readme(status, members)
    readme_file = OUT_DIR / "README.md"
    readme_file.parent.mkdir(parents=True, exist_ok=True)
    readme_file.write_text(readme, encoding="utf-8")
    print(f"   ✅ README.md 已生成")

    # 打包
    zip_path = OUT_DIR / "submission_package.zip"
    make_zip(OUT_DIR, zip_path)
    print(f"   ✅ ZIP 打包完成：{zip_path}")

    # 检查完整性
    has_missing = (
        not all(status.get(f"id_card_{m}") for m in members) or
        not all(status.get(f"authorization_{m}") for m in members) or
        not status["qrcode"] or
        not status["description"]
    )
    if has_missing:
        print()
        print("⚠️ 警告：有材料缺失，请补齐后重新打包")
    else:
        print()
        print("✅ 所有材料就位，可以直接提交！")


if __name__ == "__main__":
    main()