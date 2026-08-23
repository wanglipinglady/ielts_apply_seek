"""验证 lifespan 启动期种子钩子(v3.7 P2 Sprint 3 新增)。

覆盖:
1. 启动期调用 seed_initial_questions 后,题库被填充
2. LISTENING_AUTO_SEED=False 时不启动种子线程
3. 启动期 purge_expired_audio 不阻塞(空题库也不抛)
4. 已种子后再启动 → 跳过(幂等)
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


WEB_DIR = Path(__file__).resolve().parents[2] / "src" / "ielts_buddy" / "web"


@pytest.fixture
def fresh_db(tmp_path) -> Iterator[str]:
    """给每个测试一个全新 SQLite 文件 + 清空环境变量污染。"""
    db_path = str(tmp_path / "web.db")
    os.environ["IELTS_BUDDY_ENV"] = "dev"
    os.environ["IELTS_BUDDY_JWT_SECRET"] = "test-secret-" + "x" * 32
    os.environ["IELTS_BUDDY_WEB_DB_MODE"] = "sqlite"
    os.environ["IELTS_BUDDY_WEB_SQLITE_PATH"] = db_path
    # 关闭自动种子,由测试自己控制
    os.environ["IELTS_BUDDY_LISTENING_AUTO_SEED"] = "0"
    yield db_path


def _reload_web_config() -> None:
    import importlib
    from ielts_buddy.web import config as web_config
    importlib.reload(web_config)


class TestStartupSeed:
    def test_startup_seeds_when_db_empty(
        self, fresh_db: str, monkeypatch
    ) -> None:
        """空题库 + AUTO_SEED=1 → lifespan 启动后会有题(背景线程需要时间)。"""
        # 强制 AUTO_SEED=1
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_AUTO_SEED", "1")
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_SEED_S1", "1")
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_SEED_S2", "0")
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_SEED_S3", "0")
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_SEED_S4", "0")
        _reload_web_config()

        from ielts_buddy.web.main import create_app

        app = create_app()
        with TestClient(app):
            # 触发 lifespan startup(seed 在后台线程跑)
            # 等种子线程跑完: S1=1 套 × 5 题
            for _ in range(50):  # 最多等 ~5s
                count = app.state.container.listening_practice.count_questions()
                if count >= 5:
                    break
                time.sleep(0.1)
            assert count >= 5, f"expected ≥5 questions, got {count}"

    def test_startup_skips_when_questions_exist(
        self, fresh_db: str, monkeypatch
    ) -> None:
        """题库已有题 → 启动期种子跳过(不会再次生成)。"""
        from ielts_buddy.repositories.fallback_repo import create_fallback_container
        # 先预种子
        container = create_fallback_container(
            sqlite_db_path=Path(fresh_db),
            mysql_url="",
            prefer_mode="sqlite",
        )
        repo = container.listening_practice
        repo.seed_question(
            section=1, set_id=1, qid=1,
            scenario="Pre-existing",
            question_type="multiple_choice",
            stem="Existing Q?",
            options=["A", "B", "C", "D"],
            answer="A",
            explanation="Pre-seeded.",
            transcript="Pre-existing transcript.",
        )
        container.close()

        monkeypatch.setenv("IELTS_BUDDY_LISTENING_AUTO_SEED", "1")
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_SEED_S1", "5")
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_SEED_S2", "0")
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_SEED_S3", "0")
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_SEED_S4", "0")
        _reload_web_config()

        from ielts_buddy.web.main import create_app

        app = create_app()
        with TestClient(app):
            time.sleep(0.5)  # 给后台线程跑跑
            # 总题数仍为 1(预种子那条)
            count = app.state.container.listening_practice.count_questions()
            assert count == 1, f"expected 1 question, got {count}"

    def test_startup_disabled_does_not_seed(
        self, fresh_db: str, monkeypatch
    ) -> None:
        """AUTO_SEED=0 → 启动期不种子。"""
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_AUTO_SEED", "0")
        _reload_web_config()

        from ielts_buddy.web.main import create_app

        app = create_app()
        with TestClient(app):
            time.sleep(0.5)
            count = app.state.container.listening_practice.count_questions()
            assert count == 0

    def test_startup_purge_does_not_throw_on_empty_db(
        self, fresh_db: str, monkeypatch
    ) -> None:
        """空题库的 purge 调用不应抛异常。"""
        monkeypatch.setenv("IELTS_BUDDY_LISTENING_AUTO_SEED", "0")
        _reload_web_config()

        from ielts_buddy.web.main import create_app

        app = create_app()
        # lifespan startup 自动调过 purge,不抛 → 测试通过
        with TestClient(app):
            assert app.state.container is not None