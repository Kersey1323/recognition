from pathlib import Path


def test_reconstruction_routes_use_post_list_endpoints():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "@parts_router.post('/v2/reconstruct/video/list'" in text
    assert "@parts_router.post('/v2/reconstruct/tasks/list'" in text
    assert "@parts_router.get('/v2/reconstruct/video'," not in text
    assert "@parts_router.get('/v2/reconstruct/tasks'," not in text
