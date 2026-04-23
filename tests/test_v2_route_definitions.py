from pathlib import Path


def test_v2_search_routes_and_history_route_exist_and_old_routes_are_deprecated():
    text = Path("csrcqsf/services/parts.py").read_text(encoding="utf-8")

    assert "@parts_router.post('/v2/search/history/list'" in text
    assert "@parts_router.delete('/v2/index/{item_id}'" in text
    assert "@parts_router.post('/item_image_indexed'" in text
    assert "@parts_router.post('/update_item_features'" in text
    assert "deprecated=True" in text
