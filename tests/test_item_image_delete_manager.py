import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tests.test_item_image_upload_manager import _AsyncSessionContext, _import_railway_parts_manager


def test_delete_item_image_marks_db_and_cleans_external_resources():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_image = SimpleNamespace(
        id=202,
        item_id=101,
        image_url="bfr-ai-files/manual-upload/101/a.jpg",
        is_deleted=0,
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SgoItemImages, "get_item_image", AsyncMock(return_value=fake_image)), \
         patch.object(parts_module.SgoItemImages, "mark_deleted", AsyncMock()) as mark_deleted_mock, \
         patch("csrcqsf.modules.railway_parts.services.item_service._delete_minio_object", AsyncMock(return_value=None)) as minio_mock:
        state_manager = MagicMock()
        state_manager.delete_item_image_index.return_value = {
            "siglip_deleted": 1,
            "dinov2_deleted": 1,
            "total_deleted": 2,
        }
        with patch.object(parts_module, "_get_milvus_state_manager_v2_cls", return_value=lambda: state_manager):
            result = asyncio.run(
                parts_module.RailwayPartsManager.delete_item_image(
                    item_id=101,
                    image_id=202,
                    delete_reason="mistake",
                )
            )

    mark_deleted_mock.assert_awaited_once()
    minio_mock.assert_awaited_once()
    assert result["db_deleted"] is True
    assert result["minio_deleted"] is True
    assert result["milvus_deleted"] is True
    assert result["milvus_delete_count"] == 2


def test_delete_item_image_keeps_success_when_milvus_delete_fails():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_image = SimpleNamespace(
        id=202,
        item_id=101,
        image_url="bfr-ai-files/manual-upload/101/a.jpg",
        is_deleted=0,
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SgoItemImages, "get_item_image", AsyncMock(return_value=fake_image)), \
         patch.object(parts_module.SgoItemImages, "mark_deleted", AsyncMock()), \
         patch("csrcqsf.modules.railway_parts.services.item_service._delete_minio_object", AsyncMock(return_value=None)):
        state_manager = MagicMock()
        state_manager.delete_item_image_index.side_effect = RuntimeError("milvus down")
        with patch.object(parts_module, "_get_milvus_state_manager_v2_cls", return_value=lambda: state_manager):
            result = asyncio.run(
                parts_module.RailwayPartsManager.delete_item_image(
                    item_id=101,
                    image_id=202,
                    delete_reason=None,
                )
            )

    assert result["db_deleted"] is True
    assert result["minio_deleted"] is True
    assert result["milvus_deleted"] is False
    assert "重新同步索引" in result["message"]


def test_delete_item_image_returns_idempotent_success_when_already_deleted():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_image = SimpleNamespace(
        id=202,
        item_id=101,
        image_url="bfr-ai-files/manual-upload/101/a.jpg",
        is_deleted=1,
    )

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.SgoItemImages, "get_item_image", AsyncMock(return_value=fake_image)), \
         patch.object(parts_module.SgoItemImages, "mark_deleted", AsyncMock()) as mark_deleted_mock, \
         patch("csrcqsf.modules.railway_parts.services.item_service._delete_minio_object", AsyncMock(return_value=None)):
        state_manager = MagicMock()
        state_manager.delete_item_image_index.return_value = {
            "siglip_deleted": 0,
            "dinov2_deleted": 0,
            "total_deleted": 0,
        }
        with patch.object(parts_module, "_get_milvus_state_manager_v2_cls", return_value=lambda: state_manager):
            result = asyncio.run(
                parts_module.RailwayPartsManager.delete_item_image(
                    item_id=101,
                    image_id=202,
                    delete_reason=None,
                )
            )

    mark_deleted_mock.assert_not_awaited()
    assert result["db_deleted"] is True
