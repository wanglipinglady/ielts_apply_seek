"""IELTS Buddy CLI 入口点（自动加载 .env）"""

from dotenv import load_dotenv

load_dotenv()  # 自动查找并加载项目根目录的 .env 文件

from ielts_buddy.cli import cli

if __name__ == "__main__":
    cli()
