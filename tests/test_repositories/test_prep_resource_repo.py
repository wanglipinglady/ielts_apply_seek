"""SQLitePrepResourceRepository 单元测试(v3.8 P3.1 新增)。

覆盖:
- seed_resource upsert(UNIQUE bv_id 兜底)
- get_resource / get_resource_by_bv
- list_resources 多条件过滤 + 3 种排序
- list_featured / list_by_up / list_distinct_ups
- count_resources
- update_resource / delete_resource
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ielts_buddy.repositories.fallback_repo import create_fallback_container


def _make_container(tmp_path: Path):
    sqlite_path = tmp_path / "web.db"
    return create_fallback_container(
        sqlite_db_path=sqlite_path,
        mysql_url="",
        prefer_mode="sqlite",
    )


def _sample_resource(
    title="Test Video",
    bv_id="BV1abc",
    url="https://www.bilibili.com/video/BV1abc/",
    author_name="TestUP",
    skill="listening",
    video_type="methodology",
    level="5-6",
    method_summary="测试方法论",
    source_status="verified_repost",
    **kwargs,
):
    base = dict(
        title=title, bv_id=bv_id, url=url,
        author_name=author_name, skill=skill,
        video_type=video_type, level=level,
        method_summary=method_summary,
        source_status=source_status,
    )
    base.update(kwargs)
    return base


class TestPrepResourceSeed:
    def test_seed_inserts_new_resource(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        rid = repo.seed_resource(**_sample_resource())
        assert rid > 0
        loaded = repo.get_resource(rid)
        assert loaded is not None
        assert loaded["title"] == "Test Video"
        assert loaded["bv_id"] == "BV1abc"
        assert loaded["skill"] == "listening"

    def test_seed_upserts_on_bv_id_conflict(self, tmp_path: Path) -> None:
        """相同 BV 号第二次 seed → UPDATE,id 不变。"""
        container = _make_container(tmp_path)
        repo = container.prep_resource
        rid1 = repo.seed_resource(**_sample_resource(title="A", bv_id="BVdup"))
        rid2 = repo.seed_resource(**_sample_resource(title="B updated", bv_id="BVdup"))
        assert rid1 == rid2
        loaded = repo.get_resource(rid1)
        assert loaded["title"] == "B updated"

    def test_seed_persists_all_optional_fields(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        rid = repo.seed_resource(
            **_sample_resource(
                bv_id="BVfull",
                author_uid=12345,
                uploader_name="UploaderX",
                uploader_uid=99999,
                publish_date="2024-05-01",
                duration_sec=600,
                outdated_risk="medium",
                is_featured=True,
                recommend_score=9.5,
                sort_order=50,
                related_action_url="/listen/practice",
                related_action_label="🎧 立即做听力",
            ),
        )
        loaded = repo.get_resource(rid)
        assert loaded["author_uid"] == 12345
        assert loaded["uploader_name"] == "UploaderX"
        assert loaded["publish_date"] == "2024-05-01"
        assert loaded["duration_sec"] == 600
        assert loaded["outdated_risk"] == "medium"
        assert loaded["is_featured"] == 1
        assert loaded["recommend_score"] == 9.5
        assert loaded["sort_order"] == 50
        assert loaded["related_action_url"] == "/listen/practice"


class TestPrepResourceRead:
    def test_get_resource_by_bv(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        repo.seed_resource(**_sample_resource(bv_id="BVlookup"))
        loaded = repo.get_resource_by_bv("BVlookup")
        assert loaded is not None
        assert loaded["bv_id"] == "BVlookup"

    def test_get_resource_returns_none_for_missing(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        assert repo.get_resource(99999) is None
        assert repo.get_resource_by_bv("BVnone") is None


class TestPrepResourceList:
    def _seed_mixed(self, repo):
        repo.seed_resource(**_sample_resource(bv_id="BV1", skill="listening", recommend_score=8.5, level="5-6"))
        repo.seed_resource(**_sample_resource(bv_id="BV2", skill="listening", recommend_score=9.0, level="6.5-7", is_featured=True))
        repo.seed_resource(**_sample_resource(bv_id="BV3", skill="reading", recommend_score=7.5, level="5-6", source_status="official"))
        repo.seed_resource(**_sample_resource(bv_id="BV4", skill="writing", recommend_score=8.0, level="6.5-7"))

    def test_list_filters_by_skill(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        self._seed_mixed(repo)
        results = repo.list_resources(skill="listening")
        assert len(results) == 2
        assert all(r["skill"] == "listening" for r in results)

    def test_list_filters_by_level(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        self._seed_mixed(repo)
        results = repo.list_resources(level="6.5-7")
        assert len(results) == 2

    def test_list_filters_by_source_status(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        self._seed_mixed(repo)
        results = repo.list_resources(source_status="official")
        assert len(results) == 1
        assert results[0]["bv_id"] == "BV3"

    def test_list_filters_by_is_featured(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        self._seed_mixed(repo)
        results = repo.list_resources(is_featured=True)
        assert len(results) == 1
        assert results[0]["bv_id"] == "BV2"

    def test_list_sort_by_recommend_score(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        self._seed_mixed(repo)
        results = repo.list_resources(sort_by="recommend_score", limit=10)
        # 9.0 → 8.5 → 8.0 → 7.5
        scores = [r["recommend_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_list_sort_by_sort_order(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        repo.seed_resource(**_sample_resource(bv_id="BVa", sort_order=200))
        repo.seed_resource(**_sample_resource(bv_id="BVb", sort_order=10))
        results = repo.list_resources(sort_by="sort_order")
        assert results[0]["bv_id"] == "BVb"
        assert results[1]["bv_id"] == "BVa"

    def test_list_limit_and_offset(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        for i in range(5):
            repo.seed_resource(**_sample_resource(bv_id=f"BV{i}"))
        first = repo.list_resources(limit=2, offset=0, sort_by="sort_order")
        second = repo.list_resources(limit=2, offset=2, sort_by="sort_order")
        assert len(first) == 2
        assert len(second) == 2
        assert first[0]["id"] != second[0]["id"]

    def test_list_featured(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        self._seed_mixed(repo)
        featured = repo.list_featured(limit=10)
        assert len(featured) >= 1
        assert all(r["is_featured"] == 1 for r in featured)

    def test_list_by_up(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        repo.seed_resource(**_sample_resource(bv_id="BV1", author_name="刘洪波"))
        repo.seed_resource(**_sample_resource(bv_id="BV2", author_name="刘洪波"))
        repo.seed_resource(**_sample_resource(bv_id="BV3", author_name="王勇"))
        results = repo.list_by_up("刘洪波", limit=10)
        assert len(results) == 2
        assert all(r["author_name"] == "刘洪波" for r in results)

    def test_list_distinct_ups(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        repo.seed_resource(**_sample_resource(bv_id="BV1", author_name="刘洪波"))
        repo.seed_resource(**_sample_resource(bv_id="BV2", author_name="刘洪波"))
        repo.seed_resource(**_sample_resource(bv_id="BV3", author_name="王勇"))
        ups = repo.list_distinct_ups()
        names = [u["author_name"] for u in ups]
        assert "刘洪波" in names and "王勇" in names
        # 刘洪波 排第一(count=2)
        assert ups[0]["author_name"] == "刘洪波"
        assert ups[0]["count"] == 2


class TestPrepResourceUpdateDelete:
    def test_update_resource_partial(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        rid = repo.seed_resource(**_sample_resource(bv_id="BVupd"))
        ok = repo.update_resource(rid, recommend_score=9.9, is_featured=True)
        assert ok is True
        loaded = repo.get_resource(rid)
        assert loaded["recommend_score"] == 9.9
        assert loaded["is_featured"] == 1

    def test_update_resource_ignores_unknown_field(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        rid = repo.seed_resource(**_sample_resource(bv_id="BVupd2"))
        # unknown_field 不在白名单,应被忽略(防 SQL 注入)
        ok = repo.update_resource(rid, unknown_field="DROP TABLE")
        assert ok is False

    def test_delete_resource(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        rid = repo.seed_resource(**_sample_resource(bv_id="BVdel"))
        assert repo.delete_resource(rid) is True
        assert repo.get_resource(rid) is None


class TestPrepResourceCount:
    def test_count_total(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        repo.seed_resource(**_sample_resource(bv_id="BV1", skill="listening"))
        repo.seed_resource(**_sample_resource(bv_id="BV2", skill="reading"))
        assert repo.count_resources() == 2

    def test_count_by_skill(self, tmp_path: Path) -> None:
        container = _make_container(tmp_path)
        repo = container.prep_resource
        repo.seed_resource(**_sample_resource(bv_id="BV1", skill="listening"))
        repo.seed_resource(**_sample_resource(bv_id="BV2", skill="listening"))
        repo.seed_resource(**_sample_resource(bv_id="BV3", skill="reading"))
        assert repo.count_resources(skill="listening") == 2
        assert repo.count_resources(skill="reading") == 1
        assert repo.count_resources(skill="writing") == 0

    def test_count_by_level_and_source(self, tmp_path: Path) -> None:
        """新增:v3.8 P3.1 web 端 count 需支持 level/source_status/is_featured,
        否则 /api/resources/list 会在 web 上 500。"""
        container = _make_container(tmp_path)
        repo = container.prep_resource
        repo.seed_resource(**_sample_resource(bv_id="BV1", skill="listening", level="5-6"))
        repo.seed_resource(**_sample_resource(bv_id="BV2", skill="listening", level="6.5-7"))
        repo.seed_resource(**_sample_resource(bv_id="BV3", skill="reading",  level="5-6", source_status="official"))
        repo.seed_resource(**_sample_resource(bv_id="BV4", skill="reading",  level="5-6", is_featured=True))

        # 单维度
        assert repo.count_resources(level="5-6") == 3
        assert repo.count_resources(level="6.5-7") == 1
        assert repo.count_resources(source_status="official") == 1
        assert repo.count_resources(is_featured=True) == 1
        assert repo.count_resources(is_featured=False) == 3

        # 多维度组合:service 层把全部过滤同时传给 count/list
        assert repo.count_resources(skill="listening", level="5-6") == 1
        assert repo.count_resources(skill="reading", level="5-6") == 2
        # BV4 source_status 默认 verified_repost,不是 official
        assert repo.count_resources(
            skill="reading", level="5-6", source_status="official", is_featured=True,
        ) == 0
        assert repo.count_resources(
            skill="reading", level="5-6", is_featured=True,
        ) == 1  # 只 BV4

        # 与 list_resources 行数对齐(防止 count/list 过滤条件漂移)
        rows = repo.list_resources(skill="reading", level="5-6", is_featured=True, limit=50)
        assert repo.count_resources(
            skill="reading", level="5-6", is_featured=True,
        ) == len(rows)