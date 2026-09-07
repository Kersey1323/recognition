"""按 bucket/object 下载内部资产的根级代理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse

from csrcqsf.modules.railway_parts.services.assets_service import (
    AssetAuthError,
    build_asset_download_headers,
)
from csrcqsf.modules.railway_parts.utils.assets import SUPPORTED_ASSET_BUCKETS


asset_proxy_router = APIRouter()


async def download_bucket_asset(
    bucket: str,
    asset_path: str,
    response: Response,
):
    try:
        headers = build_asset_download_headers(
            method="GET",
            path=f"/{bucket}/{asset_path}",
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
        token: str | None = Query(
            default=None,
            description=(
                "文件代理兼容凭证。浏览器原生图片、视频或模型加载无法添加 "
                "Authorization 请求头时传入 SGO Token；普通业务接口不支持该参数。"
            ),
        ),
    ):
        return await download_bucket_asset(
            bucket=bucket,
            asset_path=asset_path,
            response=response,
        )

    endpoint.__name__ = f"download_asset_{bucket.replace('-', '_')}"
    for method in ("GET", "HEAD"):
        asset_proxy_router.add_api_route(
            f"/{bucket}/{{asset_path:path}}",
            endpoint,
            methods=[method],
            operation_id=(
                f"download_asset_{bucket.replace('-', '_')}_{method.lower()}"
            ),
            tags=["文件代理"],
            summary=f"文件下载代理入口: {bucket}",
        )


for _bucket in SUPPORTED_ASSET_BUCKETS:
    _register_bucket_download_route(_bucket)
