"""Reading 启动期种子 + PrepResource 启动期种子 lifespan 钩子测试（v3.8 P3 新增）。

覆盖:
1. 启动期 reading 题库为空 → 后台种子后有题
2. 启动期 reading 题库已有 → 跳过(幂等)
3. 启动期 prep_resources 题库为空 → 同步种子 32 条
4. 启动期 prep_resources 已有 → 跳过
5. 启动期 prep_resources seed JSON path 修复后能正常加载
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


WEB_DIR = Path(__file__).resolve().parents[2] / "src" / "ielts_buddy" / "web"


@pytest.fixture
def fresh_db(tmp_path):
    """给每个测试一个全新 SQLite 文件 + 清空环境变量污染。"""
    db_path = str(tmp_path / "web.db")
    os.environ["IELTS_BUDDY_ENV"] = "dev"
    os.environ["IELTS_BUDDY_JWT_SECRET"] = "test-secret-" + "x" * 32
    os.environ["IELTS_BUDDY_WEB_DB_MODE"] = "sqlite"
    os.environ["IELTS_BUDDY_WEB_SQLITE_PATH"] = db_path
    # 关闭 listening 启动期(避免 SQLite 抢锁)
    os.environ["IELTS_BUDDY_LISTENING_AUTO_SEED"] = "0"
    # 注意:reading 启动期保持开启,这是这个测试要验证的
    os.environ.pop("IELTS_BUDDY_READING_AUTO_SEED", None)
    yield db_path


def _reload_web_config():
    import importlib
    from ielts_buddy.web import config as web_config
    importlib.reload(web_config)


# =============================================================
# Reading 启动期种子
# =============================================================


class TestReadingStartupSeed:
    def test_startup_seeds_when_db_empty(
        self, fresh_db: str, monkeypatch
    ) -> None:
        """空题库 → lifespan 启动后 reading 题库被填充。"""
        # 关闭 prep_resources 自动种子,只测 reading
        monkeypatch.setenv("IELTS_BUDDY_PREP_AUTO_SEED", "0")
        _reload_web_config()

        from ielts_buddy.web.main import create_app

        app = create_app()
        with TestClient(app):
            # 等后台种子线程跑完
            for _ in range(100):  # 最多等 ~10s
                count = app.state.container.reading_practice.count_passages()
                if count > 0:
                    break
                time.sleep(0.1)
            # 至少种了 1 套(可能是 mock 题,数量 ≥ 5)
            assert count > 0, f"expected reading passages, got 0"

    def test_startup_skips_when_passages_exist(
        self, fresh_db: str, monkeypatch
    ) -> None:
        """题库已有题 → 启动期种子跳过。"""
        # 先预种 1 道题
        from ielts_buddy.repositories.fallback_repo import create_fallback_container
        container = create_fallback_container(
            sqlite_db_path=Path(fresh_db),
            mysql_url="",
            prefer_mode="sqlite",
        )
        container.reading_practice.seed_passage(
            section="easy", set_id=1, qid=1,
            passage_number=1,
            title="Pre-existing",
            topic="Pre-existing",
            question_type="multiple_choice",
            word_count=600,
            passage_text="Pre-existing passage text.",
            stem="Pre-existing Q?",
            options=["A", "B", "C", "D"],
            answer="A",
            explanation="Pre-seeded.",
            source_line=1,
        )
        container.close()

        monkeypatch.setenv("IELTS_BUDDY_PREP_AUTO_SEED", "0")
        _reload_web_config()

        from ielts_buddy.web.main import create_app

        app = create_app()
        with TestClient(app):
            time.sleep(0.5)
            # 总题数仍为 1
            count = app.state.container.reading_practice.count_passages()
            assert count == 1


# =============================================================
# Prep resources 启动期种子(同步)
# =============================================================


class TestPrepResourcesStartupSeed:
    def test_seed_initial_prep_resources_loads_json(
        self, tmp_path: Path
    ) -> None:
        """测试修复后的 path 能正常读取 JSON。"""
        from ielts_buddy.repositories.fallback_repo import create_fallback_container
        from ielts_buddy.services.prep_resource_service import (
            seed_initial_prep_resources,
        )

        container = create_fallback_container(
            sqlite_db_path=tmp_path / "web.db",
            mysql_url="",
            prefer_mode="sqlite",
        )
        # 不传 json_path → 走默认 path
        result = seed_initial_prep_resources(container)
        # 成功 seed(数量 ≥ 1)
        assert result["seeded"] >= 1
        assert result["skipped"] >= 0
        container.close()

    def test_startup_seeds_resources_synchronously(
        self, fresh_db: str, monkeypatch
    ) -> None:
        """lifespan 启动后 prep_resources 已经被种子(同步)。"""
        _reload_web_config()

        from ielts_buddy.web.main import create_app

        app = create_app()
        with TestClient(app):
            # 同步种子完成,直接查
            count = app.state.container.prep_resource.count_resources()
            assert count >= 1, (
                f"expected ≥1 prep resources after startup, got {count}"
            )

    def test_startup_skips_when_resources_exist(
        self, fresh_db: str, monkeypatch
    ) -> None:
        """题库已有资源 → 启动期种子跳过。"""
        from ielts_buddy.repositories.fallback_repo import create_fallback_container
        container = create_fallback_container(
            sqlite_db_path=Path(fresh_db),
            mysql_url="",
            prefer_mode="sqlite",
        )
        container.prep_resource.seed_resource(
            title="Pre-existing resource",
            bv_id="BV1pre01",
            url="https://www.bilibili.com/video/BV1pre01",
            author_name="Test UP",
            author_uid=99001,
            uploader_name="Test UP",
            uploader_uid=99001,
            skill="general",
            video_type="methodology",
            level="5-6",
            method_summary="Pre-seeded resource.",
            source_status="verified_repost",
            publish_date="2024-01-01",
            duration_sec=600,
            outdated_risk="low",
            format_compatible="computer",
            computer_delivery_only=True,
            is_featured=False,
            recommend_score=5.0,
            sort_order=100,
        )
        container.close()

        _reload_web_config()

        from ielts_buddy.web.main import create_app

        app = create_app()
        with TestClient(app):
            # 已有 1 条 → 启动期不会再 seed
            count = app.state.container.prep_resource.count_resources()
            assert count == 1
