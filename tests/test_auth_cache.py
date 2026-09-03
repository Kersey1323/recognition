import asyncio
import json

from csrcqsf.core.auth.cache import RedisTokenCache
from csrcqsf.core.auth.models import AuthPrincipal


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.last_set = None

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex):
        self.values[key] = value
        self.last_set = (key, value, ex)


def test_cache_uses_sha256_key_and_never_stores_raw_token():
    redis = _FakeRedis()
    cache = RedisTokenCache("redis://unused", client=redis)
    principal = AuthPrincipal("1", "account", "用户", "tenant")

    asyncio.run(cache.set_valid("raw-secret-token", principal, ttl_seconds=120))

    key, value, ttl = redis.last_set
    assert key.startswith("recognition:auth:token:")
    assert "raw-secret-token" not in key
    assert "raw-secret-token" not in value
    assert ttl == 120
    assert json.loads(value)["state"] == "valid"


def test_cache_round_trips_valid_and_invalid_results():
    redis = _FakeRedis()
    cache = RedisTokenCache("redis://unused", client=redis)
    principal = AuthPrincipal("1", "account", "用户", "tenant")

    asyncio.run(cache.set_valid("valid", principal, ttl_seconds=60))
    valid = asyncio.run(cache.get("valid"))
    asyncio.run(
        cache.set_invalid("invalid", "AUTH_TOKEN_EXPIRED", ttl_seconds=10)
    )
    invalid = asyncio.run(cache.get("invalid"))

    assert valid.state == "valid"
    assert valid.principal == principal
    assert invalid.state == "invalid"
    assert invalid.error_code == "AUTH_TOKEN_EXPIRED"


def test_cache_failure_is_treated_as_miss():
    class _BrokenRedis:
        async def get(self, _key):
            raise ConnectionError("redis unavailable")

    cache = RedisTokenCache("redis://unused", client=_BrokenRedis())

    assert asyncio.run(cache.get("token")) is None
