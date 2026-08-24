"""Web 端业务服务：注册 / 登录 / 刷新 / me / 登出。

注意：service 层不感知 FastAPI，方便单测。
"""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

from ielts_buddy.web.auth.repository import (
    WebUser,
    WebUserRepository,
    WebUserEmailConflictError,
    WebUserNotFoundError,
)
from ielts_buddy.web.auth.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)


# =============================================================
# 异常 / 错误码
# =============================================================


class AuthError(Exception):
    """认证业务异常：包含 code + 人类可读 message。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# =============================================================
# 登录结果
# =============================================================


@dataclass
class LoginResult:
    user: WebUser
    access_token: str
    refresh_token: str
    expires_in: int  # access token 剩余秒数
    is_new_user: bool = False  # v3.9+：微信登录专用，true = 这次登录新建了账号


# =============================================================
# Service
# =============================================================


class WebAuthService:
    """Web 端认证业务编排。

    接受 ``WebUserRepository`` 注入。Repository 是 Protocol，便于换 MySQL 实现。
    """

    def __init__(
        self,
        repo: WebUserRepository,
        *,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
    ) -> None:
        self._repo = repo
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    # ---- 注册 ----

    def register(self, email: str, password: str) -> LoginResult:
        """注册并自动登录（成功直接返回 token 集合，避免前端再来一次登录）。"""
        email_norm = email.strip().lower()
        if not email_norm:
            raise AuthError("INVALID_EMAIL", "邮箱不能为空")
        if len(password) < 8:
            raise AuthError("WEAK_PASSWORD", "密码至少 8 位")

        pw_hash = hash_password(password)
        try:
            user = self._repo.create(email_norm, pw_hash)
        except WebUserEmailConflictError as e:
            raise AuthError("EMAIL_TAKEN", str(e)) from e

        # 注册即登录：更新 last_login_at
        self._repo.update_last_login(user.id)

        return self._build_login_result(user)

    # ---- 登录 ----

    def login(self, email: str, password: str) -> LoginResult:
        """校验邮箱+密码，返回 token 集合。

        邮箱不存在 / 密码错误都返回同一个 ``INVALID_CREDENTIALS``，避免
        邮箱枚举攻击。
        """
        user = self._repo.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise AuthError("INVALID_CREDENTIALS", "邮箱或密码错误")

        self._repo.update_last_login(user.id)
        return self._build_login_result(user)

    # ---- 刷新 ----

    def refresh(self, refresh_token: str) -> LoginResult:
        """用 refresh token 换新 access + refresh。

        实现：解析 refresh token（已在路由层校验过合法性），用 sub 查 user，
        重新签发两把 token。
        """
        # 注意：调用方已经在路由层 decode_token 校验过 audience/expiry；
        # service 层只取 sub 查 user。
        from ielts_buddy.web.auth.security import (
            decode_token,
            AUDIENCE_REFRESH,
            InvalidTokenError,
        )

        try:
            payload = decode_token(refresh_token, expected_audience=AUDIENCE_REFRESH)
        except InvalidTokenError as e:
            raise AuthError("TOKEN_INVALID", str(e)) from e

        try:
            user_id = int(payload["sub"])
        except (KeyError, TypeError, ValueError) as e:
            raise AuthError("TOKEN_INVALID", "refresh token 缺少 sub") from e

        user = self._repo.get_by_id(user_id)
        if user is None:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

        return self._build_login_result(user)

    # ---- me ----

    def get_by_id(self, user_id: int) -> WebUser | None:
        """便捷：取当前用户。"""
        return self._repo.get_by_id(user_id)

    # ---- 微信小程序登录（v3.9+ / 2026-08-24 新增）----

    def login_by_wechat_openid(self, openid: str, nickname: str | None = None) -> LoginResult:
        """微信小程序登录核心方法：openid → 查/建用户 → 返回 token。

        流程：
        1. 按 openid 查现有用户（已绑定过的小程序用户）
        2. 查到 → 直接登录（is_new_user=False，更新 last_login_at）
        3. 查不到 → 自动创建账号（is_new_user=True，绑定 openid）
        4. 返回 token 集合 + is_new_user 标记

        参数：
        - openid: 微信小程序返回的 openid（**已由路由层调微信 API 校验**）
        - nickname: 用户昵称（可选，用于初始化 display_name）

        异常：
        - AuthError("INVALID_OPENID", ...): openid 为空
        """
        if not openid or not openid.strip():
            raise AuthError("INVALID_OPENID", "openid 不能为空")

        openid_clean = openid.strip()

        # 1. 按 openid 查现有用户
        user = self._repo.get_by_openid(openid_clean)
        if user is not None:
            # 已绑定 → 直接登录（is_new_user=False）
            self._repo.update_last_login(user.id)
            return self._build_login_result(user, is_new_user=False)

        # 2. 没绑定 → 自动创建新账号
        # username 用 `wx_<openid 前 12 位>` 派生（避免与邮箱注册冲突）
        username = f"wx_{openid_clean[:12]}"
        # email 用 placeholder（个人主体小程序无邮箱注册，用户也不会登录 Web）
        # 格式：`wx+<openid 短码>@wechat.ielts-buddy.local`，不与真实邮箱冲突
        email_placeholder = f"wx+{openid_clean[:12]}@wechat.ielts-buddy.local"

        # 老用户合并路径：如果 placeholder 邮箱已被占用（极小概率），覆盖该用户的 openid
        existing = self._repo.get_by_email(email_placeholder)
        if existing is not None:
            ok = self._repo.bind_wechat_openid(existing.id, openid_clean)
            if not ok:
                raise AuthError("BIND_FAILED", "openid 已被其他账号绑定")
            self._repo.update_last_login(existing.id)
            user = self._repo.get_by_id(existing.id)
            assert user is not None
            # 复用占位邮箱的账号 → 视为老用户
            return self._build_login_result(user, is_new_user=False)

        # 3. 创建新用户（密码 hash 用随机值占位，小程序账号不会走 Web 密码登录）
        pw_hash = hash_password(secrets.token_urlsafe(24))
        display_name = (nickname or "").strip() or f"微信用户{openid_clean[:6]}"
        try:
            new_user = self._create_wechat_user(
                username=username,
                email=email_placeholder,
                password_hash=pw_hash,
                display_name=display_name,
                openid=openid_clean,
            )
        except AuthError:
            raise
        except Exception as e:
            raise AuthError("WECHAT_LOGIN_FAILED", f"创建小程序用户失败: {e}") from e

        return self._build_login_result(new_user, is_new_user=True)

    def _create_wechat_user(
        self,
        *,
        username: str,
        email: str,
        password_hash: str,
        display_name: str,
        openid: str,
    ) -> WebUser:
        """为微信小程序用户创建账号并绑定 openid。

        子流程：先创建 → 再绑定（绑定失败时回滚用户）。
        之所以拆开两步：openid 唯一约束可能与现存老账号冲突，回滚比异常处理更稳。
        """
        try:
            user = self._repo.create(email, password_hash)
        except WebUserEmailConflictError as e:
            raise AuthError("EMAIL_TAKEN", str(e)) from e

        # 绑定 openid
        ok = self._repo.bind_wechat_openid(user.id, openid)
        if not ok:
            # openid 已被另一账号绑定（极小概率），返回错误由调用方决定如何处理
            raise AuthError("OPENID_CONFLICT", "openid 已被其他账号绑定")

        return self._repo.get_by_id(user.id) or user

    # ---- 改密 / 重置密码 ----

    def change_password(
        self, user_id: int, old_password: str, new_password: str,
    ) -> None:
        """用户自助改密：需要校验旧密码。

        Raises:
            AuthError("USER_NOT_FOUND", ...)    用户不存在
            AuthError("INVALID_CREDENTIALS", ...) 旧密码错
            AuthError("WEAK_PASSWORD", ...)     新密码太弱
        """
        if len(new_password) < 8:
            raise AuthError("WEAK_PASSWORD", "新密码至少 8 位")

        user = self._repo.get_by_id(user_id)
        if user is None:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

        if not verify_password(old_password, user.password_hash):
            # 故意不区分"用户不存在"与"密码错"——统一返回 INVALID_CREDENTIALS
            raise AuthError("INVALID_CREDENTIALS", "旧密码错误")

        new_hash = hash_password(new_password)
        ok = self._repo.set_password(user_id, new_hash)
        if not ok:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

    def reset_password(self, email: str) -> tuple[WebUser, str]:
        """管理员重置密码：按 email 找到用户，生成随机明文密码并写入 hash。

        返回 (user, new_plain_password)：
        - user：被重置的用户
        - new_plain_password：调用方**必须**立即展示给用户（一次性）

        Raises:
            AuthError("USER_NOT_FOUND", ...) 邮箱不存在
            AuthError("INVALID_EMAIL", ...)  邮箱格式错
        """
        email_norm = email.strip().lower()
        if not email_norm or "@" not in email_norm:
            raise AuthError("INVALID_EMAIL", "邮箱格式无效")

        user = self._repo.get_by_email(email_norm)
        if user is None:
            # 与登录保持一致：避免邮箱枚举攻击
            raise AuthError("INVALID_CREDENTIALS", "邮箱或密码错误")

        # 生成强随机明文密码（10 位：4 字母 + 2 数字 + 4 字母）
        new_plain = _generate_random_password(length=10)
        new_hash = hash_password(new_plain)
        ok = self._repo.set_password(user.id, new_hash)
        if not ok:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

        # 把 user 也回一份给调用方（用于响应里打印 email 等）
        return user, new_plain

    # 用户自助「忘记密码」默认密码（业务约定）
    DEFAULT_PASSWORD = "12345678"

    def reset_to_default_password(self, email: str) -> tuple[WebUser, str]:
        """用户自助「忘记密码」：把账号密码重置为固定默认密码 ``12345678``。

        设计目标：
        - 无需登录态；任何知道 email 的人都能触发
        - 默认密码固定为 ``12345678``（业务约定）
        - 一次性返回明文给前端展示，**前端必须明确提示用户改密**
        - 邮箱不存在时仍返回 INVALID_CREDENTIALS，避免邮箱枚举

        安全注意（已知缺陷，按用户要求接受）：
        - 任何能猜到 email 的攻击者都能重置该账号 → 不适合公网
        - 仅用于本地 dev / 单用户 / 受信环境
        - 生产应改为：邮件发验证码 → 用户输入 → 通过后再重置

        返回 (user, new_plain_password)：
        - user：被重置的用户
        - new_plain_password：固定为 ``12345678``

        Raises:
            AuthError("INVALID_CREDENTIALS", ...) 邮箱不存在（避免枚举）
            AuthError("INVALID_EMAIL", ...)  邮箱格式错
        """
        email_norm = email.strip().lower()
        if not email_norm or "@" not in email_norm:
            raise AuthError("INVALID_EMAIL", "邮箱格式无效")

        user = self._repo.get_by_email(email_norm)
        if user is None:
            raise AuthError("INVALID_CREDENTIALS", "邮箱或密码错误")

        new_plain = self.DEFAULT_PASSWORD
        new_hash = hash_password(new_plain)
        ok = self._repo.set_password(user.id, new_hash)
        if not ok:
            raise AuthError("USER_NOT_FOUND", "用户不存在")
        return user, new_plain

    # ---- 内部 ----

    def _build_login_result(self, user: WebUser, is_new_user: bool = False) -> LoginResult:
        access = create_access_token(
            user.id, user.email, ttl_seconds=self._access_ttl
        )
        refresh = create_refresh_token(user.id, ttl_seconds=self._refresh_ttl)
        return LoginResult(
            user=user,
            access_token=access,
            refresh_token=refresh,
            expires_in=self._access_ttl,
            is_new_user=is_new_user,
        )


__all__ = [
    "WebAuthService",
    "AuthError",
    "LoginResult",
    "_generate_random_password",
]


def _generate_random_password(length: int = 10) -> str:
    """生成易记但难猜的随机密码（字母 + 数字，至少 1 个数字）。

    算法：
    - 取小写字母 + 大写字母 + 数字 组成字符池
    - 保证至少 1 个数字（避免纯字母字典攻击）
    - 用 ``secrets.choice`` 保证密码学随机性
    - 最终密码会被 bcrypt 哈希（72 字节限制内），长度 10 完全够
    """
    if length < 8:
        raise ValueError("length 必须 ≥ 8")
    alphabet = string.ascii_letters + string.digits
    while True:
        # 至少 1 个数字
        chars = [secrets.choice(string.digits)]  # 保证 1 个数字
        chars += [secrets.choice(alphabet) for _ in range(length - 1)]
        secrets.SystemRandom().shuffle(chars)
        pwd = "".join(chars)
        # 二次保险：确保生成的密码看起来"够强"
        if any(c.isdigit() for c in pwd) and any(c.isalpha() for c in pwd):
            return pwd
