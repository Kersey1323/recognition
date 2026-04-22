from csrcqsf.biz.railwayparts.api_models import GetItemDetailRes, ListItem
from csrcqsf.models.item import Items


def test_list_item_supports_weight_field():
    item = ListItem(
        item_name="配件A",
        obj_url=None,
        item_code="A001",
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        created_at="2026-04-22 10:00:00",
        id="1935558010375340032",
    )

    assert item.weight == 40.0


def test_get_item_detail_supports_weight_field():
    detail = GetItemDetailRes(
        obj_url=None,
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        name="配件A",
        item_code="A001",
        id="1935558010375340032",
        created_at="2026-04-22 10:00:00",
        updated_at="2026-04-22 10:00:00",
        images=[],
        images_index_list=[],
        parent_item_name=None,
        parent_item_code=None,
        parent_item_id=None,
        size_str=None,
        features=[],
    )

    assert detail.weight == 40.0


def test_build_measurement_updates_only_includes_provided_fields():
    values = Items.build_measurement_updates(
        height=10.0,
        length=None,
        width=30.0,
        weight=None,
    )

    assert values == {
        "height": 10.0,
        "width": 30.0,
    }


def test_build_measurement_updates_maps_length_and_weight():
    values = Items.build_measurement_updates(
        height=None,
        length=20.0,
        width=None,
        weight=40.0,
    )

    assert values == {
        "long": 20.0,
        "weight": 40.0,
    }


def test_build_source_video_updates_maps_metadata_and_measurements():
    values = Items.build_source_video_updates(
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        filename="demo.mp4",
        size=1024,
        content_type="video/mp4",
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        updated_at="2026-04-22T10:00:00",
    )

    assert values == {
        "source_video_path": "bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        "source_video_filename": "demo.mp4",
        "source_video_size": 1024,
        "source_video_content_type": "video/mp4",
        "source_video_updated_at": "2026-04-22T10:00:00",
        "height": 10.0,
        "long": 20.0,
        "width": 30.0,
        "weight": 40.0,
    }


def test_build_source_video_updates_omits_unprovided_measurements():
    values = Items.build_source_video_updates(
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        filename="demo.mp4",
        size=1024,
        content_type="video/mp4",
        height=None,
        length=None,
        width=30.0,
        weight=None,
        updated_at="2026-04-22T10:00:00",
    )

    assert values == {
        "source_video_path": "bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        "source_video_filename": "demo.mp4",
        "source_video_size": 1024,
        "source_video_content_type": "video/mp4",
        "source_video_updated_at": "2026-04-22T10:00:00",
        "width": 30.0,
    }


def test_build_clear_source_video_values_clears_video_and_measurements():
    values = Items.build_clear_source_video_values()

    assert values == {
        "source_video_path": None,
        "source_video_filename": None,
        "source_video_size": None,
        "source_video_content_type": None,
        "source_video_updated_at": None,
        "height": None,
        "long": None,
        "width": None,
        "weight": None,
    }
