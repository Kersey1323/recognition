from csrcqsf.biz.railwayparts.api_models import GetItemDetailRes, ListItem
from csrcqsf.models.item import Items

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def test_list_item_supports_weight_field():
    item = ListItem(
        item_name="配件A",
        ply_url=None,
        item_code="A001",
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        created_at="2026-04-22 10:00:00",
        id="1935558010375340032",
    )

    assert item.weight == 40.0


def test_list_item_supports_video_path_field():
    item = ListItem(
        item_name="配件A",
        ply_url=None,
        item_code="A001",
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        created_at="2026-04-22 10:00:00",
        id="1935558010375340032",
    )

    assert item.video_path == "bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4"


def test_list_item_uses_ply_url_field():
    item = ListItem(
        item_name="配件A",
        ply_url="bfr-reconstruction-files/results/1935558010375340032/task-id/point_cloud.ply",
        item_code="A001",
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        created_at="2026-04-22 10:00:00",
        id="1935558010375340032",
    )

    assert item.ply_url.endswith("point_cloud.ply")


def test_get_item_detail_supports_weight_field():
    detail = GetItemDetailRes(
        ply_url=None,
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
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


def test_get_item_detail_supports_video_path_field():
    detail = GetItemDetailRes(
        ply_url=None,
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
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

    assert detail.video_path == "bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4"


def test_get_item_detail_uses_ply_url_field():
    detail = GetItemDetailRes(
        ply_url="bfr-reconstruction-files/results/1935558010375340032/task-id/point_cloud.ply",
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
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

    assert detail.ply_url.endswith("point_cloud.ply")


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


def test_build_obj_url_update_sets_and_clears_current_result_url():
    assert Items.build_obj_url_update(
        "bfr-reconstruction-files/results/1935558010375340032/task-id/point_cloud.ply"
    ) == {
        "obj_url": "bfr-reconstruction-files/results/1935558010375340032/task-id/point_cloud.ply"
    }

    assert Items.build_obj_url_update(None) == {
        "obj_url": None
    }


def test_build_item_updates_keeps_zero_values_and_only_selected_fields():
    values = Items.build_item_updates(
        fields={"height", "length", "width", "weight"},
        height=0,
        length=0,
        width=0,
        weight=0,
    )

    assert values == {
        "height": 0,
        "long": 0,
        "width": 0,
        "weight": 0,
    }


def test_build_item_updates_ignores_unselected_fields():
    values = Items.build_item_updates(
        fields={"item_name"},
        item_name="橡胶套",
        item_code="A001",
        height=10,
    )

    assert values == {
        "item_name": "橡胶套",
    }


def _fake_v1_milvus_module():
    return SimpleNamespace(
        MilvusManager=lambda: MagicMock(),
        ImageIndex=object,
        PartsIndex=object,
        FeaturesIndex=object,
        ColletionEnum=object,
    )


def _fake_minio_module():
    def _parse_minio_path(path: str, default_bucket: str | None = None):
        bucket, object_name = path.split("/", 1)
        return bucket, object_name

    return SimpleNamespace(
        minio_instance=SimpleNamespace(client=SimpleNamespace()),
        ensure_minio_bucket=MagicMock(),
        parse_minio_path=_parse_minio_path,
    )


def _import_railway_parts_manager():
    cached = getattr(_import_railway_parts_manager, "_cached", None)
    if cached is not None:
        return cached

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.data.milvus": SimpleNamespace(milvus_client=MagicMock()),
            "csrcqsf.data.mdpdb": SimpleNamespace(sgo_sessionLocal=MagicMock()),
            "csrcqsf.data.minio": _fake_minio_module(),
            "csrcqsf.biz.railwayparts.milvus": _fake_v1_milvus_module(),
            "csrcqsf.biz.railwayparts.vector_db.storage.milvus_manager": SimpleNamespace(MilvusManagerV2=lambda *args, **kwargs: MagicMock()),
            "csrcqsf.biz.railwayparts.vector_db.storage.milvus_state_manager": SimpleNamespace(MilvusStateManagerV2=MagicMock()),
            "cv2": MagicMock(),
        },
    ):
        import csrcqsf.biz.railwayparts.parts as parts_module

    _import_railway_parts_manager._cached = parts_module
    return parts_module


def test_update_item_uses_partial_fields_and_skips_blank_parent():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_item = SimpleNamespace(id=101, item_code="A001")

    class _AsyncSessionContext:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.Items, "update_item_fields", AsyncMock()) as update_mock, \
         patch.object(parts_module.ItemsParent, "replace_parent_relations", AsyncMock()) as replace_parent_mock:
        asyncio.run(
            parts_module.RailwayPartsManager.update_item(
                item_id=101,
                update_fields={"height", "length", "width", "weight"},
                height=0,
                length=0,
                width=0,
                weight=0,
                parent_item_id=None,
            )
        )

    kwargs = update_mock.await_args.kwargs
    assert kwargs["values"] == {"height": 0, "long": 0, "width": 0, "weight": 0}
    replace_parent_mock.assert_not_awaited()
    session.commit.assert_awaited()


