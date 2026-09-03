from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AuthPrincipal:
    """SGO Token 校验后写入请求上下文的用户身份。"""

    user_id: str
    account: str
    username: str
    tenant_id: str
    token_expires_at: str | None = None
    validated_at: str | None = None
    provider_expiration_seconds: int | None = None

    def to_cache_dict(self) -> dict[str, str | int | None]:
        return asdict(self)

    @classmethod
    def from_cache_dict(cls, data: dict) -> "AuthPrincipal":
        return cls(
            user_id=str(data.get("user_id") or ""),
            account=str(data.get("account") or ""),
            username=str(data.get("username") or ""),
            tenant_id=str(data.get("tenant_id") or ""),
            token_expires_at=data.get("token_expires_at"),
            validated_at=data.get("validated_at"),
            provider_expiration_seconds=data.get("provider_expiration_seconds"),
        )
