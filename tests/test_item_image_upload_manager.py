import asyncio
import io
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _fake_v1_milvus_module():
    return SimpleNamespace(
        MilvusManager=lambda: MagicMock(),
        ImageIndex=object,
        PartsIndex=object,
        FeaturesIndex=object,
        ColletionEnum=object,
    )


def _fake_minio_module():
    fake_client = SimpleNamespace(
        put_object=MagicMock(),
        remove_object=MagicMock(),
    )

    def _parse_minio_path(path: str, default_bucket: str | None = None):
        bucket, object_name = path.split("/", 1)
        return bucket, object_name

    return SimpleNamespace(
        minio_instance=SimpleNamespace(client=fake_client),
        ensure_minio_bucket=MagicMock(),
        parse_minio_path=_parse_minio_path,
    )


def _import_railway_parts_manager():
    cached = getattr(_import_railway_parts_manager, "_cached", None)
    if cached is not None:
        return cached

    existing = sys.modules.get("csrcqsf.modules.railway_parts.services.parts_service")
    if existing is not None:
        _import_railway_parts_manager._cached = existing
        return existing

    preserved_modules = {}
    with patch.dict(
        sys.modules,
        {
            "csrcqsf.data.milvus": SimpleNamespace(milvus_client=MagicMock()),
            "csrcqsf.data.mdpdb": SimpleNamespace(sgo_sessionLocal=MagicMock()),
            "csrcqsf.data.minio": _fake_minio_module(),
            "csrcqsf.biz.railwayparts.milvus": _fake_v1_milvus_module(),
            "csrcqsf.modules.railway_parts.vector_search.storage.milvus_manager": SimpleNamespace(MilvusManagerV2=lambda *args, **kwargs: MagicMock()),
            "csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager": SimpleNamespace(MilvusStateManagerV2=MagicMock()),
            "cv2": MagicMock(),
        },
    ):
        import csrcqsf.modules.railway_parts.services.parts_service as parts_module
        preserved_modules = {
            "csrcqsf.modules.railway_parts.services.parts_service": parts_module,
            "csrcqsf.models.item": sys.modules.get("csrcqsf.models.item"),
            "csrcqsf.models.sgo": sys.modules.get("csrcqsf.models.sgo"),
            "csrcqsf.models.search_history": sys.modules.get("csrcqsf.models.search_history"),
        }

    for module_name, module in preserved_modules.items():
        if module is not None:
            sys.modules[module_name] = module

    _import_railway_parts_manager._cached = parts_module
    return parts_module


def _fake_upload_file(filename: str, content_type: str = "image/jpeg", body: bytes = b"img"):
    return SimpleNamespace(
        filename=filename,
        content_type=content_type,
        file=io.BytesIO(body),
        close=AsyncMock(),
    )


def test_create_item_image_files_uploads_to_minio_and_creates_pg_records():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_item = SimpleNamespace(id=101)
    fake_files = [_fake_upload_file("a.jpg"), _fake_upload_file("b.jpg")]

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "create_item_images", AsyncMock()) as create_images_mock, \
         patch.object(parts_module.minio_instance.client, "put_object", MagicMock()), \
         patch.object(parts_module, "run_sync", AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))), \
         patch.object(parts_module, "ensure_minio_bucket", MagicMock()):
        res = asyncio.run(parts_module.RailwayPartsManager.create_item_image_files(101, fake_files))

    assert res["item_id"] == 101
    assert res["uploaded_count"] == 2
    assert len(res["records"]) == 2
    create_images_mock.assert_awaited()
    session.commit.assert_awaited()


def test_create_item_image_url_mode_still_deduplicates_existing_image_url():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_item = SimpleNamespace(id=101)
    existing = [SimpleNamespace(image_url="bfr-ai-files/manual/demo.jpg")]

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "list_item_images_by_item_id", AsyncMock(return_value=existing)), \
         patch.object(parts_module.SgoItemImages, "create_item_images", AsyncMock()) as create_images_mock:
        res = asyncio.run(
            parts_module.RailwayPartsManager.create_item_image(
                101,
                image_url_list=["bfr-ai-files/manual/demo.jpg", "bfr-ai-files/manual/demo-2.jpg"],
            )
        )

    assert res["uploaded_count"] == 1
    create_images_mock.assert_awaited()


def test_create_item_image_files_rolls_back_minio_when_pg_write_fails():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_item = SimpleNamespace(id=101)
    fake_file = _fake_upload_file("a.jpg")

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "get_item_by_id", AsyncMock(return_value=fake_item)), \
         patch.object(parts_module.SgoItemImages, "create_item_images", AsyncMock(side_effect=RuntimeError("pg failed"))), \
         patch.object(parts_module.minio_instance.client, "put_object", MagicMock()), \
         patch.object(parts_module, "run_sync", AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))), \
         patch.object(parts_module, "ensure_minio_bucket", MagicMock()), \
         patch.object(parts_module.minio_instance.client, "remove_object", MagicMock()) as remove_mock:
        try:
            asyncio.run(parts_module.RailwayPartsManager.create_item_image_files(101, [fake_file]))
        except RuntimeError as exc:
            assert "pg failed" in str(exc)
        else:
            raise AssertionError("PG failure should bubble up")

    session.rollback.assert_awaited()
    remove_mock.assert_called_once()
