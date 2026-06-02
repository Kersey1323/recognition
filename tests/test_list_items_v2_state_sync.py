import asyncio
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
    return MagicMock(
        MilvusManager=lambda: MagicMock(),
        ImageIndex=object,
        PartsIndex=object,
        FeaturesIndex=object,
        ColletionEnum=object,
    )


def _fake_cv2_module():
    return SimpleNamespace(
        COLOR_BGR2RGB=1,
        IMREAD_COLOR=1,
        INTER_AREA=1,
        cvtColor=lambda image, _code: image,
        imdecode=lambda image, _code: image,
        resize=lambda image, _size, interpolation=None: image,
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
            "csrcqsf.infra.vector_store.milvus": MagicMock(milvus_client=MagicMock()),
            "csrcqsf.infra.db.mdp_db": MagicMock(sgo_sessionLocal=MagicMock()),
            "csrcqsf.modules.railway_parts.integrations.milvus_state_manager": _fake_v1_milvus_module(),
            "cv2": _fake_cv2_module(),
        },
    ):
        import csrcqsf.modules.railway_parts.services.parts_service as parts_module
        preserved_modules = {
            "csrcqsf.modules.railway_parts.services.parts_service": parts_module,
            "csrcqsf.models.orm.item": sys.modules.get("csrcqsf.models.orm.item"),
            "csrcqsf.models.orm.sgo": sys.modules.get("csrcqsf.models.orm.sgo"),
            "csrcqsf.models.orm.search_history": sys.modules.get("csrcqsf.models.orm.search_history"),
        }

    for module_name, module in preserved_modules.items():
        if module is not None:
            sys.modules[module_name] = module

    _import_railway_parts_manager._cached = parts_module
    return parts_module


def test_sync_all_v2_index_state_resets_and_bulk_updates_snapshot():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_snapshot = {
        101: {"has_v2_index": 1, "v2_indexed_image_num": 3},
        202: {"has_v2_index": 1, "v2_indexed_image_num": 1},
    }

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module, "MilvusStateManagerV2") as manager_cls, \
         patch.object(parts_module.Items, "reset_v2_index_state", AsyncMock()) as reset_mock, \
         patch.object(parts_module.Items, "bulk_update_v2_index_state", AsyncMock()) as bulk_mock:
        manager_cls.return_value.get_item_index_state_snapshot.return_value = fake_snapshot
        res = asyncio.run(parts_module.RailwayPartsManager.sync_all_v2_index_state())

    reset_mock.assert_awaited()
    bulk_mock.assert_awaited()
    session.commit.assert_awaited()
    assert res["indexed_item_count"] == 2


def test_sync_single_item_v2_index_state_clears_missing_item():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module, "MilvusStateManagerV2") as manager_cls, \
         patch.object(parts_module.Items, "update_v2_index_state", AsyncMock()) as update_mock:
        manager_cls.return_value.get_item_index_state_snapshot.return_value = {}
        asyncio.run(parts_module.RailwayPartsManager.sync_item_v2_index_state(303))

    update_mock.assert_awaited()
    session.commit.assert_awaited()


def test_sync_single_item_v2_index_state_uses_injected_state_manager_when_provided():
    parts_module = _import_railway_parts_manager()
    session = AsyncMock()
    fake_state_manager = MagicMock()
    fake_state_manager.get_item_index_state_snapshot.return_value = {
        303: {"has_v2_index": 1, "v2_indexed_image_num": 4}
    }

    with patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch.object(parts_module.Items, "update_v2_index_state", AsyncMock()) as update_mock:
        asyncio.run(
            parts_module.RailwayPartsManager.sync_item_v2_index_state(
                303, state_manager=fake_state_manager
            )
        )

    update_mock.assert_awaited()
    fake_state_manager.get_item_index_state_snapshot.assert_called_once_with()
    session.commit.assert_awaited()
