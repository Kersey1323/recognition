from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone
import json
import time

from .cache import RedisTokenCache
from .errors import AuthError
from .models import AuthPrincipal
from .providers import AuthProvider


class AuthService:
    """按本地过期检查、摘要缓存、SGO 回源的顺序完成身份认证。"""

    def __init__(
        self,
        provider: AuthProvider,
        cache: RedisTokenCache | None,
        token_cache_ttl_seconds: int,
        invalid_token_cache_ttl_seconds: int,
    ):
        self._provider = provider
        self._cache = cache
        self._token_cache_ttl_seconds = token_cache_ttl_seconds
        self._invalid_token_cache_ttl_seconds = invalid_token_cache_ttl_seconds

    async def authenticate(self, token: str) -> AuthPrincipal:
        jwt_exp = _read_unverified_jwt_exp(token)
        if jwt_exp is not None and jwt_exp <= time.time():
            await self._cache_invalid(token, "AUTH_TOKEN_EXPIRED")
            raise AuthError(401, "AUTH_TOKEN_EXPIRED", "会话已过期，请重新登录")

        cached = await self._cache.get(token) if self._cache is not None else None
        if cached is not None and cached.state == "valid" and cached.principal:
            return cached.principal
        if cached is not None and cached.state == "invalid":
            code = cached.error_code or "AUTH_TOKEN_INVALID"
            if code == "AUTH_TOKEN_EXPIRED":
                raise AuthError(401, code, "会话已过期，请重新登录")
            raise AuthError(401, code, "登录状态已失效，请重新登录")

        try:
            principal = await self._provider.verify(token)
        except AuthError as exc:
            if exc.status_code == 401:
                await self._cache_invalid(token, exc.code)
            raise

        now = time.time()
        ttl_candidates = [self._token_cache_ttl_seconds]
        if jwt_exp is not None:
            ttl_candidates.append(max(1, int(jwt_exp - now)))
        if principal.provider_expiration_seconds is not None:
            ttl_candidates.append(principal.provider_expiration_seconds)
        ttl_seconds = max(1, min(ttl_candidates))

        token_expires_at = principal.token_expires_at
        if jwt_exp is not None:
            token_expires_at = datetime.fromtimestamp(jwt_exp, timezone.utc).isoformat()
        principal = replace(
            principal,
            token_expires_at=token_expires_at,
            validated_at=principal.validated_at or datetime.now(timezone.utc).isoformat(),
        )
        if self._cache is not None:
            await self._cache.set_valid(token, principal, ttl_seconds)
        return principal

    async def _cache_invalid(self, token: str, error_code: str) -> None:
        if self._cache is not None:
            await self._cache.set_invalid(
                token,
                error_code,
                self._invalid_token_cache_ttl_seconds,
            )


def _read_unverified_jwt_exp(token: str) -> float | None:
    """只读取 JWT exp 用于提前拒绝；该结果不能证明 Token 真实有效。"""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        exp = float(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return exp
