from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from csrcqsf.core.logging_config import logger

from .models import AuthPrincipal


@dataclass(frozen=True)
class CacheEntry:
    state: str
    principal: AuthPrincipal | None = None
    error_code: str | None = None


class RedisTokenCache:
    """仅以 Token SHA-256 摘要为键保存短期验证结果。"""

    def __init__(self, redis_url: str, *, client=None):
        self._redis_url = redis_url
        self._client = client
        if self._client is None and redis_url:
            from redis.asyncio import from_url

            self._client = from_url(redis_url, decode_responses=True)

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def key(cls, token: str) -> str:
        return f"recognition:auth:token:{cls.digest(token)}"

    async def get(self, token: str) -> CacheEntry | None:
        if self._client is None:
            return None
        digest = self.digest(token)
        try:
            raw_value = await self._client.get(f"recognition:auth:token:{digest}")
        except Exception as exc:
            logger.warning(
                "Token 验证缓存读取失败: digest_prefix={}, error_type={}",
                digest[:12],
                type(exc).__name__,
            )
            return None
        if not raw_value:
            return None
        try:
            payload = json.loads(raw_value)
            state = payload["state"]
            if state == "valid":
                return CacheEntry(
                    state="valid",
                    principal=AuthPrincipal.from_cache_dict(payload["principal"]),
                )
            if state == "invalid":
                return CacheEntry(
                    state="invalid",
                    error_code=str(payload.get("error_code") or "AUTH_TOKEN_INVALID"),
                )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Token 验证缓存内容无效: digest_prefix={}", digest[:12])
        return None

    async def set_valid(
        self,
        token: str,
        principal: AuthPrincipal,
        ttl_seconds: int,
    ) -> None:
        await self._set(
            token,
            {
                "state": "valid",
                "principal": principal.to_cache_dict(),
            },
            ttl_seconds,
        )

    async def set_invalid(
        self,
        token: str,
        error_code: str,
        ttl_seconds: int,
    ) -> None:
        await self._set(
            token,
            {"state": "invalid", "error_code": error_code},
            ttl_seconds,
        )

    async def _set(self, token: str, payload: dict, ttl_seconds: int) -> None:
        if self._client is None:
            return
        digest = self.digest(token)
        try:
            await self._client.set(
                f"recognition:auth:token:{digest}",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ex=max(1, int(ttl_seconds)),
            )
        except Exception as exc:
            # SGO 本次已验证成功时，缓存写失败不能反向阻断当前业务请求。
            logger.warning(
                "Token 验证缓存写入失败: digest_prefix={}, error_type={}",
                digest[:12],
                type(exc).__name__,
            )

    async def close(self) -> None:
        if self._client is not None and hasattr(self._client, "aclose"):
            await self._client.aclose()
