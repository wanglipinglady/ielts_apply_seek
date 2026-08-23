"""Web 端认证子包（v3+：统一走 users 表，与 CLI 的 AuthService 共享 users 命名空间）。

模块划分：
- security    ：密码哈希 + JWT 签发/校验（无 IO 副作用，纯函数）
- schemas     ：Pydantic 请求/响应模型
- repository  ：Web 端用户仓储（Protocol + SQLite/MySQL 双实现，v3+ 读写 users 表）
- service     ：WebAuthService（注册/登录/刷新/me/登出/改密）
- deps        ：FastAPI 依赖注入（get_current_user 等）
- routes      ：/api/auth/* 与 /login、/register 模板路由
"""

from ielts_buddy.web.auth.repository import (
    WebUserRepository,
    SQLiteWebUserRepository,
    WebUser,
    WebUserNotFoundError,
    WebUserEmailConflictError,
    create_sqlite_web_user_repository,
)
from ielts_buddy.web.auth.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    InvalidTokenError,
    TokenExpiredError,
)
from ielts_buddy.web.auth.schemas import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
    AuthErrorResponse,
)
from ielts_buddy.web.auth.service import WebAuthService, AuthError
from ielts_buddy.web.auth.deps import (
    get_current_user,
    get_current_user_optional,
    get_web_auth_service,
)

__all__ = [
    "WebUser",
    "WebUserRepository",
    "SQLiteWebUserRepository",
    "WebUserNotFoundError",
    "WebUserEmailConflictError",
    "create_sqlite_web_user_repository",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "InvalidTokenError",
    "TokenExpiredError",
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "TokenResponse",
    "UserResponse",
    "AuthErrorResponse",
    "WebAuthService",
    "AuthError",
    "get_current_user",
    "get_current_user_optional",
    "get_web_auth_service",
]
