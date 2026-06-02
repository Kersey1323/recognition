import asyncio
import io
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image


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
        _import_railway_parts_manager._cached = (
            existing.RailwayPartsManager,
            existing,
        )
        return _import_railway_parts_manager._cached

    preserved_modules = {}
    with patch.dict(
        sys.modules,
        {
            "csrcqsf.infra.vector_store.milvus": SimpleNamespace(milvus_client=MagicMock()),
            "csrcqsf.infra.db.mdp_db": SimpleNamespace(sgo_sessionLocal=MagicMock()),
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

    _import_railway_parts_manager._cached = (
        parts_module.RailwayPartsManager,
        parts_module,
    )
    return _import_railway_parts_manager._cached


class FakeUploadFile:
    def __init__(self, name: str, color: str):
        self.filename = name
        image = Image.new("RGB", (8, 8), color)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        self._content = buf.getvalue()

    async def read(self):
        return self._content


def test_rrf_fusion_for_multi_query_images_prefers_candidates_supported_by_multiple_queries():
    RailwayPartsManager, _ = _import_railway_parts_manager()

    per_query_results = [
        [
            {
                "entity": {
                    "image_id": 101,
                    "item_id": 1,
                    "item_code": "4001",
                    "item_name": "A",
                    "image_url": "a1.jpg",
                },
                "distance": 0.99,
            },
            {
                "entity": {
                    "image_id": 102,
                    "item_id": 2,
                    "item_code": "4002",
                    "item_name": "B",
                    "image_url": "b1.jpg",
                },
                "distance": 0.95,
            },
        ],
        [
            {
                "entity": {
                    "image_id": 101,
                    "item_id": 1,
                    "item_code": "4001",
                    "item_name": "A",
                    "image_url": "a1.jpg",
                },
                "distance": 0.88,
            },
            {
                "entity": {
                    "image_id": 202,
                    "item_id": 3,
                    "item_code": "4003",
                    "item_name": "C",
                    "image_url": "c1.jpg",
                },
                "distance": 0.87,
            },
        ],
    ]

    fused = RailwayPartsManager._fuse_multi_image_search_results(per_query_results)

    assert fused[0]["entity"]["item_id"] == 1
    assert fused[0]["matched_query_indexes"] == [0, 1]
    assert fused[0]["best_similarity"] == 0.99


def test_aggregate_v2_search_items_preserves_matched_query_indexes():
    RailwayPartsManager, _ = _import_railway_parts_manager()

    search_items = [
        RailwayPartsManager._build_search_item_from_hit(
            hit={
                "entity": {
                    "item_id": 1,
                    "item_code": "4001",
                    "item_name": "A",
                    "image_url": "a1.jpg",
                },
                "distance": 0.99,
                "matched_query_indexes": [0, 1],
            }
        ),
        RailwayPartsManager._build_search_item_from_hit(
            hit={
                "entity": {
                    "item_id": 1,
                    "item_code": "4001",
                    "item_name": "A",
                    "image_url": "a2.jpg",
                },
                "distance": 0.92,
                "matched_query_indexes": [1],
            }
        ),
    ]

    aggregated = RailwayPartsManager._aggregate_v2_search_items(search_items)

    assert len(aggregated) == 1
    assert aggregated[0].matched_images[0].matched_query_indexes == [0, 1]


def test_search_v2_by_images_fuses_results_and_persists_single_history():
    RailwayPartsManager, parts_module = _import_railway_parts_manager()

    files = [FakeUploadFile("a.jpg", "white"), FakeUploadFile("b.jpg", "black")]
    fake_manager = MagicMock()
    fake_manager.search_by_image = AsyncMock(
        side_effect=[
            [
                {
                    "entity": {
                        "image_id": 101,
                        "item_id": 1,
                        "item_code": "4001",
                        "item_name": "A",
                        "image_url": "a1.jpg",
                    },
                    "distance": 0.99,
                },
                {
                    "entity": {
                        "image_id": 102,
                        "item_id": 2,
                        "item_code": "4002",
                        "item_name": "B",
                        "image_url": "b1.jpg",
                    },
                    "distance": 0.95,
                },
            ],
            [
                {
                    "entity": {
                        "image_id": 101,
                        "item_id": 1,
                        "item_code": "4001",
                        "item_name": "A",
                        "image_url": "a1.jpg",
                    },
                    "distance": 0.89,
                },
            ],
        ]
    )

    with patch.object(parts_module, "MilvusManagerV2", return_value=fake_manager), \
         patch.object(parts_module, "get_id", return_value=2048696242753638400), \
         patch.object(parts_module, "SessionLocal", return_value=_AsyncSessionContext(AsyncMock())), \
         patch.object(
             RailwayPartsManager,
             "_upload_v2_search_query_image",
             AsyncMock(side_effect=["q1.jpg", "q2.jpg"]),
         ), \
         patch.object(RailwayPartsManager, "_persist_v2_search_history", AsyncMock()) as persist_mock:
        result = asyncio.run(
            RailwayPartsManager.search_v2_by_images(
                files=files,
                top_k=10,
                search_mode="hybrid",
                search_equipment="web",
            )
        )

    assert result.history_id == "2048696242753638400"
    assert result.data[0].item_id == "1"
    assert result.data[0].matched_images[0].matched_query_indexes == [0, 1]
    persist_mock.assert_awaited_once()
    assert persist_mock.await_args.kwargs["query_images"] == ["q1.jpg", "q2.jpg"]
