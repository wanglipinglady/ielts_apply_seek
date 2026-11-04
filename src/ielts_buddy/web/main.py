"""Web 入口：FastAPI app 工厂 + uvicorn 启动。

启动：
    PYTHONPATH=src python -m ielts_buddy.web.main
    # 或：
    PYTHONPATH=src uvicorn ielts_buddy.web.main:app --reload --port 8000

阶段 1：web_user_repo（SQLite 内存） + auth 路由。
阶段 2：在 lifespan 阶段同步打开业务仓库容器（SQLite，与 CLI data.db 物理隔离），
         Service 通过"借壳"方式注入 user_id。
"""
from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ielts_buddy.repositories import create_repositories
from ielts_buddy.web import config as web_config
from ielts_buddy.web.auth.repository import (
    SQLiteWebUserRepository,
    create_sqlite_web_user_repository,
    MySQLWebUserRepository,
)
from ielts_buddy.web.routers import auth as auth_routes
from ielts_buddy.web.routers import pages as pages_routes
from ielts_buddy.web.routers import stats as stats_routes
from ielts_buddy.web.routers import study as study_routes
from ielts_buddy.web.routers import quiz as quiz_routes
from ielts_buddy.web.routers import browse as browse_routes
from ielts_buddy.web.routers import lookup as lookup_routes
from ielts_buddy.web.routers import personal as personal_routes
from ielts_buddy.web.routers import exam as exam_routes
from ielts_buddy.web.routers import grade as grade_routes
from ielts_buddy.web.routers import plan as plan_routes
from ielts_buddy.web.routers import report as report_routes
from ielts_buddy.web.routers import articles as articles_routes
from ielts_buddy.web.routers import typing as typing_routes
from ielts_buddy.web.routers import pomodoro as pomodoro_routes
from ielts_buddy.web.routers import calendar as calendar_routes
from ielts_buddy.web.routers import write as write_routes
from ielts_buddy.web.routers import listening as listening_routes
from ielts_buddy.web.routers import speak as speak_routes
from ielts_buddy.web.routers import mistakes as mistakes_routes
from ielts_buddy.web.routers import speaking_practice as speaking_practice_routes
from ielts_buddy.web.routers import listening_practice as listening_practice_routes
from ielts_buddy.web.routers import prep_resources as prep_resources_routes
from ielts_buddy.web.routers import reading_practice as reading_practice_routes
from ielts_buddy.web.routers import voice_training as voice_training_routes  # v3.9 W11：语音训练工坊
from ielts_buddy.web.routers import wechat as wechat_routes  # v3.9+：微信小程序登录（2026-08-24）
from ielts_buddy.web.routers import wx_study as wx_study_routes  # v3.9+：小程序学习 API（2026-08-24）
from ielts_buddy.web.routers import wx_speak as wx_speak_routes  # v3.9+：小程序口语 API（2026-08-24）
from ielts_buddy.web.routers import wx_grade as wx_grade_routes  # v3.9+：小程序写作批改 API（2026-08-24）

# 模板目录 = 本文件所在目录/templates
WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


def _build_templates() -> Jinja2Templates:
    """构造 Jinja2 模板对象，注入全局变量。"""
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.globals["app_name"] = "IELTS Buddy"
    templates.env.globals["app_version"] = "0.1.0"
    return templates





