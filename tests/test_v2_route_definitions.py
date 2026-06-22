from pathlib import Path


def test_v2_search_routes_and_history_route_exist():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/search_routes.py"
    ).read_text(encoding="utf-8")

    assert "@parts_router.post('/v2/search/history/list'" in text
    assert "@parts_router.delete('/v2/index/{item_id}'" in text
    assert "@parts_router.post('/v2/search/image'" in text


def test_parts_routes_include_list_item_images_endpoint():
    parts_text = Path(
        "csrcqsf/modules/railway_parts/routes/parts_routes.py"
    ).read_text(encoding="utf-8")
    sgo_text = Path("csrcqsf/modules/sgo/routes.py").read_text(encoding="utf-8")

    assert "@parts_router.post('/list_item_images'" in parts_text
    assert "@sgo_router.post('/sgo/parts/images'" not in sgo_text


def test_parts_routes_include_delete_item_image_endpoint():
    parts_text = Path(
        "csrcqsf/modules/railway_parts/routes/parts_routes.py"
    ).read_text(encoding="utf-8")

    assert "@parts_router.post('/delete_item_image'" in parts_text
    assert "DeleteItemImageReq" in parts_text
    assert "DeleteItemImageRes" in parts_text
