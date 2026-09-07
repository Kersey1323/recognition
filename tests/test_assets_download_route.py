import asyncio
from unittest.mock import patch

from fastapi import FastAPI, Response

from csrcqsf.modules.railway_parts.routes.asset_proxy_routes import (
    asset_proxy_router,
    download_bucket_asset,
)


def test_assets_download_route_returns_x_accel_redirect_header():
    with patch(
        "csrcqsf.modules.railway_parts.routes.asset_proxy_routes.build_asset_download_headers",
        return_value={
            "X-Accel-Redirect": "/recognition_oss/bfr-reconstruction-files/results/demo/point_cloud.ply"
        },
    ):
        response = asyncio.run(
            download_bucket_asset(
                bucket="bfr-reconstruction-files",
                asset_path="results/demo/point_cloud.ply",
                response=Response(),
            )
        )

    assert response.status_code == 200
    assert (
        response.headers["X-Accel-Redirect"]
        == "/recognition_oss/bfr-reconstruction-files/results/demo/point_cloud.ply"
    )


def test_assets_download_openapi_documents_query_token_fallback():
    app = FastAPI()
    app.include_router(asset_proxy_router)

    operation = app.openapi()["paths"]["/bfr-ai-files/{asset_path}"]["get"]
    token_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "token"
    )

    assert token_parameter["in"] == "query"
    assert token_parameter["required"] is False
    assert "文件代理" in token_parameter["description"]
