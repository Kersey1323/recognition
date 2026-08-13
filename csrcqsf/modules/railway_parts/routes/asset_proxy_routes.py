"""Root-level asset proxy routes for bucket/object downloads."""

from __future__ import annotations

from fastapi import APIRouter, Header, Response
from fastapi.responses import JSONResponse

from csrcqsf.modules.railway_parts.services.assets_service import (
    AssetAuthError,
    build_asset_download_headers,
    should_skip_asset_proxy_auth,
)
from csrcqsf.modules.railway_parts.utils.assets import SUPPORTED_ASSET_BUCKETS


asset_proxy_router = APIRouter()


async def download_bucket_asset(
    bucket: str,
    asset_path: str,
    response: Response,
    u_token: str | None = Header(None, alias="U-Token"),
):
    try:
        headers = build_asset_download_headers(
            method="GET",
            path=f"/{bucket}/{asset_path}",
            u_token=u_token,
            skip_auth=should_skip_asset_proxy_auth(),
        )
    except AssetAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})
    for key, value in headers.items():
        response.headers[key] = value
    response.status_code = 200
    return response


def _register_bucket_download_route(bucket: str) -> None:
    async def endpoint(
        asset_path: str,
        response: Response,
        u_token: str | None = Header(None, alias="U-Token"),
    ):
        return await download_bucket_asset(
            bucket=bucket,
            asset_path=asset_path,
            response=response,
            u_token=u_token,
        )

    endpoint.__name__ = f"download_asset_{bucket.replace('-', '_')}"
    asset_proxy_router.add_api_route(
        f"/{bucket}/{{asset_path:path}}",
        endpoint,
        methods=["GET", "HEAD"],
        tags=["文件代理"],
        summary=f"文件下载代理入口: {bucket}",
    )


for _bucket in SUPPORTED_ASSET_BUCKETS:
    _register_bucket_download_route(_bucket)
