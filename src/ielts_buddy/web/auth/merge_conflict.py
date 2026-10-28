"""合并冲突消解逻辑（SQLite / MySQL 共用）。

背景：
合并两个账号时，目标账号（PC 老账号）和源账号（微信占位账号）都持有
**系统内置分类** ``favorites`` / ``mistakes``，而 ``vocab_categories`` 上有
``UNIQUE(user_id, name)`` —— 直接 UPDATE user_id 必然撞
``Duplicate entry '1155-favorites' for key 'vocab_categories.uk_vc_user_name'``。

同理：
- ``learning_records`` / ``personal_vocab`` 有 ``UNIQUE(user_id, word)``
  → 两个账号学的同一个词会撞
- ``vocab_category_words`` 有 ``UNIQUE(user_id, category_id, word)``
  → 分类合并后，源账号该分类下的词条会和目标账号撞

消解策略（"目标账号优先"，源账号数据作为补充）：
1. **分类**（vocab_categories）：同名分类 → 合并到目标分类（保留目标 id），
   源分类下的词条改挂到目标分类；源分类里目标没有的 → 直接改 user_id 带过去
2. **词条**（learning_records / personal_vocab）：同一个 word 已在目标账号存在
   → 保留目标那条，丢弃源那条；源没有的 → 直接迁移
3. **分类-词条关联**（vocab_category_words）：按 (user_id, category_id, word)
   去重，源里重复的关联直接删掉

两端连接形态不同：
- MySQL：SQLAlchemy Connection（有 ``exec_driver_sql``）
- SQLite：原生 ``sqlite3.Connection``（只有 ``execute``）
所以这里用一层薄适配，两边都走同一套逻辑。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


# 分类冲突消解涉及的表
_CATEGORY_TABLE = "vocab_categories"
_CATEGORY_LINK_TABLE = "vocab_category_words"

# 有 UNIQUE(user_id, word) 的"词条"表
_WORD_TABLES = ["learning_records", "personal_vocab"]


class _Executor:
    """把 SQLAlchemy Connection 和原生 sqlite3.Connection 统一成 ``execute``。

    占位符差异（踩过的坑）：
    - SQLite 原生驱动：``?``
    - PyMySQL：``%s``（不是 ``?``！用 ``?`` 会报
      "not all arguments converted during string formatting"，
      检测函数会静默返回空 → 冲突消解被整段跳过 → 合并必然撞唯一键）

    所以统一由本类把 ``?`` 转成目标驱动的占位符。
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._is_sqlite = isinstance(conn, sqlite3.Connection)

    @property
    def is_sqlite(self) -> bool:
        """是否为 SQLite 驱动（两端 SQL 方言不同）。"""
        return self._is_sqlite

    def _adapt(self, sql: str) -> str:
        """把 ``?`` 占位符转成目标驱动认识的格式。"""
        if self._is_sqlite:
            return sql
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: tuple = ()) -> Any:
        if self._is_sqlite:
            return self._conn.execute(sql, params)
        return self._conn.exec_driver_sql(self._adapt(sql), params)

    def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        return list(self.execute(sql, params).fetchall())

    def row(self, sql: str, params: tuple = ()) -> Any:
        return self.execute(sql, params).fetchone()


def _table_exists(ex: _Executor, table: str) -> bool:
    """判断表是否存在。"""
    try:
        rows = ex.rows(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?",
            (table,),
        )
        if rows:
            return True
    except Exception as exc:
        logger.debug("[merge] _table_exists(%s) 查询失败: %s", table, exc)
    try:
        rows = ex.rows(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        )
        return bool(rows)
    except Exception:
        return False


