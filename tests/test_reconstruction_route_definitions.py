from pathlib import Path


def test_reconstruction_routes_use_post_list_endpoints():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "@parts_router.post('/v2/reconstruct/video/list'" in text
    assert "@parts_router.post('/v2/reconstruct/tasks/list'" in text
    assert "@parts_router.get('/v2/reconstruct/video'," not in text
    assert "@parts_router.get('/v2/reconstruct/tasks'," not in text


def test_reconstruction_routes_include_manual_result_upload():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "@parts_router.post('/v2/reconstruct/result/{item_id}'" in text
    assert "@parts_router.delete('/v2/reconstruct/result/{item_id}'" in text


def test_reconstruction_routes_include_statistics_endpoint():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "@parts_router.post('/v2/reconstruct/statistics'" in text


def test_reconstruction_routes_include_multipart_source_video_endpoints():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "@parts_router.post('/v2/reconstruct/video/upload/init'" in text
    assert "@parts_router.post('/v2/reconstruct/video/upload/local'" not in text
    assert "@parts_router.post('/v2/reconstruct/video/upload/part'" in text
    assert "@parts_router.post('/v2/reconstruct/video/upload/minio/health'" in text
    assert "@parts_router.post('/v2/reconstruct/video/upload/progress'" in text
    assert "@parts_router.post('/v2/reconstruct/video/upload/urls'" in text
    assert "@parts_router.post('/v2/reconstruct/video/upload/complete'" in text
    assert "@parts_router.post('/v2/reconstruct/video/upload/abort'" in text
    assert "@parts_router.post('/v2/reconstruct/video'" in text
