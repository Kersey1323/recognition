import asyncio
from unittest.mock import patch

from fastapi import Response

from csrcqsf.modules.railway_parts.routes.asset_proxy_routes import download_bucket_asset


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
                u_token="ok",
            )
        )

    assert response.status_code == 200
    assert (
        response.headers["X-Accel-Redirect"]
        == "/recognition_oss/bfr-reconstruction-files/results/demo/point_cloud.ply"
    )