def _columns(ex: _Executor, table: str) -> list[str]:
    """取表的列名列表。"""
    try:
        rows = ex.rows(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
            (table,),
        )
        if rows:
            return [str(r[0]) for r in rows]
    except Exception as exc:
        logger.debug("[merge] _columns(%s) 查询失败: %s", table, exc)
    try:
        rows = ex.rows("PRAGMA table_info(%s)" % table)
        return [str(r[1]) for r in rows]
    except Exception as exc:
        logger.debug("[merge] PRAGMA table_info(%s) 失败: %s", table, exc)
        return []


def _has_user_id_column(ex: _Executor, table: str) -> bool:
    """判断表是否有 user_id 列。

    SQLite 端的 ``vocab_category_words`` 结构是 (category_id, word_id, added_at)，
    **没有 user_id** —— 与 MySQL 端 (user_id, category_id, word) 完全不同。
    这类表无法按 user_id 迁移，合并时必须跳过。
    """
    return "user_id" in _columns(ex, table)


def _repoint_category_links(
    ex: _Executor,
    src_category_id: Any,
    dst_category_id: Any,
    from_user_id: int,
    to_user_id: int,
) -> None:
    """把源分类下的"分类-词条关联"改挂到目标分类。

    两端结构不同，这里分别处理：
    - MySQL ``(user_id, category_id, word, added_at)``：
      ``UPDATE ... SET category_id = dst WHERE user_id = src AND category_id = src_cat``
    - SQLite ``(category_id, word_id, added_at)``：**没有 user_id**，
      靠 ``word_id`` 关联 personal_vocab。只能按 category_id 定位，
      再用 word_id 反查该词属于哪个 user，把"源用户的词"的关联改挂到目标分类，
      "目标用户已有的词"的关联直接删掉（避免主键冲突）。
    """
    if not _table_exists(ex, _CATEGORY_LINK_TABLE):
        return
    cols = _columns(ex, _CATEGORY_LINK_TABLE)
    if "category_id" not in cols:
        return

    if "user_id" in cols and "word" in cols:
        # MySQL 结构
        try:
            ex.execute(
                "UPDATE `%s` SET category_id = %s "
                "WHERE user_id = %s AND category_id = %s"
                % (_CATEGORY_LINK_TABLE, dst_category_id, from_user_id, src_category_id)
            )
        except Exception as exc:
            logger.warning("[merge] 分类关联迁移失败: %s", exc)
        return

    if "word_id" in cols:
        # SQLite 结构：没有 user_id，靠 word_id → personal_vocab.user_id 判断归属
        if not _table_exists(ex, "personal_vocab"):
            return
        try:
            # 目标用户已有的词 → 关联会与目标账号的关联主键冲突 → 删掉
            ex.execute(
                "DELETE FROM `%s` WHERE category_id = %s AND word_id IN ("
                "  SELECT id FROM personal_vocab WHERE user_id = %s)"
                % (_CATEGORY_LINK_TABLE, src_category_id, to_user_id)
            )
            # 源用户的词 → 改挂到目标分类
            ex.execute(
                "UPDATE `%s` SET category_id = %s WHERE category_id = %s AND word_id IN ("
                "  SELECT id FROM personal_vocab WHERE user_id = %s)"
                % (_CATEGORY_LINK_TABLE, dst_category_id, src_category_id, from_user_id)
            )
        except Exception as exc:
            logger.warning("[merge] SQLite 分类关联迁移失败: %s", exc)


