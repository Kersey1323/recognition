from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hmac
import json
from typing import Protocol

import aiohttp

from .errors import AuthError
from .models import AuthPrincipal


class AuthProvider(Protocol):
    async def verify(self, token: str) -> AuthPrincipal: ...


def _positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class MockAuthProvider:
    """只用于开发联调的固定 Token Provider。"""

    def __init__(self, expected_token: str):
        self._expected_token = expected_token

    async def verify(self, token: str) -> AuthPrincipal:
        if not hmac.compare_digest(token, self._expected_token):
            raise AuthError(401, "AUTH_TOKEN_INVALID", "登录状态已失效，请重新登录")
        return AuthPrincipal(
            user_id="local-debug",
            account="local-debug",
            username="本地调试用户",
            tenant_id="local",
            validated_at=datetime.now(timezone.utc).isoformat(),
        )


class SgoAuthProvider:
    """调用甲方 SSO 接口验证客户端 Token 并解析用户身份。"""

    def __init__(
        self,
        *,
        auth_url: str,
        service: str,
        sso_mode: str,
        timeout_seconds: float,
        session_factory=None,
    ):
        self._auth_url = auth_url
        self._service = service
        self._sso_mode = sso_mode
        self._timeout_seconds = timeout_seconds
        self._session_factory = session_factory or aiohttp.ClientSession

    async def verify(self, token: str) -> AuthPrincipal:
        params = {"ticket": token, "code": token, "service": self._service}
        if self._sso_mode:
            params["ssoMode"] = self._sso_mode

        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        try:
            async with self._session_factory(timeout=timeout) as session:
                async with session.get(self._auth_url, params=params) as response:
                    status = response.status
                    raw_body = await response.text()
        except asyncio.TimeoutError as exc:
            raise AuthError(
                503,
                "AUTH_SERVICE_TIMEOUT",
                "登录验证服务响应超时，请稍后重试",
            ) from exc
        except aiohttp.ClientError as exc:
            raise AuthError(
                503,
                "AUTH_SERVICE_UNAVAILABLE",
                "登录验证服务暂时不可用，请稍后重试",
            ) from exc

        try:
            payload = json.loads(raw_body)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AuthError(
                503,
                "AUTH_SERVICE_UNAVAILABLE",
                "登录验证服务暂时不可用，请稍后重试",
            ) from exc

        if not isinstance(payload, dict):
            raise AuthError(
                503,
                "AUTH_SERVICE_UNAVAILABLE",
                "登录验证服务暂时不可用，请稍后重试",
            )

        if status == 200 and payload.get("loginStatus") is True:
            user_id = str(payload.get("userId") or "").strip()
            if not user_id:
                raise AuthError(
                    503,
                    "AUTH_SERVICE_UNAVAILABLE",
                    "登录验证服务暂时不可用，请稍后重试",
                )
            attrs = payload.get("userAttrs")
            attrs = attrs if isinstance(attrs, dict) else {}
            return AuthPrincipal(
                user_id=user_id,
                account=str(payload.get("account") or ""),
                username=str(payload.get("username") or ""),
                tenant_id=str(attrs.get("tenantId") or ""),
                validated_at=datetime.now(timezone.utc).isoformat(),
                provider_expiration_seconds=_positive_int(payload.get("expiration")),
            )

        if status == 200 and payload.get("loginStatus") is False:
            raise AuthError(401, "AUTH_TOKEN_INVALID", "登录状态已失效，请重新登录")

        if status == 500 and payload.get("state") is False:
            self._raise_sgo_failure(str(payload.get("message") or ""))

        raise AuthError(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "登录验证服务暂时不可用，请稍后重试",
        )

    @staticmethod
    def _raise_sgo_failure(message: str) -> None:
        normalized = message.lower()
        parameter_names = ("ticket", "code", "service")
        missing_markers = ("required", "missing", "不能为空", "缺少")
        if any(name in normalized for name in parameter_names) and any(
            marker in normalized for marker in missing_markers
        ):
            raise AuthError(
                500,
                "AUTH_INTERNAL_ERROR",
                "系统暂时无法完成登录验证，请稍后重试",
            )

        if "expired" in normalized or "过期" in normalized:
            raise AuthError(401, "AUTH_TOKEN_EXPIRED", "会话已过期，请重新登录")

        invalid_markers = (
            "token",
            "jwt",
            "signature",
            "invalid",
            "malformed",
            "illegal",
            "无效",
            "篡改",
            "解析",
        )
        if any(marker in normalized for marker in invalid_markers):
            raise AuthError(401, "AUTH_TOKEN_INVALID", "登录状态已失效，请重新登录")

        raise AuthError(
            503,
            "AUTH_SERVICE_UNAVAILABLE",
            "登录验证服务暂时不可用，请稍后重试",
        )
