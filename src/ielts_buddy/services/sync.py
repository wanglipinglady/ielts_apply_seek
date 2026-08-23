"""SyncWorker（v3）：MySQL ↔ SQLite 双向增量同步。

核心职责：
  1. push：把本地 SQLite 里 ``sync_status='pending_upload'`` 的行推到 MySQL
  2. pull：把 MySQL 上 ``updated_at > last_pull_at`` 的新行拉到本地 SQLite
  3. 冲突解决：last-write-wins（按 ``updated_at`` 时间戳比较）

关键设计：
  - 每张业务表独立同步：personal_vocab / learning_records / vocab_categories /
    vocab_category_words / exam_sessions / grade_history / articles
  - sync_meta 单行表记录 last_pull_at / last_push_at / last_error
  - 写入同步状态：'synced' / 'pending_upload'
  - users 表单独处理（结构简单，按 username 拉取）
  - 同步过程全部走线程池 / asyncio.to_thread 避免阻塞事件循环

使用方式：
  Web 端：
    worker = start_sync_worker(container, interval_seconds=30)  # asyncio 后台任务
  CLI 端：
    daemon = start_sync_daemon(container, interval_seconds=30)   # threading daemon
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ielts_buddy.repositories.fallback_repo import FallbackContainer

logger = logging.getLogger(__name__)


# =============================================================
# 同步表定义
# =============================================================
# 每张表的列映射：左边 SQLite 列名 → 右边 MySQL 列名
# 必须在两端 schema 一致才同步（schema 升级脚本保证）

SYNC_TABLES: list[dict[str, Any]] = [
    {
        "name": "personal_vocab",
        "id_col": "id",
        "user_col": "user_id",
        "ts_col": "updated_at",
        # 业务列映射：两端 schema 字段一致时同名列直接列出。
        # MySQL 的 uk_pv_user_word = (user_id, word)；SQLite 同。
        # 所以 conflict_key 用 (user_id, word) 而不是 id，避免两侧自增 id 不一致。
        "cols": [
            "user_id", "word", "phonetic", "meaning", "pos", "band",
            "topic", "example", "example_cn", "note", "source",
            "created_at", "updated_at",
        ],
        "conflict_key": ["user_id", "word"],
        "include_id": False,  # id 由 MySQL 自增分配
    },
    {
        "name": "learning_records",
        "id_col": "id",
        "user_col": "user_id",
        "ts_col": "updated_at",
        "cols": [
            "user_id", "word", "word_data", "memory_level", "next_review",
            "learn_count", "correct_count", "wrong_count",
            "first_learned", "last_reviewed",
            "is_starred", "is_difficult",
            "source", "updated_at",
        ],
        "conflict_key": ["user_id", "word"],  # 用 (user_id, word) 作业务键
        "include_id": False,
    },
    {
        "name": "vocab_categories",
        "id_col": "id",
        "user_col": "user_id",
        "ts_col": "updated_at",
        # 注意：SQLite 端 vocab_categories 没有 word_count 列
        # MySQL 端 word_count 由触发器维护；sync 时不传该列即可
        "cols": [
            "user_id", "name", "description", "is_system",
            "created_at", "updated_at",
        ],
        "conflict_key": ["user_id", "name"],
        "include_id": False,
    },
    {
        # vocab_category_words: SQLite 端表结构是 (category_id, word_id, added_at)，
        # 完全没有 user_id/word 列；MySQL 端表结构完全不同。结构上不兼容 → 跳过。
        # 实际场景：分类-词条关联只是 UI 辅助，不需要跨设备同步。
        "name": "vocab_category_words",
        "skip": True,
    },
    {
        # exam_sessions: SQLite 的 id 是 TEXT (UUID)；MySQL 的 id 是 BIGINT。
        # 结构上不兼容 → 暂不加入 sync 范围，避免误删/误覆盖。
        # 如未来需要支持，可在 MySQL 把 id 改成 VARCHAR(64) + 应用层生成 UUID。
        "name": "exam_sessions",
        "skip": True,
    },
    {
        "name": "grade_history",
        "id_col": "id",
        "user_col": "user_id",
        "ts_col": "updated_at",
        "cols": [
            "user_id", "essay_text", "topic", "overall_score",
            "task_response_score", "coherence_score", "lexical_score",
            "grammar_score", "result_json", "task_type",
            "error_summary_json", "graded_at", "updated_at",
        ],
        "conflict_key": ["user_id", "id"],
        "include_id": True,  # 用 id 作业务键（SQLite 自增，MySQL 自增对齐）
    },
    {
        "name": "articles",
        "id_col": "id",
        "user_col": "user_id",
        "ts_col": "updated_at",
        "cols": [
            "user_id", "title", "source_text", "translation", "word_count",
            "diff_words_json", "translation_source", "analysis_source",
            "created_at", "updated_at",
        ],
        "conflict_key": ["user_id", "id"],
        "include_id": True,
    },
]


def _now_iso() -> str:
    """UTC ISO 格式时间戳（同步时间戳基准）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_error_log(errors: list[str]) -> None:
    """把本轮 sync 错误追加到 ``~/.ielts-buddy/sync_errors.log``。

    用途：
      - Web/CLI 静默运行时，同步异常写到文件，便于事后排查
      - 比 stdlib logging 更直接，不需要配 handler
    """
    if not errors:
        return
    try:
        from ielts_buddy.core.config import get_app_dir
        log_path = Path(get_app_dir()) / "sync_errors.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {_now_iso()} ---\n")
            for err in errors:
                f.write(f"  {err}\n")
    except Exception:
        # 日志写失败不应阻塞主流程
        logger.warning("写 sync_errors.log 失败", exc_info=True)


