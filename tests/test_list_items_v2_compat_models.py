from csrcqsf.modules.railway_parts.schemas.parts import ListItem, ListItemReq
from csrcqsf.models.orm.item import Items


def dump_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", by_alias=True)
    return model.dict(by_alias=True)


def test_list_item_req_accepts_has_source_video_flag():
    req = ListItemReq(page=1, pageSize=20, has_source_video=2)

    assert req.page == 1
    assert req.per_page == 20
    assert req.has_source_video == 2


def test_list_item_req_defaults_has_source_video_to_no_filter():
    req = ListItemReq(page=1, pageSize=20)

    assert req.has_source_video == 2


def test_items_normalize_source_video_filter_mode_uses_boolean_style_flags():
    assert Items.normalize_source_video_filter_mode(0) == "missing"
    assert Items.normalize_source_video_filter_mode(1) == "exists"
    assert Items.normalize_source_video_filter_mode(2) is None


def test_list_item_serializes_v2_status_fields():
    item = ListItem(
        item_name="橡胶套",
        ply_url=None,
        item_code="40000543491",
        height=None,
        length=None,
        width=None,
        weight=None,
        video_path="bfr-3d-videos/raw-videos/demo.mp4",
        created_at="2025-10-24 15:40:16",
        has_index=1,
        has_source_video=1,
        id="1979095297377554432",
    )

    data = dump_model(item)
    assert data["has_index"] == 1
    assert data["has_source_video"] == 1


def test_items_build_v2_index_updates_maps_bool_and_counts():
    values = Items.build_v2_index_updates(
        has_v2_index=True,
        v2_indexed_image_num=4,
        updated_at="2026-04-23 18:00:00",
    )

    assert values["has_v2_index"] == 1
    assert values["v2_indexed_image_num"] == 4
    assert "v2_index_updated_at" in values