@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """v3 启动：MySQL 主存 + SQLite 自动降级。

    - 测试覆盖：如果 app.state.container 已被 conftest 注入，跳过
    - 默认行为：按 ``IELTS_BUDDY_WEB_DB_MODE`` 配置选择 prefer_mode
      - online（默认）：尝试连 MySQL；不通则降级到 SQLite
      - sqlite：强制本地 SQLite，不创建 MySQL container
    - web_user_repo：随当前 backend 切换（online 用 MySQLWebUserRepository，
      fallback 用 SQLiteWebUserRepository）
    """
    # 测试覆盖：如果 app.state.container 已被 conftest 注入，跳过
    if getattr(app.state, "container", None) is None:
        from ielts_buddy.repositories.fallback_repo import create_fallback_container

        sqlite_path = Path(web_config.get_web_db_path())
        prefer_mode = (
            "sqlite" if web_config.WEB_DB_MODE == "sqlite"
            else "online"
        )
        app.state.container = create_fallback_container(
            sqlite_db_path=sqlite_path,
            mysql_url=web_config.WEB_DB_URL,
            prefer_mode=prefer_mode,
        )

    # web_user_repo：复用当前 backend 的连接
    if getattr(app.state, "web_user_repo", None) is None:
        app.state.web_user_repo = _open_default_user_repo()

    # 启动后台同步任务（v3）
    if getattr(app.state, "sync_worker", None) is None:
        from ielts_buddy.services.sync import start_sync_worker
        interval = int(os.environ.get("IELTS_BUDDY_SYNC_INTERVAL_SEC", "30"))
        app.state.sync_worker = start_sync_worker(
            container=app.state.container,
            interval_seconds=interval,
        )

    # v3.7 P1：启动期清理过期录音(7 天前)。失败也无所谓,
    #   用户的当前请求不受影响。日志里能看到清理数量。
    try:
        from ielts_buddy.services.speaking_practice_service import (
            purge_all_expired_audio,
        )
        result = purge_all_expired_audio(
            container=app.state.container,
            retention_days=web_config.SPEAKING_AUDIO_RETENTION_DAYS,
        )
        if result["files_deleted"] or result["records_audio_nulled"]:
            import logging as _logging
            _logging.getLogger(__name__).info(
                "[speaking] startup cleanup: %s",
                result,
            )
    except Exception as _exc:
        # 启动期清理失败不阻塞 web,记 warning 即可
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[speaking] startup cleanup failed: %s", _exc
        )

    # v3.7 P2：启动期清理过期听力音频(30 天前)。
    try:
        from ielts_buddy.services.listening_practice_service import (
            purge_expired_audio,
        )
        result = purge_expired_audio(
            container=app.state.container,
            retention_days=web_config.LISTENING_AUDIO_RETENTION_DAYS,
        )
        if result["files_deleted"] or result["rows_nulled"]:
            import logging as _logging
            _logging.getLogger(__name__).info(
                "[listening] startup audio cleanup: %s",
                result,
            )
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[listening] startup audio cleanup failed: %s", _exc
        )

    # v3.7 P2：启动期种子题库(LLM 出题 + TTS 合成 30 套)。
    # 设计:fire-and-forget 后台跑,不阻塞 web 启动;已有题则跳过。
    try:
        import logging as _logging
        from ielts_buddy.services.listening_practice_service import (
            seed_initial_questions,
        )
        import threading

        def _seed_in_background():
            try:
                result = seed_initial_questions(
                    container=app.state.container,
                    auto_trigger_tts=web_config.LISTENING_AUTO_SEED,
                )
                if not result["skipped"]:
                    _logging.getLogger(__name__).info(
                        "[listening] startup seed: %s",
                        result,
                    )
                else:
                    _logging.getLogger(__name__).info(
                        "[listening] startup seed skipped (题库已有 %d 题)",
                        result["seeded_questions"],
                    )
            except Exception as _exc2:
                _logging.getLogger(__name__).warning(
                    "[listening] startup seed failed: %s", _exc2
                )

        if web_config.LISTENING_AUTO_SEED:
            t = threading.Thread(
                target=_seed_in_background,
                name="listening-seed",
                daemon=True,
            )
            t.start()
            app.state.listening_seed_thread = t
        else:
            _logging.getLogger(__name__).info(
                "[listening] startup seed disabled by config"
            )
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[listening] startup seed setup failed: %s", _exc
        )

    # v3.8 P3.1：启动期种子备考资源广场(同步,阻塞 ~0.5s;无 LLM)
    try:
        import logging as _logging
        from ielts_buddy.services.prep_resource_service import (
            seed_initial_prep_resources,
        )
        result = seed_initial_prep_resources(
            container=app.state.container,
        )
        _logging.getLogger(__name__).info(
            "[prep] startup seed: %s",
            result,
        )
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[prep] startup seed failed: %s", _exc,
        )

    # v3.8 P3.2：启动期种子 Reading 题库(后台线程,fire-and-forget)
    # 注意:后台线程引用了 app.state.container,必须在 lifespan finally 中 join,
    #   否则容器关闭后线程还在跑会导致 SQLite "closed database" 错误
    # 测试可通过 ``IELTS_BUDDY_READING_AUTO_SEED=0`` 关闭(避免 SQLite 抢锁)
    if (
        getattr(app.state, "reading_seed_thread", None) is None
        and os.environ.get("IELTS_BUDDY_READING_AUTO_SEED", "1").strip() != "0"
    ):
        try:
            import logging as _logging
            from ielts_buddy.services.reading_practice_service import (
                seed_initial_reading,
            )
            import threading

            def _seed_reading_in_background():
                try:
                    result = seed_initial_reading(
                        container=app.state.container,
                    )
                    _logging.getLogger(__name__).info(
                        "[reading] startup seed: %s",
                        result,
                    )
                except Exception as _exc2:
                    _logging.getLogger(__name__).warning(
                        "[reading] startup seed failed: %s", _exc2,
                    )

            t = threading.Thread(
                target=_seed_reading_in_background,
                name="reading-seed",
                daemon=True,
            )
            t.start()
            app.state.reading_seed_thread = t
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "[reading] startup seed setup failed: %s", _exc,
            )

    try:
        yield
    finally:
        # 先停同步
        worker = getattr(app.state, "sync_worker", None)
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                pass
            app.state.sync_worker = None
        # join reading 后台种子线程(避免容器关闭后线程仍在操作 SQLite)
        reading_thread = getattr(app.state, "reading_seed_thread", None)
        if reading_thread is not None:
            try:
                reading_thread.join(timeout=5.0)
            except Exception:
                pass
            app.state.reading_seed_thread = None
        # join listening 后台种子线程
        listening_thread = getattr(app.state, "listening_seed_thread", None)
        if listening_thread is not None:
            try:
                listening_thread.join(timeout=5.0)
            except Exception:
                pass
            app.state.listening_seed_thread = None
        # 关 web_user_repo
        repo = getattr(app.state, "web_user_repo", None)
        if repo is not None:
            try:
                repo.close()
            except Exception:
                pass
            app.state.web_user_repo = None
        # 关业务容器
        container = getattr(app.state, "container", None)
        if container is not None:
            try:
                container.close()
            except Exception:
                pass
            app.state.container = None