# =============================================================
# 同步结果统计
# =============================================================


class SyncResult:
    """单次同步结果汇总。"""

    def __init__(self):
        self.pushed = 0   # 本地 → MySQL
        self.pulled = 0   # MySQL → 本地
        self.skipped = 0  # 无变化跳过
        self.errors: list[str] = []

    @property
    def total(self) -> int:
        return self.pushed + self.pulled

    def __str__(self) -> str:
        return (
            f"push={self.pushed}, pull={self.pulled}, "
            f"skip={self.skipped}, errors={len(self.errors)}"
        )


# =============================================================
# SyncWorker 主体
# =============================================================


class SyncWorker:
    """同步器：负责一对 Pull + Push 操作。"""

    def __init__(self, container: FallbackContainer):
        self.container = container
        self._lock = threading.Lock()

    # ---- 公开 API ----

    def sync_once(self) -> SyncResult:
        """执行一轮完整同步。返回 SyncResult。

        流程：
          1. 检查 MySQL 可达性；不可达直接返回（不报错）
          2. push：本地的 pending_upload 推到 MySQL
          3. pull：MySQL 的增量拉到本地
          4. 更新 sync_meta.last_pull_at / last_push_at
        """
        with self._lock:
            result = SyncResult()
            try:
                if not self.container.try_mysql():
                    result.errors.append("MySQL 不可达，跳过本轮同步")
                    return result
                if self.container.online is None:
                    result.errors.append("未配置 MySQL container")
                    return result

                # push first（本地优先让数据上 MySQL）
                try:
                    pushed = self._push_all()
                    result.pushed = pushed
                except Exception as e:
                    logger.exception("push 阶段失败")
                    result.errors.append(f"push: {e}")

                # pull
                try:
                    pulled = self._pull_all()
                    result.pulled = pulled
                except Exception as e:
                    logger.exception("pull 阶段失败")
                    result.errors.append(f"pull: {e}")

                # 更新元数据
                try:
                    self._update_meta(
                        push_ts=_now_iso() if result.pushed > 0 else None,
                        pull_ts=_now_iso() if result.pulled > 0 else None,
                        error="\n".join(result.errors) if result.errors else None,
                    )
                except Exception as e:
                    logger.warning("更新 sync_meta 失败: %s", e)

                # v3：把错误同时写到 ~/.ielts-buddy/sync_errors.log
                _append_error_log(result.errors)

            except Exception as e:
                logger.exception("sync_once 总异常")
                result.errors.append(f"general: {e}")
                _append_error_log(result.errors)
            return result

    # ---- push: 本地 → MySQL ----

    def _push_all(self) -> int:
        """把本地 SQLite 标记为 pending_upload 的所有行推到 MySQL。

        每张表独立：先拿 pending_upload 行，按 last-write-wins 检查 MySQL；
        没有冲突或本地更新 → INSERT/UPDATE；本地冲突 → 更新本地时间戳。
        """
        total_pushed = 0
        sqlite_conn = self.container.offline._conn
        mysql_engine = self.container.online._engine

        for spec in SYNC_TABLES:
            try:
                pushed = self._push_table(spec, sqlite_conn, mysql_engine)
                total_pushed += pushed
            except Exception as e:
                logger.warning("push %s 失败: %s", spec["name"], e)
        return total_pushed

    def _push_table(
        self,
        spec,
        sqlite_conn: sqlite3.Connection,
        mysql_engine,
    ) -> int:
        if spec.get("skip"):
            return 0
        table = spec["name"]
        ts_col = spec["ts_col"]
        cols = spec["cols"]
        conflict_key = spec["conflict_key"]
        include_id = spec.get("include_id", False)

        # 1. 拿本地 pending 行
        cur = sqlite_conn.execute(
            f"SELECT {', '.join(cols)} FROM {table} "
            f"WHERE sync_status='pending_upload'"
        )
        rows = cur.fetchall()
        if not rows:
            return 0

        pushed = 0
        pushed_keys: list[tuple] = []  # 记录实际成功 push 的 conflict_key 组合

        with mysql_engine.begin() as conn:
            for row in rows:
                row_dict = dict(zip(cols, row))

                # 2. 查 MySQL 端对应行（按 conflict_key）
                # 用 :key 命名占位符 + dict，避免 SQLAlchemy list 绑定报错
                where_clause = " AND ".join(
                    f"`{k}`=:{k}" for k in conflict_key
                )
                where_params = {k: row_dict[k] for k in conflict_key}
                sel_sql = f"SELECT `{ts_col}` FROM `{table}` WHERE {where_clause}"
                mysql_row = conn.execute(
                    text(sel_sql), where_params
                ).first()

                if mysql_row is not None:
                    # 冲突：按 updated_at 比较
                    local_ts = row_dict.get(ts_col) or ""
                    remote_ts = str(mysql_row[0]) if mysql_row[0] else ""
                    if self._compare_ts(local_ts, remote_ts) <= 0:
                        # 远端更新或相等 → 放弃本次 push，让 pull 覆盖本地
                        # 标记本地这一行为 synced（避免下次再 push）
                        sqlite_conn.execute(
                            f"UPDATE {table} SET sync_status='synced' "
                            f"WHERE {' AND '.join(f'`{k}`=?' for k in conflict_key)}",
                            [row_dict[k] for k in conflict_key],
                        )
                        sqlite_conn.commit()
                        continue

                # 3. UPSERT：INSERT ... ON DUPLICATE KEY UPDATE
                # include_id=False 时不写 id 列，让 MySQL 自增分配
                if include_id:
                    insert_cols = cols
                    update_cols = [c for c in cols if c != "id"]
                else:
                    insert_cols = [c for c in cols if c != "id"]
                    update_cols = insert_cols

                col_list = ", ".join(f"`{c}`" for c in insert_cols)
                placeholders = ", ".join(f":{c}" for c in insert_cols)
                update_part = ", ".join(
                    f"`{c}`=VALUES(`{c}`)" for c in update_cols
                )

                upsert_sql = (
                    f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders}) "
                    f"ON DUPLICATE KEY UPDATE {update_part}, "
                    f"`sync_status`='synced'"
                )
                # ON DUPLICATE KEY UPDATE 同时会更新 updated_at 列（如果有）
                # 再次写 updated_at 以保证冲突解决后远端时间戳前进
                if ts_col not in update_cols:
                    upsert_sql += f", `{ts_col}`=CURRENT_TIMESTAMP"

                conn.execute(text(upsert_sql), row_dict)
                pushed += 1
                pushed_keys.append(tuple(row_dict[k] for k in conflict_key))

        # 4. 只把"实际成功 push"的本地行标记为 synced
        #    （之前一行 UPDATE 标记全部 pending 行 → 误把冲突跳过的行也标记了）
        if pushed_keys:
            # 用 OR 链把每个 conflict_key 组合拼出来
            # 对组合数 < 50 时性能没问题；超过时按 conflict_key 单独 UPDATE
            for key_tuple in pushed_keys:
                sqlite_conn.execute(
                    f"UPDATE {table} SET sync_status='synced' "
                    f"WHERE {' AND '.join(f'`{k}`=?' for k in conflict_key)}",
                    list(key_tuple),
                )
            sqlite_conn.commit()

        return pushed

    # ---- pull: MySQL → 本地 ----

    def _pull_all(self) -> int:
        total_pulled = 0
        sqlite_conn = self.container.offline._conn
        mysql_engine = self.container.online._engine

        # 取上次同步时间
        last_pull_at = self._get_last_pull_at()

        for spec in SYNC_TABLES:
            try:
                pulled = self._pull_table(spec, sqlite_conn, mysql_engine, last_pull_at)
                total_pulled += pulled
            except Exception as e:
                logger.warning("pull %s 失败: %s", spec["name"], e)
        return total_pulled

    def _pull_table(
        self,
        spec,
        sqlite_conn: sqlite3.Connection,
        mysql_engine,
        last_pull_at: Optional[str],
    ) -> int:
        if spec.get("skip"):
            return 0
        table = spec["name"]
        ts_col = spec["ts_col"]
        cols = spec["cols"]
        include_id = spec.get("include_id", False)

        # include_id=True 时用 id 列；否则按 conflict_key 列查 SQLite 本地行
        # SQLite 本地表必须有 UNIQUE (conflict_key...) 才能用 INSERT ON CONFLICT
        select_cols_sql = ", ".join(f"`{c}`" for c in cols)

        # MySQL 端拉（updated_at > last_pull_at 的所有行）
        if last_pull_at:
            sel_sql = (
                f"SELECT {select_cols_sql} "
                f"FROM `{table}` "
                f"WHERE `{ts_col}` > :last_pull_at "
                f"ORDER BY `{ts_col}` ASC"
            )
            params = {"last_pull_at": last_pull_at}
        else:
            sel_sql = (
                f"SELECT {select_cols_sql} "
                f"FROM `{table}` ORDER BY `{ts_col}` ASC LIMIT 1000"
            )
            params = {}

        with mysql_engine.connect() as conn:
            rows = list(conn.execute(text(sel_sql), params).fetchall())

        if not rows:
            return 0

        # 本地：INSERT ... ON CONFLICT DO UPDATE（比 INSERT OR REPLACE 安全）
        pulled = 0
        conflict_key = spec["conflict_key"]

        # 注意：SQLite 的 INSERT ... ON CONFLICT 要求目标必须是 UNIQUE/PRIMARY KEY
        # SQLite 端的 UNIQUE 约束是否与 conflict_key 列顺序一致？
        # - personal_vocab: UNIQUE (user_id, word) ✓
        # - learning_records: UNIQUE (user_id, word) ✓
        # - vocab_categories: UNIQUE (user_id, name) ✓
        # - vocab_category_words: PRIMARY KEY (category_id, word_id)，但 sync 时
        #   用的是 (user_id, category_id, word)，无 UNIQUE → 改用 INSERT OR REPLACE
        # - grade_history: PRIMARY KEY (id)；conflict_key 是 [user_id, id]，
        #   列顺序不匹配 → 不能用 ON CONFLICT (user_id, id)；改用 [id] 单列 PK
        #   注意：SQLite PRIMARY KEY 隐含 UNIQUE，单列也支持
        # - articles: PRIMARY KEY (id)，conflict_key 是 [user_id, id]，同样列序
        #   不匹配；改用 [id]

        # 决定 ON CONFLICT 子句的目标列
        if table == "personal_vocab":
            conflict_target = ["user_id", "word"]
        elif table == "learning_records":
            conflict_target = ["user_id", "word"]
        elif table == "vocab_categories":
            conflict_target = ["user_id", "name"]
        elif table == "grade_history":
            conflict_target = ["id"]
        elif table == "articles":
            conflict_target = ["id"]
        else:
            conflict_target = None

        use_on_conflict = conflict_target is not None

        for row in rows:
            row_dict = dict(zip(cols, row))
            where = " AND ".join(f"`{k}`=?" for k in conflict_key)
            where_args = [row_dict[k] for k in conflict_key]

            cur = sqlite_conn.execute(
                f"SELECT `{ts_col}` FROM {table} WHERE {where}",
                where_args,
            )
            local_row = cur.fetchone()

            if local_row is not None:
                local_ts = local_row[0] or ""
                remote_ts = row_dict.get(ts_col) or ""
                if self._compare_ts(remote_ts, local_ts) < 0:
                    # 远端旧于本地 → 不覆盖
                    continue

            # 准备 INSERT 参数（按 conflict_target 唯一索引做 UPSERT）
            if use_on_conflict:
                insert_sql = (
                    f"INSERT INTO {table} "
                    f"({', '.join(f'`{c}`' for c in cols)}, sync_status) "
                    f"VALUES ({', '.join('?' for _ in cols)}, 'synced') "
                    f"ON CONFLICT ({', '.join(conflict_target)}) DO UPDATE SET "
                    + ", ".join(
                        f"`{c}`=excluded.`{c}`" for c in cols
                    )
                    + ", sync_status='synced'"
                )
                args = [row_dict[c] for c in cols]  # sync_status 已用字面量 'synced'
            else:
                # vocab_category_words 这类：fallback 到 INSERT OR REPLACE
                insert_sql = (
                    f"INSERT OR REPLACE INTO {table} "
                    f"({', '.join(f'`{c}`' for c in cols)}, sync_status) "
                    f"VALUES ({', '.join('?' for _ in cols)}, 'synced')"
                )
                args = [row_dict[c] for c in cols]

            sqlite_conn.execute(insert_sql, args)
            pulled += 1
        sqlite_conn.commit()
        return pulled

    # ---- 工具方法 ----

    @staticmethod
    def _compare_ts(a, b) -> int:
        """比较两个时间戳，返回 -1 / 0 / 1（a 与 b）。

        支持的输入：
          - str（ISO 格式）
          - datetime（来自 MySQL row 直接取出）
          - None / 空字符串 → 视为"无值"
        """
        # 统一转成 datetime（UTC）
        def _coerce(v):
            if v is None or v == "":
                return None
            if isinstance(v, datetime):
                # MySQL 返回的 datetime 通常是 naive（不带 tz），
                # 按 UTC 处理（数据库连接时区假设）
                if v.tzinfo is None:
                    return v.replace(tzinfo=timezone.utc)
                return v
            if isinstance(v, str):
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00"))
                except ValueError:
                    return None
            return None

        ta = _coerce(a)
        tb = _coerce(b)
        if ta is None and tb is None:
            return 0
        if ta is None:
            return -1
        if tb is None:
            return 1
        try:
            if ta < tb:
                return -1
            if ta > tb:
                return 1
            return 0
        except TypeError:
            return 0  # 不可比较 → 当作相等

    def _get_last_pull_at(self) -> Optional[str]:
        sqlite_conn = self.container.offline._conn
        cur = sqlite_conn.execute(
            "SELECT last_pull_at FROM sync_meta WHERE id=1"
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None

    def _update_meta(
        self,
        push_ts: Optional[str],
        pull_ts: Optional[str],
        error: Optional[str],
    ) -> None:
        sqlite_conn = self.container.offline._conn
        parts = ["id=1"]
        args: list[Any] = []
        if push_ts:
            parts.append("last_push_at=?")
            args.append(push_ts)
        if pull_ts:
            parts.append("last_pull_at=?")
            args.append(pull_ts)
        if error is not None:
            parts.append("last_error=?, last_error_at=?")
            args.extend([error, _now_iso()])
        sqlite_conn.execute(
            f"UPDATE sync_meta SET {', '.join(parts)} WHERE id=1", args
        )
        sqlite_conn.commit()


# =============================================================
# 标记本地写操作为 pending_upload 的工具
# =============================================================


def mark_pending_upload(
    container: FallbackContainer,
    table: str,
    conflict_key_values: dict[str, Any],
) -> None:
    """写入数据后，标记某行为 ``pending_upload``，等待 SyncWorker 推到 MySQL。

    Args:
        container: FallbackContainer（必须已初始化）
        table: 表名（如 "personal_vocab"）
        conflict_key_values: 业务键字典，如 {"user_id": 1, "word": "test"}
    """
    sqlite_conn = container.offline._conn
    where = " AND ".join(f"`{k}`=?" for k in conflict_key_values)
    args = list(conflict_key_values.values())
    sqlite_conn.execute(
        f"UPDATE {table} SET sync_status='pending_upload', "
        f"updated_at=? WHERE {where}",
        [_now_iso()] + args,
    )
    sqlite_conn.commit()


# =============================================================
# 后台 worker 启动器
# =============================================================


class SyncDaemonThread(threading.Thread):
    """CLI 端：threading 后台 daemon。"""

    def __init__(self, container: FallbackContainer, interval_seconds: int = 30):
        super().__init__(daemon=True, name="SyncWorker-Daemon")
        self.worker = SyncWorker(container)
        self.interval = max(5, interval_seconds)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        logger.info("SyncWorker daemon 启动，间隔 %ds", self.interval)
        while not self._stop_event.is_set():
            try:
                result = self.worker.sync_once()
                if result.total or result.errors:
                    logger.info("sync: %s", result)
            except Exception:
                logger.exception("SyncWorker 异常")
            # 等间隔（被 stop 时立刻退出）
            if self._stop_event.wait(self.interval):
                break
        logger.info("SyncWorker daemon 停止")


class SyncWorkerAsync:
    """Web 端：asyncio 后台任务。"""

    def __init__(self, container: FallbackContainer, interval_seconds: int = 30):
        self.worker = SyncWorker(container)
        self.interval = max(5, interval_seconds)
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def _loop(self):
        logger.info("SyncWorker async 启动，间隔 %ds", self.interval)
        while not self._stop_event.is_set():
            try:
                # sync_once 走 sqlite + MySQL，全是阻塞调用 → 放到线程池
                result = await asyncio.to_thread(self.worker.sync_once)
                if result.total or result.errors:
                    logger.info("sync: %s", result)
            except Exception:
                logger.exception("SyncWorker 异常")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval)
                break  # stop 被 set
            except asyncio.TimeoutError:
                pass  # 继续循环
        logger.info("SyncWorker async 停止")

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop())

    async def stop_async(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    def stop(self) -> None:
        """同步停止接口（lifespan 关闭时用）。"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.stop_async())
                return
        except RuntimeError:
            pass
        # 没在 event loop 里：直接 set 让任务下次循环退出
        self._stop_event.set()


def start_sync_worker(
    container: FallbackContainer,
    interval_seconds: int = 30,
) -> SyncWorkerAsync:
    """启动 Web 端 asyncio 同步任务。"""
    if interval_seconds <= 0:
        logger.info("IELTS_BUDDY_SYNC_INTERVAL_SEC=0，关闭同步")
        return None
    worker = SyncWorkerAsync(container, interval_seconds=interval_seconds)
    worker.start()
    return worker


def start_sync_daemon(
    container: FallbackContainer,
    interval_seconds: int = 30,
) -> Optional[SyncDaemonThread]:
    """启动 CLI 端 threading daemon 同步。"""
    if interval_seconds <= 0:
        return None
    daemon = SyncDaemonThread(container, interval_seconds=interval_seconds)
    daemon.start()
    return daemon


__all__ = [
    "SyncWorker",
    "SyncWorkerAsync",
    "SyncDaemonThread",
    "SyncResult",
    "start_sync_worker",
    "start_sync_daemon",
    "mark_pending_upload",
    "SYNC_TABLES",
]