def test_create_item_defaults_parent_item_id_to_zero():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()

    class _AsyncSessionContext:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module, "get_id", return_value=2023080809420000001), \
         patch.object(parts_module.Items, "create_item", AsyncMock()) as create_mock, \
         patch.object(parts_module.ItemsParent, "replace_parent_relations", AsyncMock()) as replace_parent_mock:
        asyncio.run(
            parts_module.RailwayPartsManager.create_item(
                item_name="测试配件",
                item_code="A001",
                height=1,
                length=2,
                width=3,
                weight=4,
                parent_item_id=None,
            )
        )

    item = create_mock.await_args.kwargs["item"]
    assert item.parent_item_id == 0
    replace_parent_mock.assert_awaited_once_with(
        session=session,
        item_id=2023080809420000001,
        parent_item_id=0,
    )
    session.commit.assert_awaited()


def test_update_item_allows_top_level_parent_zero_and_clears_relation():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_item = SimpleNamespace(id=101, item_code="A001")

    class _AsyncSessionContext:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)) as get_item_mock, \
         patch.object(parts_module.Items, "update_item_fields", AsyncMock()) as update_mock, \
         patch.object(parts_module.ItemsParent, "replace_parent_relations", AsyncMock()) as replace_parent_mock:
        asyncio.run(
            parts_module.RailwayPartsManager.update_item(
                item_id=101,
                update_fields={"parent_item_id"},
                parent_item_id=0,
            )
        )

    get_item_mock.assert_awaited_once_with(session=session, item_id=101)
    assert update_mock.await_args.kwargs["values"] == {"parent_item_id": 0}
    replace_parent_mock.assert_awaited_once_with(
        session=session,
        item_id=101,
        parent_item_id=0,
    )
    session.commit.assert_awaited()


def test_update_item_updates_parent_relation_when_selected():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_item = SimpleNamespace(id=101, item_code="A001")
    fake_parent = SimpleNamespace(id=2023080809420000002)

    class _AsyncSessionContext:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(side_effect=[fake_item, fake_parent])), \
         patch.object(parts_module.Items, "update_item_fields", AsyncMock()) as update_mock, \
         patch.object(parts_module.ItemsParent, "replace_parent_relations", AsyncMock()) as replace_parent_mock:
        asyncio.run(
            parts_module.RailwayPartsManager.update_item(
                item_id=101,
                update_fields={"parent_item_id", "item_name"},
                item_name="橡胶套",
                parent_item_id=2023080809420000002,
            )
        )

    update_mock.assert_awaited_once()
    replace_parent_mock.assert_awaited_once_with(
        session=session,
        item_id=101,
        parent_item_id=2023080809420000002,
    )
