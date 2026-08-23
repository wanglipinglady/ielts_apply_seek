#!/usr/bin/env python3
"""手动种子真·听力题库（v3.7 P2 新增）。

PRD: docs/web-mvp/plans/phase-9-listening-practice.md §6.2 / §11

用法:
    # 增量种子(已有题则跳过)
    PYTHONPATH=src python scripts/seed_listening_questions.py

    # 强制重新种子(清空题库再生成;危险)
    PYTHONPATH=src python scripts/seed_listening_questions.py --force

    # 只种子 Section 1
    PYTHONPATH=src python scripts/seed_listening_questions.py --sections 1

    # 调每个 Section 套数
    PYTHONPATH=src python scripts/seed_listening_questions.py --s1 5 --s2 4 --s3 3 --s4 2

    # 不触发 TTS(只生成题目,不合成音频)
    PYTHONPATH=src python scripts/seed_listening_questions.py --no-tts

依赖:
    - IELTS_BUDDY_LLM_API_KEY 已配置(否则走 mock)
    - IELTS_BUDDY_WEB_DB_MODE=sqlite (本地) 或 =online (MySQL)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# 添加 src 到 PYTHONPATH(让 PYTHONPATH=src 可省略)
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="手动种子真·听力题库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="清空题库再生成(危险!会删除所有 listening_questions 行)",
    )
    parser.add_argument(
        "--sections",
        type=int,
        choices=[1, 2, 3, 4],
        nargs="+",
        help="仅种子指定 Section(如 --sections 1 2);默认全 4 个 Section",
    )
    parser.add_argument(
        "--s1", type=int, default=None, help="Section 1 套数(默认走 env 或 10)"
    )
    parser.add_argument(
        "--s2", type=int, default=None, help="Section 2 套数(默认走 env 或 8)"
    )
    parser.add_argument(
        "--s3", type=int, default=None, help="Section 3 套数(默认走 env 或 7)"
    )
    parser.add_argument(
        "--s4", type=int, default=None, help="Section 4 套数(默认走 env 或 5)"
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="只生成题目不合成音频(节省 LLM 配额,音频延后触发)",
    )
    parser.add_argument(
        "--db-mode",
        default=None,
        choices=["online", "sqlite"],
        help="数据库模式(默认走 env 或 online)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细日志",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger = logging.getLogger("seed_listening")

    # ---- 0. 加载 config + 容器 ----
    from ielts_buddy.repositories import create_repositories
    from ielts_buddy.services.listening_practice_service import (
        seed_initial_questions,
    )
    from ielts_buddy.web import config as web_config

    mode = args.db_mode or web_config.WEB_DB_MODE
    if mode == "online":
        try:
            container = create_repositories(mode="online")
        except Exception as exc:
            logger.warning(
                "[online] 创建容器失败,降级 sqlite: %s", exc
            )
            container = create_repositories(mode="local")
    else:
        container = create_repositories(mode="local")

    repo = container.listening_practice
    try:
        # ---- 1. --force:清空题库 ----
        if args.force:
            existing = repo.count_questions()
            logger.warning(
                "[force] 将清空 %d 道题 + 关联 listening_attempts",
                existing,
            )
            # SQLite 端直接执行 DELETE
            try:
                conn = repo._conn  # type: ignore[attr-defined]
                conn.execute("DELETE FROM listening_attempts")
                conn.execute("DELETE FROM listening_questions")
                conn.commit()
                logger.warning("[force] 已清空")
            except Exception as exc:
                logger.error("[force] 清空失败: %s", exc)
                return 1

        # ---- 2. 检查是否需要种子 ----
        if repo.count_questions() > 0 and not args.force:
            logger.info(
                "题库已有 %d 道题,跳过种子(用 --force 强制重新生成)",
                repo.count_questions(),
            )
            return 0

        # ---- 3. 决定每个 Section 套数 ----
        s1 = args.s1 if args.s1 is not None else web_config.LISTENING_SEED_S1
        s2 = args.s2 if args.s2 is not None else web_config.LISTENING_SEED_S2
        s3 = args.s3 if args.s3 is not None else web_config.LISTENING_SEED_S3
        s4 = args.s4 if args.s4 is not None else web_config.LISTENING_SEED_S4

        if args.sections:
            target_sections = set(args.sections)
            if 1 not in target_sections:
                s1 = 0
            if 2 not in target_sections:
                s2 = 0
            if 3 not in target_sections:
                s3 = 0
            if 4 not in target_sections:
                s4 = 0

        total_target = s1 + s2 + s3 + s4
        if total_target == 0:
            logger.warning("目标套数为 0,无需种子")
            return 0

        logger.info(
            "开始种子:S1=%d S2=%d S3=%d S4=%d (共 %d 套, TTS=%s)",
            s1, s2, s3, s4, total_target,
            "OFF" if args.no_tts else "ON",
        )

        # ---- 4. 执行种子 ----
        start = time.time()
        result = seed_initial_questions(
            container=container,
            s1=s1, s2=s2, s3=s3, s4=s4,
            auto_trigger_tts=not args.no_tts,
        )
        elapsed = time.time() - start

        logger.info(
            "种子完成: %s,耗时 %.1fs",
            result, elapsed,
        )
        return 0
    finally:
        try:
            container.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())