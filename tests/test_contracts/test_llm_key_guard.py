"""契约测试：LLM API key 占位符防御（2026-11-04 文章翻译 401 事故）。

覆盖三件事：
1. 占位符 key（``sk-cp-...`` / 9 字符）必须被识别为"疑似无效"
2. 正常 key 不被误判
3. 鉴权类异常（401）必须走可读提示分支，而不是把原始 JSON 塞进正文
"""
from __future__ import annotations

import importlib

import pytest


def _reload_config(monkeypatch, key: str):
    """用给定 key 重载 web.config，返回重载后的 config 模块。

    注意：config 在 prod 模式下要求 JWT_SECRET / ADMIN_RESET_TOKEN，
    这里先补齐，否则 reload 会直接 RuntimeError，测不到 key 校验逻辑。
    """
    monkeypatch.setenv("IELTS_BUDDY_LLM_API_KEY", key)
    monkeypatch.setenv("IELTS_BUDDY_ENV", "prod")
    monkeypatch.setenv("IELTS_BUDDY_JWT_SECRET", "test-secret-" + "x" * 32)
    monkeypatch.setenv("IELTS_BUDDY_ADMIN_RESET_TOKEN", "t" * 64)
    import ielts_buddy.web.config as config
    return importlib.reload(config)


class TestApiKeyValidation:
    """_validate_llm_api_key：识别占位符 / 被截断的 key。"""

    def test_placeholder_with_ellipsis_is_suspect(self, monkeypatch):
        """生产事故的真实形态：sk-cp-...（9 字符 + 省略号）。"""
        cfg = _reload_config(monkeypatch, "sk-cp-...")
        assert cfg.LLM_STATUS["key_suspect"], "占位符 key 必须被标记为可疑"
        assert cfg.LLM_STATUS["configured"] is True
        assert cfg.LLM_STATUS["dry_run"] is False

    def test_short_key_is_suspect(self, monkeypatch):
        """短 key（<32 字符）不可用，必须告警。"""
        cfg = _reload_config(monkeypatch, "sk-short")
        assert cfg.LLM_STATUS["key_suspect"]
        assert "长度" in cfg.LLM_STATUS["key_suspect"]

    def test_real_key_is_not_suspect(self, monkeypatch):
        """125 字符的真实 key 不能被误判。"""
        real = "sk-cp-" + "a" * 121
        cfg = _reload_config(monkeypatch, real)
        assert cfg.LLM_STATUS["key_suspect"] == ""
        assert cfg.LLM_STATUS["key_length"] == len(real)
        assert cfg.LLM_STATUS["dry_run"] is False

    def test_empty_key_goes_dry_run(self, monkeypatch):
        """空 key -> dry-run 模式（不是"配置坏了"，是没配）。"""
        cfg = _reload_config(monkeypatch, "")
        assert cfg.LLM_STATUS["configured"] is False
        assert cfg.LLM_STATUS["dry_run"] is True
        assert cfg.LLM_STATUS["key_suspect"] == ""


class TestAuthErrorHint:
    """_is_auth_error：识别 MiniMax 的 401 鉴权失败。"""

    def test_detects_401(self):
        from ielts_buddy.web.llm_service import _is_auth_error
        exc = Exception("Error code: 401 - {'type': 'error', 'error': "
                        "{'type': 'authorized_error', 'message': 'login fail'}}")
        assert _is_auth_error(exc) is True

    def test_detects_login_fail(self):
        from ielts_buddy.web.llm_service import _is_auth_error
        assert _is_auth_error(
            Exception("login fail: Please carry the API secret key")
        ) is True

    def test_ignores_timeout(self):
        """超时不是鉴权问题，不要误报成"key 坏了"。"""
        from ielts_buddy.web.llm_service import _is_auth_error
        assert _is_auth_error(Exception("Request timed out")) is False

    def test_translation_uses_readable_hint(self, monkeypatch):
        """翻译遇 401 -> 正文是可操作提示，不是原始 JSON。"""
        import ielts_buddy.web.llm_service as llm_service

        svc = llm_service.LLMService(
            api_key="sk-test", base_url="https://example.invalid/v1",
            model="m", timeout=1.0, dry_run=False,
        )

        def _boom(*a, **kw):
            raise Exception("Error code: 401 - authorized_error login fail")

        monkeypatch.setattr(svc, "_llm_translate", _boom)
        result = svc.translate("Hello world, this is a test sentence.")
        assert result.source == "error"
        assert "鉴权失败" in result.translation
        assert "IELTS_BUDDY_LLM_API_KEY" in result.translation
        # 不该把 MiniMax 的原始报错细节裸露给用户
        assert "authorized_error" not in result.translation
        assert "Error code" not in result.translation

    def test_analyze_words_uses_readable_hint(self, monkeypatch):
        """生词分析遇 401 -> 同样给可读提示。"""
        import ielts_buddy.web.llm_service as llm_service

        svc = llm_service.LLMService(
            api_key="sk-test", base_url="https://example.invalid/v1",
            model="m", timeout=1.0, dry_run=False,
        )

        def _boom(*a, **kw):
            raise Exception("Error code: 401 - authorized_error")

        monkeypatch.setattr(svc, "_llm_analyze_words", _boom)
        analyses = svc.analyze_words(["confidence", "language"], "some context")
        assert len(analyses) == 2
        for a in analyses:
            assert a.source == "error"
            assert "鉴权失败" in a.context_meaning
