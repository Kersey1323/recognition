from __future__ import annotations

from dataclasses import dataclass
import os

from bfrcommon.basis_api.auth import UserClient

from csrcqsf.core.settings import basis_api_http_url
from csrcqsf.modules.railway_parts.utils.assets import (
    build_internal_accel_redirect,
    parse_public_asset_url,
)


@dataclass
class AssetAuthError(Exception):
    status_code: int
    message: str


def get_user_client() -> UserClient:
    if not basis_api_http_url:
        raise AssetAuthError(503, "未配置 BASIS_API_HTTP_URL")
    return UserClient(basis_api_http_url)


def authorize_asset_request(
    *,
    method: str,
    path: str,
    u_token: str | None,
    user_client: UserClient | None = None,
    skip_auth: bool = False,
) -> dict:
    normalized_method = str(method or "").upper()
    if normalized_method not in {"GET", "HEAD"}:
        raise AssetAuthError(403, "不允许的请求方法")

    parsed = parse_public_asset_url(path)
    if parsed is None:
        raise AssetAuthError(403, "不允许的资产路径")

    if skip_auth:
        return {
            "user_id": "local-debug",
            "bucket": parsed[0],
            "object_name": parsed[1],
        }

    token = str(u_token or "").strip()
    if token == "":
        raise AssetAuthError(401, "缺少 U-Token")

    client = user_client or get_user_client()
    data = client.check_token(token)
    if not isinstance(data, dict) or data.get("status") != "success":
        if isinstance(data, dict):
            message = data.get("message", "token 校验失败")
        else:
            message = "token 校验失败"
        raise AssetAuthError(401, message)

    return {
        "user_id": (data.get("data") or {}).get("id"),
        "bucket": parsed[0],
        "object_name": parsed[1],
    }


def build_asset_download_headers(
    *,
    method: str,
    path: str,
    u_token: str | None,
    user_client: UserClient | None = None,
    skip_auth: bool = False,
) -> dict[str, str]:
    result = authorize_asset_request(
        method=method,
        path=path,
        u_token=u_token,
        user_client=user_client,
        skip_auth=skip_auth,
    )
    return {
        "X-Accel-Redirect": build_internal_accel_redirect(
            result["bucket"], result["object_name"]
        ),
        "X-Asset-Bucket": result["bucket"],
        "X-Asset-Object": result["object_name"],
    }


def should_skip_asset_proxy_auth(header_value: str | None = None) -> bool:
    if str(header_value or "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    env_value = os.getenv("ASSET_PROXY_SKIP_AUTH", "")
    return env_value.strip().lower() in {"1", "true", "yes", "on"}
