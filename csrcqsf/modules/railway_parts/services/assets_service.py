from __future__ import annotations

from dataclasses import dataclass
from csrcqsf.modules.railway_parts.utils.assets import (
    build_internal_accel_redirect,
    parse_public_asset_url,
)


@dataclass
class AssetAuthError(Exception):
    status_code: int
    message: str


def authorize_asset_request(
    *,
    method: str,
    path: str,
) -> dict:
    # 用户身份已由全局中间件校验，这里只约束文件读取方法和 MinIO 业务路径。
    normalized_method = str(method or "").upper()
    if normalized_method not in {"GET", "HEAD"}:
        raise AssetAuthError(403, "不允许的请求方法")

    parsed = parse_public_asset_url(path)
    if parsed is None:
        raise AssetAuthError(403, "不允许的资产路径")

    return {
        "bucket": parsed[0],
        "object_name": parsed[1],
    }


def build_asset_download_headers(
    *,
    method: str,
    path: str,
) -> dict[str, str]:
    result = authorize_asset_request(
        method=method,
        path=path,
    )
    return {
        "X-Accel-Redirect": build_internal_accel_redirect(
            result["bucket"], result["object_name"]
        ),
        "X-Asset-Bucket": result["bucket"],
        "X-Asset-Object": result["object_name"],
    }
