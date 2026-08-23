"""备考资源广场业务服务（v3.8 P3.1 新增）。

PRD: docs/web-mvp/plans/phase-10-reading-and-resources.md §5.5-5.7

负责:
- 启动期自动种子 B 站资源(从 prep_resources_seed.json)
- 列表查询(过滤/排序/分页)
- 单条详情 + 「今日推荐」(基于用户学习阶段)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ielts_buddy.core.repository import PrepResourceRepository

logger = logging.getLogger(__name__)


# 评分公式常量(PRD §5.7 §3)
METHODOLOGY_WEIGHT = 0.35
ACCOUNT_TRUST_WEIGHT = 0.25
RECENCY_WEIGHT = 0.20
TARGET_MATCH_WEIGHT = 0.15
ACTIONABILITY_WEIGHT = 0.05

SOURCE_STATUS_SCORE = {
    "official": 1.0,
    "institution": 0.8,
    "verified_repost": 0.6,
    "unverified_repost": 0.3,
}

OUTDATED_RISK_SCORE = {
    "low": 1.0,
    "medium": 0.6,
    "high": 0.2,
}


def compute_recommend_score(
    *,
    method_summary: str,
    source_status: str,
    publish_date: Optional[str],
    level: str,
    related_action_url: Optional[str],
) -> float:
    """计算推荐分(0-10)。手工种子数据已自带 recommend_score,
    此函数用于动态新增资源时的兜底评分。
    """
    meth = min(1.0, len(method_summary or "") / 50.0)  # ≥50 字给满分
    src = SOURCE_STATUS_SCORE.get(source_status, 0.5)
    risk = OUTDATED_RISK_SCORE.get("low", 0.5)
    if publish_date:
        try:
            y = int(publish_date.split("-")[0])
            now = datetime.now().year
            recency = max(0.0, 1.0 - (now - y) / 5.0)  # 5 年前=0
        except Exception:
            recency = 0.5
    else:
        recency = 0.5
    target = 0.8 if level else 0.5
    action = 1.0 if related_action_url else 0.6
    score = (
        METHODOLOGY_WEIGHT * meth
        + ACCOUNT_TRUST_WEIGHT * src
        + RECENCY_WEIGHT * recency * risk
        + TARGET_MATCH_WEIGHT * target
        + ACTIONABILITY_WEIGHT * action
    ) * 10
    return round(min(10.0, score), 1)


class PrepResourceService:
    """备考资源业务服务。

    Args:
        container: 业务容器(拿 .prep_resource)
    """

    def __init__(self, container: Any) -> None:
        self._container = container
        self._repo: PrepResourceRepository = container.prep_resource

    # =============================================================
    # 查询
    # =============================================================

    def list_resources(
        self,
        skill: Optional[str] = None,
        level: Optional[str] = None,
        source_status: Optional[str] = None,
        is_featured: Optional[bool] = None,
        sort_by: str = "recommend_score",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        return self._repo.list_resources(
            skill=skill, level=level, source_status=source_status,
            is_featured=is_featured, sort_by=sort_by,
            limit=limit, offset=offset,
        )

    def get_resource(self, resource_id: int) -> Optional[dict]:
        return self._repo.get_resource(int(resource_id))

    def list_featured(self, skill: Optional[str] = None, limit: int = 5) -> list[dict]:
        return self._repo.list_featured(skill=skill, limit=limit)

    def list_by_up(self, author_name: str, limit: int = 20) -> list[dict]:
        return self._repo.list_by_up(author_name=author_name, limit=limit)

    def list_distinct_ups(self) -> list[dict]:
        return self._repo.list_distinct_ups()

    def count_resources(
        self,
        skill: Optional[str] = None,
        level: Optional[str] = None,
        source_status: Optional[str] = None,
        is_featured: Optional[bool] = None,
    ) -> int:
        return self._repo.count_resources(
            skill=skill, level=level, source_status=source_status,
            is_featured=is_featured,
        )

    def get_today_recommendation(
        self, user_level: str = "5-6", skill: Optional[str] = None
    ) -> Optional[dict]:
        """返回今日推荐(Dashboard 「今日方法论」卡片用)。

        策略:从 featured 中取一条;若空,从 recommend_score top 5 中按 level 匹配一条。
        """
        candidates = self._repo.list_featured(skill=skill, limit=10)
        if candidates:
            return candidates[0]
        # fallback:高分池子
        pool = self._repo.list_resources(skill=skill, sort_by="recommend_score", limit=20)
        for r in pool:
            if r["level"] == user_level:
                return r
        if pool:
            return pool[0]
        return None

    # =============================================================
    # 种子(启动期 + 手动)
    # =============================================================

    def seed_from_json(self, json_path: Path) -> dict[str, int]:
        """从 prep_resources_seed.json 种子数据导入。

        Args:
            json_path: JSON 文件路径
        Returns:
            {"seeded": N, "skipped": M}
        """
        try:
            items = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("[prep] seed file read failed: %s", exc)
            return {"seeded": 0, "skipped": 0}
        seeded = 0
        skipped = 0
        for it in items:
            try:
                # 已有 → 跳过(只新增,UPDATE 通过手工)
                if self._repo.get_resource_by_bv(it["bv_id"]):
                    skipped += 1
                    continue
                self._repo.seed_resource(
                    title=it["title"],
                    bv_id=it["bv_id"],
                    url=it["url"],
                    author_name=it["author_name"],
                    author_uid=it.get("author_uid"),
                    uploader_name=it.get("uploader_name"),
                    uploader_uid=it.get("uploader_uid"),
                    skill=it["skill"],
                    video_type=it["video_type"],
                    level=it["level"],
                    method_summary=it["method_summary"],
                    source_status=it.get("source_status", "verified_repost"),
                    publish_date=it.get("publish_date"),
                    duration_sec=int(it.get("duration_sec", 0)),
                    outdated_risk=it.get("outdated_risk", "low"),
                    format_compatible=it.get("format_compatible", "computer"),
                    computer_delivery_only=bool(it.get("computer_delivery_only", True)),
                    is_featured=bool(it.get("is_featured", False)),
                    recommend_score=float(it.get("recommend_score", 0.0)),
                    sort_order=int(it.get("sort_order", 100)),
                    related_action_url=it.get("related_action_url"),
                    related_action_label=it.get("related_action_label"),
                )
                seeded += 1
            except Exception as exc:
                logger.warning("[prep] seed failed for %s: %s", it.get("bv_id"), exc)
        return {"seeded": seeded, "skipped": skipped}


def seed_initial_prep_resources(container: Any, json_path: Optional[Path] = None) -> dict[str, int]:
    """启动期种子资源。已有资源 → 跳过。

    Args:
        container: 业务容器
        json_path: JSON 文件路径;默认走 data/prep_resources_seed.json
    """
    if json_path is None:
        # 服务文件: src/ielts_buddy/services/prep_resource_service.py
        # parents[0] = services/, parents[1] = ielts_buddy/, parents[2] = src/, parents[3] = project root
        # JSON 数据位于 src/ielts_buddy/data/,因此走 parents[1] + "data"
        json_path = Path(__file__).resolve().parents[1] / "data" / "prep_resources_seed.json"
    repo = container.prep_resource
    if repo.count_resources() > 0:
        return {"seeded": 0, "skipped": repo.count_resources(), "skipped_all": True}
    svc = PrepResourceService(container)
    return svc.seed_from_json(json_path)


__all__ = [
    "PrepResourceService",
    "compute_recommend_score",
    "seed_initial_prep_resources",
]