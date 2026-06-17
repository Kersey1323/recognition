from csrcqsf.core.app import app


def test_all_business_routes_are_mounted_without_service_prefix():
    paths = {route.path for route in app.routes}

    assert "/openapi.json" in paths
    assert "/railway/parts/v2/search/history/list" in paths
    assert "/railway/parts/v2/reconstruct/video/upload/init" in paths
    assert "/bfr-3d-videos/{asset_path:path}" in paths
    assert "/sgo/sgo/parts/sync" in paths
    assert "/railway/docs/file" in paths
    assert "/images/ocr/front" in paths
    assert "/segment/simple" in paths
