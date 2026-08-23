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

    try:
        yield
    finally:
        # 停同步
        worker = getattr(app.state, "sync_worker", None)
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                pass
            app.state.sync_worker = None
        # web_user_repo 关
        repo = getattr(app.state, "web_user_repo", None)
        if repo is not None:
            try:
                repo.close()
            except Exception:
                pass
            app.state.web_user_repo = None
        # 业务容器关
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
