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
)
from ielts_buddy.web.routers import auth as auth_routes
from ielts_buddy.web.routers import pages as pages_routes
from ielts_buddy.web.routers import stats as stats_routes
from ielts_buddy.web.routers import study as study_routes

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


def _resolve_web_sqlite_path() -> str:
    """Web 端独立 SQLite 路径。

    优先级：
    1. 环境变量 ``IELTS_BUDDY_WEB_SQLITE_PATH``
    2. ``~/.ielts-buddy/web_data.db``（与 CLI 的 ``data.db`` 物理隔离）

    隔离理由：项目硬约束要求 Service / Repository 不动；当前 StatsService 等
    内部用直 SQL（依赖 sqlite3.Connection），没法跑 MySQL。Web 端用独立
    SQLite 文件既满足"多用户隔离"，又能让 Service 无修改复用。
    阶段 4 会把 Service 重构成走 Repository，届时再切 MySQL。
    """
    p = os.environ.get("IELTS_BUDDY_WEB_SQLITE_PATH", "").strip()
    if p:
        return p
    return str(Path("~/.ielts-buddy/web_data.db").expanduser())


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动时：开 web_user_repo + 业务仓库容器；关闭时：关。

    业务仓库容器在 Web 端固定走 SQLite（独立 db 文件），原因见
    ``_resolve_web_sqlite_path`` 注释。
    """
    # 测试覆盖：如果 app.state.web_user_repo 已被 conftest 注入，跳过
    if getattr(app.state, "web_user_repo", None) is None:
        app.state.web_user_repo = _open_default_user_repo()

    # 阶段 2：业务仓库容器（学习记录 / 个人词库 / 题库 等）
    if getattr(app.state, "container", None) is None:
        web_db = Path(_resolve_web_sqlite_path())
        # 父目录不存在则创建（生产部署通常是空挂载）
        web_db.parent.mkdir(parents=True, exist_ok=True)
        app.state.container = create_repositories(
            mode="local", db_path=web_db
        )
        # stats 直 SQL 用的连接：check_same_thread=False 跨 worker 安全
        import sqlite3
        app.state.web_stats_conn = sqlite3.connect(
            str(web_db), check_same_thread=False
        )
        app.state.web_stats_conn.row_factory = sqlite3.Row
    try:
        yield
    finally:
        # 业务容器关
        container = getattr(app.state, "container", None)
        if container is not None:
            try:
                container.close()
            except Exception:
                pass
            app.state.container = None
        # stats 连接关
        stats_conn = getattr(app.state, "web_stats_conn", None)
        if stats_conn is not None:
            try:
                stats_conn.close()
            except Exception:
                pass
            app.state.web_stats_conn = None
        # web_user_repo 关
        repo = getattr(app.state, "web_user_repo", None)
        if repo is not None:
            try:
                repo.close()
            except Exception:
                pass
            app.state.web_user_repo = None


def _open_default_user_repo():
    """web_user_repo：dev 走临时文件 SQLite（lifespan 与请求共享）"""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(prefix="ib_web_", suffix=".db", delete=False)
    tmp.close()
    return create_sqlite_web_user_repository(tmp.name)


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
        """健康检查：返回服务名与版本。"""
        return {
            "status": "ok",
            "app": "ielts-buddy-web",
            "version": app.version,
            "db_mode": web_config.WEB_DB_MODE,
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """阶段 0 占位首页。"""
        return templates.TemplateResponse(
            request,
            "pages/index.html",
            {
                "title": "IELTS Buddy Web",
                "phase": 2,
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