def resolve_merge_conflicts(conn: Any, from_user_id: int, to_user_id: int) -> dict[str, int]:
    """在迁移 user_id **之前**消解所有唯一约束冲突。

    必须与后续的 UPDATE 处在**同一个事务**里，否则消解结果可能被别的连接看到。

    返回：各类消解动作的计数（用于日志 / 审计）。
    """
    ex = _Executor(conn)
    stats = {
        "categories_merged": 0,
        "categories_moved": 0,
        "words_dropped": 0,
        "links_dropped": 0,
    }

    # ---------- 1. 分类冲突 ----------
    if _table_exists(ex, _CATEGORY_TABLE) and _has_user_id_column(ex, _CATEGORY_TABLE):
        cols = _columns(ex, _CATEGORY_TABLE)
        if "id" in cols and "name" in cols:
            src_cats = ex.rows(
                "SELECT id, name FROM `%s` WHERE user_id = ?" % _CATEGORY_TABLE,
                (from_user_id,),
            )
            for row in src_cats:
                src_id = row[0]
                name = row[1]
                dst_same = ex.row(
                    "SELECT id FROM `%s` WHERE user_id = ? AND name = ? LIMIT 1"
                    % _CATEGORY_TABLE,
                    (to_user_id, name),
                )
                if dst_same is not None:
                    dst_id = dst_same[0]
                    # 源分类下的关联改挂到目标分类
                    _repoint_category_links(ex, src_id, dst_id, from_user_id, to_user_id)
                    # 源分类本身和目标重名 → 删掉
                    ex.execute(
                        "DELETE FROM `%s` WHERE id = %s" % (_CATEGORY_TABLE, src_id)
                    )
                    stats["categories_merged"] += 1
                else:
                    # 目标没有同名分类 → 整体带过去
                    ex.execute(
                        "UPDATE `%s` SET user_id = %s WHERE id = %s"
                        % (_CATEGORY_TABLE, to_user_id, src_id)
                    )
                    stats["categories_moved"] += 1

    # ---------- 2. 词条冲突 ----------
    for table in _WORD_TABLES:
        if not _table_exists(ex, table) or not _has_user_id_column(ex, table):
            continue
        cols = _columns(ex, table)
        if "word" not in cols:
            continue
        # 源账号里已经在目标账号存在的词 → 丢弃源那条
        #
        # 两端方言不同（踩过的坑）：
        # - MySQL 不允许 DELETE 的子查询引用被删的那张表
        #   （ERROR 1093: You can't specify target table for update in FROM clause），
        #   必须用多表 DELETE：DELETE src FROM src JOIN dst ON src.word=dst.word
        # - SQLite **不支持**多表 DELETE，只能用 IN 子查询
        try:
            if ex.is_sqlite:
                cur = ex.execute(
                    "DELETE FROM `%s` WHERE user_id = ? AND word IN "
                    "(SELECT word FROM `%s` WHERE user_id = ?)" % (table, table),
                    (from_user_id, to_user_id),
                )
            else:
                cur = ex.execute(
                    "DELETE src FROM `%s` src JOIN `%s` dst ON src.word = dst.word "
                    "WHERE src.user_id = ? AND dst.user_id = ?" % (table, table),
                    (from_user_id, to_user_id),
                )
            stats["words_dropped"] += (cur.rowcount or 0)
        except Exception as exc:
            logger.warning("[merge] %s 词条去重失败: %s", table, exc)

    # ---------- 3. 分类-词条关联去重 ----------
    if _table_exists(ex, _CATEGORY_LINK_TABLE):
        link_cols = _columns(ex, _CATEGORY_LINK_TABLE)
        if "user_id" in link_cols and "category_id" in link_cols and "word" in link_cols:
            # MySQL 结构：(user_id, category_id, word, added_at)
            try:
                cur = ex.execute(
                    "DELETE FROM `%s` WHERE user_id = %s AND EXISTS ("
                    "  SELECT 1 FROM (SELECT category_id, word FROM `%s` WHERE user_id = %s) d "
                    "  WHERE d.category_id = `%s`.category_id AND d.word = `%s`.word"
                    ")" % (
                        _CATEGORY_LINK_TABLE, from_user_id,
                        _CATEGORY_LINK_TABLE, to_user_id,
                        _CATEGORY_LINK_TABLE, _CATEGORY_LINK_TABLE,
                    )
                )
                stats["links_dropped"] += (cur.rowcount or 0)
            except Exception as exc:
                logger.warning("[merge] 分类关联去重失败: %s", exc)

    if any(stats.values()):
        logger.info("[merge] 冲突消解: %s", stats)
    return stats
