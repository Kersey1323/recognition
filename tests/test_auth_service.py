import asyncio
import base64
import json
import time

import pytest

from csrcqsf.core.auth.cache import CacheEntry
from csrcqsf.core.auth.errors import AuthError
from csrcqsf.core.auth.models import AuthPrincipal
from csrcqsf.core.auth.service import AuthService


class _Provider:
    def __init__(self, result=None, error=None):
        self.result = result or AuthPrincipal("1", "account", "用户", "tenant")
        self.error = error
        self.calls = 0

    async def verify(self, _token):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class _Cache:
    def __init__(self, entry=None):
        self.entry = entry
        self.valid_writes = []
        self.invalid_writes = []

    async def get(self, _token):
        return self.entry

    async def set_valid(self, token, principal, ttl_seconds):
        self.valid_writes.append((token, principal, ttl_seconds))

    async def set_invalid(self, token, error_code, ttl_seconds):
        self.invalid_writes.append((token, error_code, ttl_seconds))


def _jwt(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.unsigned"


def test_valid_cache_hit_does_not_call_provider():
    principal = AuthPrincipal("1", "account", "用户", "tenant")
    provider = _Provider()
    cache = _Cache(CacheEntry(state="valid", principal=principal))

    result = asyncio.run(AuthService(provider, cache, 300, 10).authenticate("token"))

    assert result == principal
    assert provider.calls == 0


def test_negative_cache_hit_returns_same_auth_failure():
    provider = _Provider()
    cache = _Cache(CacheEntry(state="invalid", error_code="AUTH_TOKEN_EXPIRED"))

    with pytest.raises(AuthError) as captured:
        asyncio.run(AuthService(provider, cache, 300, 10).authenticate("token"))

    assert captured.value.code == "AUTH_TOKEN_EXPIRED"
    assert provider.calls == 0


def test_explicitly_expired_jwt_is_rejected_without_sgo_call():
    provider = _Provider()

    with pytest.raises(AuthError) as captured:
        asyncio.run(
            AuthService(provider, _Cache(), 300, 10).authenticate(
                _jwt(int(time.time()) - 30)
            )
        )

    assert captured.value.code == "AUTH_TOKEN_EXPIRED"
    assert provider.calls == 0


def test_cache_ttl_is_limited_by_jwt_and_provider_expiration():
    provider = _Provider(
        AuthPrincipal(
            "1",
            "account",
            "用户",
            "tenant",
            provider_expiration_seconds=40,
        )
    )
    cache = _Cache()

    asyncio.run(
        AuthService(provider, cache, 300, 10).authenticate(
            _jwt(int(time.time()) + 120)
        )
    )

    assert cache.valid_writes[0][2] == 40


def test_provider_401_is_negative_cached():
    provider = _Provider(
        error=AuthError(401, "AUTH_TOKEN_INVALID", "SGO 登录已失效，请重新登录")
    )
    cache = _Cache()

    with pytest.raises(AuthError):
        asyncio.run(AuthService(provider, cache, 300, 10).authenticate("bad-token"))

    assert cache.invalid_writes == [("bad-token", "AUTH_TOKEN_INVALID", 10)]


def test_cache_miss_or_failure_never_bypasses_provider():
    provider = _Provider(
        error=AuthError(503, "AUTH_SERVICE_UNAVAILABLE", "SGO 认证服务暂时不可用")
    )

    with pytest.raises(AuthError) as captured:
        asyncio.run(AuthService(provider, _Cache(), 300, 10).authenticate("token"))

    assert provider.calls == 1
    assert captured.value.status_code == 503
