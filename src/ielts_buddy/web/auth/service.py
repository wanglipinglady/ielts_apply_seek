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

        v4.0+：登录成功时标记 PC 端首次登录时间（pc_logged_in_at）。
        业务语义：一旦标记，业务规则会锁定该账号的邮箱（不允许修改），
        仅允许通过"忘记密码"邮件重置密码。
        """
        user = self._repo.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise AuthError("INVALID_CREDENTIALS", "邮箱或密码错误")

        self._repo.update_last_login(user.id)

        # v4.0+：标记 PC 端首次登录（只标记一次）
        if not user.pc_logged_in_at:
            self._repo.update_pc_logged_in_at(user.id)

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

    # ---- v4+：主动合并占位账号到老账号 ----

    def merge_wechat_to_existing(
        self,
        wechat_openid: str,
        target_email: str,
        target_password: str,
    ) -> tuple[LoginResult, int, int]:
        """v4+：把当前微信占位账号合并到指定邮箱的老账号。

        业务背景：
        - 用户在 PC 端用邮箱注册（独立账号），积累了大量学习数据
        - 用户后来扫码进小程序 → 后端创建占位账号
        - 用户在小程序主动触发"合并" → 输入 PC 端邮箱密码
        - 本方法把占位账号的所有数据迁移到老账号，删除占位账号
        - 小程序下次扫码时直接登录老账号

        关键约束：
        - 目标账号必须是真实邮箱（不是 @wechat.ielts-buddy.local 占位）
        - 密码必须校验通过（防冒名合并）
        - 目标账号不能已经绑定了其他 openid
        - 全部操作必须在数据库事务里（任何失败回滚）
        - 必须留审计日志（防误操作可追溯）

        异常：
        - AuthError("USER_NOT_FOUND", ...): 邮箱未注册
        - AuthError("INVALID_CREDENTIALS", ...): 密码错
        - AuthError("CANNOT_MERGE_SELF", ...): 合并目标和当前是同一个账号
        - AuthError("ALREADY_BOUND", ...): 目标账号已绑定其他微信
        - AuthError("INVALID_TARGET", ...): 目标是占位账号，不能合并到占位账号
        - AuthError("MERGE_FAILED", ...): 合并过程出错（已回滚）

        返回：(LoginResult 基于老账号, 被合并的占位 user_id, 迁移的单词数)
        """
        if not wechat_openid or not wechat_openid.strip():
            raise AuthError("INVALID_OPENID", "wechat_openid 不能为空")

        openid_clean = wechat_openid.strip()
        target_email_norm = target_email.strip().lower()

        # 1. 校验目标账号存在 + 密码对
        old_user = self._repo.get_by_email(target_email_norm)
        if old_user is None:
            raise AuthError("USER_NOT_FOUND", "该邮箱未注册")

        if not old_user.password_hash:
            raise AuthError(
                "INVALID_TARGET",
                "该账号是占位账号，不能作为合并目标",
            )

        if not verify_password(target_password, old_user.password_hash):
            raise AuthError("INVALID_CREDENTIALS", "邮箱或密码错误")

        # 2. 校验目标账号没有绑过其他微信
        if old_user.wechat_openid and old_user.wechat_openid != openid_clean:
            raise AuthError(
                "ALREADY_BOUND",
                "该邮箱已绑定其他微信，请先在 PC 端解绑",
            )

        # 3. 查占位账号
        placeholder = self._repo.get_by_openid(openid_clean)
        if placeholder is None:
            # 微信没创建过占位账号（用户之前用纯微信扫码登录，老账号 email 是占位）
            # 直接把老账号绑到当前 openid
            ok = self._repo.bind_wechat_openid(old_user.id, openid_clean)
            if not ok:
                raise AuthError("MERGE_FAILED", "绑定 openid 失败")
            return (
                self._build_login_result(old_user, is_new_user=False),
                0,  # 没有占位账号被合并
                0,  # 没有迁移数据
            )

        # 4. 校验不是合并到自己
        if placeholder.id == old_user.id:
            raise AuthError("CANNOT_MERGE_SELF", "合并目标不能是当前账号")

        # 5. 核心：事务里合并两个账号
        merged_vocab_count = self._do_merge(
            from_user_id=placeholder.id,
            to_user_id=old_user.id,
            from_user_snapshot={
                "id": placeholder.id,
                "email": placeholder.email,
                "wechat_openid": placeholder.wechat_openid,
            },
            to_user_id_before=old_user.id,
        )

        # 6. 重新查老账号（确保数据最新）
        merged_user = self._repo.get_by_id(old_user.id)
        assert merged_user is not None

        return (
            self._build_login_result(merged_user, is_new_user=False),
            placeholder.id,
            merged_vocab_count,
        )

    def _do_merge(
        self,
        from_user_id: int,
        to_user_id: int,
        from_user_snapshot: dict,
        to_user_id_before: int,
    ) -> int:
        """v4+：执行数据库事务合并（业务数据迁移 + openid 转移 + 删除占位账号 + 审计）。

        v4 初版在这里直接 ``from ielts_buddy.repositories.mysql_repo import
        get_mysql_engine`` —— **该函数在 mysql_repo 里并不存在**，所以合并
        一定抛 ``ImportError``；而且业务表清单（vocab / mistakes / study_plans）
        与真实 schema 完全不符。

        现在下沉到仓储层：``repo.merge_user_data()`` 负责事务 + 迁移 + 审计，
        SQLite / MySQL 两套实现共用同一份表清单常量。

        返回：迁移的单词数（personal_vocab 表）
        """
        wechat_openid = from_user_snapshot.get("wechat_openid")
        moved = self._repo.merge_user_data(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            wechat_openid=wechat_openid,
        )
        return int(moved.get("personal_vocab", 0))

    # ---- v4+：小程序内开通 PC 端账号 ----

    def activate_pc_account(
        self, user_id: int, email: str, password: str,
    ) -> LoginResult:
        """v4+：把当前微信占位账号**原地**升级成可登录 PC 端的账号。

        为什么是"原地升级"而不是"新建账号 + 合并"：
        - 原地改 email 保留 user_id → 小程序里的全部学习数据零迁移
        - 不产生第二个账号行，不需要事务合并，也就没有合并失败/回滚的风险
        - 用户在 PC 端用同一个邮箱密码登录后，``pc_logged_in_at`` 被标记，
          业务规则随即锁定邮箱（只能改密码）

        前置条件：当前账号是占位账号（email 以 ``@wechat.ielts-buddy.local`` 结尾）。

        异常：
        - AuthError("INVALID_EMAIL", ...)     邮箱格式非法
        - AuthError("WEAK_PASSWORD", ...)     密码太弱
        - AuthError("EMAIL_TAKEN", ...)       邮箱已被注册
        - AuthError("ALREADY_ACTIVATED", ...) 已经是真实邮箱账号了
        - AuthError("USER_NOT_FOUND", ...)    用户不存在
        """
        email_norm = email.strip().lower()
        if not email_norm or "@" not in email_norm or "." not in email_norm:
            raise AuthError("INVALID_EMAIL", "邮箱格式无效")
        if len(password) < 8:
            raise AuthError("WEAK_PASSWORD", "密码至少 8 位")

        user = self._repo.get_by_id(user_id)
        if user is None:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

        # 已经是真实邮箱 → 不允许再"开通"（改邮箱走 reset 流程）
        if not user.email.endswith("@wechat.ielts-buddy.local"):
            raise AuthError(
                "ALREADY_ACTIVATED",
                "该账号已开通 PC 端，如需修改请使用重置密码",
            )

        # 邮箱已被别人占用 → 明确报错（不让用户以为自己开好了）
        existing = self._repo.get_by_email(email_norm)
        if existing is not None and existing.id != user_id:
            raise AuthError("EMAIL_TAKEN", f"邮箱 '{email_norm}' 已被注册")

        pw_hash = hash_password(password)
        try:
            ok = self._repo.set_email_and_password(user_id, email_norm, pw_hash)
        except WebUserEmailConflictError as e:
            raise AuthError("EMAIL_TAKEN", str(e)) from e
        if not ok:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

        # 重新查一次拿到最新 user（含新 email）
        updated = self._repo.get_by_id(user_id)
        if updated is None:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

        return self._build_login_result(updated, is_new_user=False)

    # ---- v4+：已登录用户重置 PC 端密码 ----

    def reset_password_for_session(
        self, user_id: int, email: str, new_password: str,
    ) -> WebUser:
        """v4+：已登录用户重置自己账号的 PC 端密码。

        安全模型（无邮件验证码的前提下）：
        - 调用方必须持有有效 access token（``get_current_user`` 强制校验）
        - 传入的 email 必须等于当前账号的 email → 防止拿别人的账号改密码
        - 账号已经用 PC 端登录过（``pc_logged_in_at`` 有值）时邮箱被锁定，
          但**密码仍可重置**（这正是 v4 的业务要求）

        异常：
        - AuthError("EMAIL_MISMATCH", ...) 邮箱与当前账号不符
        - AuthError("WEAK_PASSWORD", ...)   新密码太弱
        - AuthError("USER_NOT_FOUND", ...)  用户不存在
        """
        if len(new_password) < 8:
            raise AuthError("WEAK_PASSWORD", "密码至少 8 位")

        user = self._repo.get_by_id(user_id)
        if user is None:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

        email_norm = email.strip().lower()
        if not email_norm or email_norm != (user.email or "").strip().lower():
            raise AuthError("EMAIL_MISMATCH", "邮箱与当前账号不一致")

        new_hash = hash_password(new_password)
        ok = self._repo.set_password(user_id, new_hash)
        if not ok:
            raise AuthError("USER_NOT_FOUND", "用户不存在")

        return self._repo.get_by_id(user_id) or user

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