def _open_default_user_repo():
    """v3 web_user_repo：跟随当前 backend 切换。

    - 如果容器是 FallbackContainer 且当前模式 online → MySQLWebUserRepository
    - 如果是 FallbackContainer 但模式 fallback → SQLiteWebUserRepository（共用 conn）
    - 老代码兼容：直接是 SQLiteRepositoryContainer / MySQLRepositoryContainer
    """
    from ielts_buddy.web.auth.repository import (
        MySQLWebUserRepository, SQLiteWebUserRepository,
    )

    container = getattr(app.state, "container", None)
    if container is None:
        from pathlib import Path
        db_path = Path(web_config.get_web_db_path())
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return create_sqlite_web_user_repository(str(db_path))

    # FallbackContainer：看 current_mode 决定走哪个 web_user_repo 实现
    if hasattr(container, "current_mode") and hasattr(container, "online"):
        if container.current_mode == "online" and container.online is not None:
            return MySQLWebUserRepository(container.online._engine)
        # fallback 模式：复用 SQLite container 的 conn（与业务表同 db）
        sqlite_conn = getattr(container.offline, "_conn", None)
        if sqlite_conn is not None:
            return SQLiteWebUserRepository(sqlite_conn)

    # 直接是 MySQLRepositoryContainer（兼容老测试）
    if hasattr(container, "_engine"):
        return MySQLWebUserRepository(container._engine)
    if hasattr(container, "_conn"):
        return SQLiteWebUserRepository(container._conn)
    raise RuntimeError("无法根据 container 决定 web_user_repo 类型")


