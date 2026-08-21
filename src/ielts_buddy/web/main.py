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
    """启动时：开业务仓库容器（学习记录/个人词库/题库等）+ web_user_repo；关闭时关。

    关键设计：**web_user_repo 与业务数据共用同一个存储引擎**，避免账号/数据分叉
    导致"重启丢失账号"或"账号存在但看不到业务数据"。

    - online (MySQL)：web_users 与 learning_records / personal_vocab / exam_results
      都在同一 MySQL 实例的同一 engine 下，事务一致。
    - sqlite：web_users 与业务表都在 ``~/.ielts-buddy/web_data.db`` 同一个文件下。
    """
    # 测试覆盖：如果 app.state.container 已被 conftest 注入，跳过
    if getattr(app.state, "container", None) is None:
        if web_config.WEB_DB_MODE == "online":
            # MySQL 模式：使用远程数据库永久存储
            from ielts_buddy.repositories.mysql_repo import (
                create_mysql_repositories,
            )
            container = create_mysql_repositories(
                connection_url=web_config.WEB_DB_URL or None
            )
            app.state.container = container
        else:
            # SQLite 模式：使用本地文件存储
            web_db = Path(web_config.get_web_db_path())
            # 父目录不存在则创建（生产部署通常是空挂载）
            web_db.parent.mkdir(parents=True, exist_ok=True)
            app.state.container = create_repositories(
                mode="local", db_path=web_db
            )

    # 关键：用业务容器同一份 engine 构造 web_user_repo，避免账号与数据分叉
    if getattr(app.state, "web_user_repo", None) is None:
        app.state.web_user_repo = _open_default_user_repo()

    try:
        yield
    finally:
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
    """web_user_repo：与业务数据共享同一存储连接。

    关键：无论 MySQL 还是 SQLite 模式，web_user_repo 都复用业务容器已
    创建好的连接（MySQL engine / SQLite conn），而不是再单独创建一份。

    带来的好处：
    1. web_users 与业务表在同一个物理实例/文件中，账号与数据一致。
    2. 重启服务不会丢失账号（之前测试脚本误删 db 才是真因）。
    3. 测试时 conftest 注入 container 后，本函数自动复用。

    注意：SQLite 模式下，业务容器已经打开了 ``web_data.db`` 的连接，
    并创建了业务表的 schema；这里再 ``executescript(_WEB_USERS_SCHEMA)``
    追加 web_users 表。两者共享同一 conn。
    """
    if web_config.WEB_DB_MODE == "online":
        # MySQL 模式：复用业务容器的 engine
        from ielts_buddy.web.auth.repository import MySQLWebUserRepository
        container = getattr(app.state, "container", None)
        if container is None:
            from ielts_buddy.repositories.mysql_repo import create_mysql_repositories
            container = create_mysql_repositories(
                connection_url=web_config.WEB_DB_URL or None
            )
            app.state.container = container
        return MySQLWebUserRepository(container._engine)
    else:
        # SQLite 模式：复用业务容器的 conn（不是再开一个）
        from ielts_buddy.web.auth.repository import SQLiteWebUserRepository
        from ielts_buddy.web.auth.repository import _SCHEMA as _WEB_USERS_SCHEMA
        container = getattr(app.state, "container", None)
        if container is not None and getattr(container, "_conn", None) is not None:
            # 共用业务 conn：web_users 表 schema 直接挂在业务库里
            return SQLiteWebUserRepository(container._conn)
        # 兜底：业务 container 未注入（如 conftest 走了别的路径）
        from pathlib import Path
        db_path = Path(web_config.get_web_db_path())
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return create_sqlite_web_user_repository(str(db_path))


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
                    from ielts_buddy.web.auth.repository import WebUserRepository
                    repo = WebUserRepository(db_path=web_config.WEB_DB_PATH)
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
