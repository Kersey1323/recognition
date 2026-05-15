from csrcqsf.app import app


def test_all_business_routes_are_mounted_under_recognition_api_prefix():
    paths = {route.path for route in app.routes}

    assert "/recognition_api/openapi.json" in paths
    assert "/recognition_api/railway/parts/v2/search/history/list" in paths
    assert "/recognition_api/railway/parts/v2/reconstruct/video/upload/init" in paths
    assert "/recognition_api/sgo/sgo/parts/sync" in paths
    assert "/recognition_api/railway/docs/file" in paths
    assert "/recognition_api/images/ocr/front" in paths
    assert "/recognition_api/segment/simple" in paths