def create_app() -> FastAPI:
    """构造 FastAPI 实例。

    每次调用都返回新实例，方便测试用 override_dependency。
    """
    app = FastAPI(
        title="IELTS Buddy Web",
        version="0.1.0",
        description="IELTS 学习助手的 Web 入口（阶段 2：Dashboard + Stats）",
        lifespan=_lifespan,
    )

    # 挂载静态文件
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    # templates 单例（auth 路由也要用，注入到 app.state）
    templates = _build_templates()
    app.state.templates = templates

    # ---- 路由 ----

    @app.get("/healthz", response_class=JSONResponse)
    async def healthz() -> dict[str, Any]:
        """健康检查：服务名 + 版本 + DB backend 状态 + 同步状态。"""
        result: dict[str, Any] = {
            "status": "ok",
            "app": "ielts-buddy-web",
            "version": app.version,
            "prefer_mode": web_config.WEB_DB_MODE,
            # LLM 配置状态：key 没配 / 写成占位符时，运维一眼能看出来，
            # 不用去点"翻译"按钮试（那是 2026-11-04 文章翻译 401 的排查痛点）
            "llm": dict(web_config.LLM_STATUS),
        }

        container = getattr(app.state, "container", None)
        if container is not None and hasattr(container, "current_mode"):
            result["db_mode"] = container.current_mode
            result["mysql_reachable"] = container.mysql_reachable
            # 同步状态
            try:
                sqlite_conn = container.offline._conn
                cur = sqlite_conn.execute(
                    "SELECT last_pull_at, last_push_at, last_error, last_error_at "
                    "FROM sync_meta WHERE id=1"
                )
                row = cur.fetchone()
                if row:
                    result["sync"] = {
                        "last_pull_at": row[0],
                        "last_push_at": row[1],
                        "last_error": row[2],
                        "last_error_at": row[3],
                    }
                # pending_upload 计数
                cur = sqlite_conn.execute(
                    "SELECT COUNT(*) FROM personal_vocab "
                    "WHERE sync_status='pending_upload'"
                )
                result["pending_upload_personal_vocab"] = cur.fetchone()[0]
            except Exception as e:
                result["sync_meta_error"] = str(e)
        return result

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """首页：展示欢迎信息 + 登录/进入学习入口。"""
        # 检查用户是否已登录
        user = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                from ielts_buddy.web.auth.security import decode_token
                payload = decode_token(token)
                if payload:
                    # 复用 app.state.web_user_repo（不再 instantiate Protocol —— 那会抛 TypeError）
                    repo = getattr(request.app.state, "web_user_repo", None)
                    if repo is not None:
                        user = repo.get_by_id(payload.get("sub"))
            except Exception:
                pass
        return templates.TemplateResponse(
            request,
            "pages/index.html",
            {
                "title": "IELTS Buddy",
                "phase": 2,
                "current_user": user,
                "request": request,
            },
        )

    # 阶段 1：auth 路由（HTML 模板 + JSON API）
    app.include_router(auth_routes.router)
    app.include_router(auth_routes.api_router)

    # 阶段 2：页面（dashboard / stats）+ stats API
    app.include_router(pages_routes.router)
    app.include_router(stats_routes.api_router)

    # 阶段 3：学习（随机 + 复习）+ 答题 API
    app.include_router(study_routes.router)

    # 阶段 2-3：词汇测验
    app.include_router(quiz_routes.router)
    app.include_router(quiz_routes.api_router)

    # 阶段 2：词库浏览
    app.include_router(browse_routes.router)
    app.include_router(browse_routes.api_router)
    app.include_router(lookup_routes.api_router)

    # 阶段 3：个人词库
    app.include_router(personal_routes.router)
    app.include_router(personal_routes.api_router)

    # 阶段 4：模拟考试
    app.include_router(exam_routes.router)
    app.include_router(exam_routes.api_router)

    # 阶段 4：AI 批改
    app.include_router(grade_routes.router)
    app.include_router(grade_routes.api_router)

    # 阶段 4：学习计划
    app.include_router(plan_routes.router)
    app.include_router(plan_routes.api_router)

    # 阶段 4：报告生成
    app.include_router(report_routes.router)
    app.include_router(report_routes.api_router)

    # 阶段 5：文章翻译 + 生词分析
    app.include_router(articles_routes.router)
    app.include_router(articles_routes.api_router)

    # 阶段 6：机考打字
    app.include_router(typing_routes.router)
    app.include_router(typing_routes.api_router)
    app.include_router(pomodoro_routes.router)
    app.include_router(pomodoro_routes.api_router)
    app.include_router(calendar_routes.router)
    app.include_router(calendar_routes.api_router)

    # 阶段 7：写作辅助 / 听力 / 口语（v3.6+：纯只读 CLI service 复用 web）
    app.include_router(write_routes.router)
    app.include_router(write_routes.api_router)
    app.include_router(listening_routes.router)
    app.include_router(listening_routes.api_router)
    app.include_router(speak_routes.router)
    app.include_router(speak_routes.api_router)

    # v3.6 错词本：按 wrong_count DESC 列出所有错词 + 5 个 web 答错入口自动入分类
    app.include_router(mistakes_routes.router)
    app.include_router(mistakes_routes.api_router)

    # v3.7 P1：口语对练（录音 + whisper 转写 + LLM 评分 + 错词回收）
    app.include_router(speaking_practice_routes.router)
    app.include_router(speaking_practice_routes.api_router)

    # v3.7 P2：真·听力题库（LLM 出题 + TTS 合成 + 单题模式）
    app.include_router(listening_practice_routes.router)
    app.include_router(listening_practice_routes.api_router)

    # v3.8 P3.1：备考资源广场(B 站 UP 主资源)
    app.include_router(prep_resources_routes.router)
    app.include_router(prep_resources_routes.api_router)

    # v3.8 P3.2：Reading 真题题库
    app.include_router(reading_practice_routes.router)
    app.include_router(reading_practice_routes.api_router)

    # v3.9 W11：语音训练工坊（页面 + API）
    app.include_router(voice_training_routes.router)
    app.include_router(voice_training_routes.api_router)

    # v3.9（2026-08-24）：微信小程序登录路由（/api/wx/* 前缀，与 Web /api/auth/* 物理隔离）
    # service 层复用 WebAuthService，零 schema 改动
    app.include_router(wechat_routes.router)

    # v3.9（2026-08-24）：微信小程序学习路由（/api/wx/study/* 前缀）
    # service 层复用 ReviewService + VocabService，零 schema 改动
    app.include_router(wx_study_routes.router)

    # v3.9（2026-08-24）：微信小程序口语对练路由（/api/wx/speak/practice/* 前缀）
    # service 层复用 SpeakingPracticeService
    app.include_router(wx_speak_routes.router)

    # v3.9（2026-08-24）：微信小程序写作批改路由（/api/wx/grade/* 前缀）
    # service 层复用 GradingService（导入 Web 端 _call_llm_grader）
    app.include_router(wx_grade_routes.router)

    return app


# 模块级 app 供 `uvicorn ielts_buddy.web.main:app` 使用
app = create_app()


# ---- CLI 入口：python -m ielts_buddy.web.main ----

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ielts-buddy-web",
        description="IELTS Buddy Web 入口",
    )
    parser.add_argument(
        "--host",
        default=web_config.WEB_HOST,
        help=f"绑定地址（默认 {web_config.WEB_HOST}）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=web_config.WEB_PORT,
        help=f"端口（默认 {web_config.WEB_PORT}）",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式：代码变更自动重启",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        import uvicorn
    except ImportError as e:
        raise SystemExit(
            "未安装 uvicorn。请执行：pip install 'uvicorn[standard]'\n"
            "或安装全部 Web 依赖：pip install -e '.[web]'"
        ) from e

    uvicorn.run(
        "ielts_buddy.web.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
