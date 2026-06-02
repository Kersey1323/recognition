import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel

from csrcqsf.modules.railway_parts.schemas import reconstruction as real_reconstruction_api_models


def _clear_module(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


def _seed_routes_package() -> None:
    package = ModuleType("csrcqsf.modules.railway_parts.routes")
    package.__path__ = [str(Path("csrcqsf/modules/railway_parts/routes").resolve())]
    sys.modules["csrcqsf.modules.railway_parts.routes"] = package


def _import_parts_service():
    _clear_module("csrcqsf.modules.railway_parts.routes")
    _clear_module("csrcqsf.runtime")
    _seed_routes_package()
    fake_parts_service_module = ModuleType("csrcqsf.modules.railway_parts.services.parts_service")
    fake_parts_service_module.RailwayPartsManager = type("RailwayPartsManager", (), {})
    fake_state_manager_module = ModuleType("csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager")
    fake_state_manager_module.MilvusStateManagerV2 = type("MilvusStateManagerV2", (), {})
    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.parts_service": fake_parts_service_module,
            "csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager": fake_state_manager_module,
        },
    ):
        module = importlib.import_module("csrcqsf.modules.railway_parts.routes.search_routes")
        subset = ModuleType("test_index_rebuild_routes_subset")
        subset.RailwayPartsManager = module.RailwayPartsManager
        subset.rebuild_v2_index = module.rebuild_v2_index
        return subset


def test_v2_index_rebuild_route_accepts_rebuild_existing_flag():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/search_routes.py"
    ).read_text(encoding="utf-8")

    assert "async def rebuild_v2_index(" in text
    assert "rebuild_existing: bool = False" in text


def test_v2_index_rebuild_route_passes_rebuild_existing_to_background_and_sync_paths():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/search_routes.py"
    ).read_text(encoding="utf-8")

    assert "rebuild_existing=rebuild_existing" in text
    assert "ReconstructionIndexRebuildRes(" in text


def test_v2_index_rebuild_route_keeps_single_item_requests_sync():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/search_routes.py"
    ).read_text(encoding="utf-8")

    assert "should_background = int_item_id is None and (limit is None or limit > 100) and background_tasks is not None" in text
    assert "message=f'索引重建完成: 成功={result[\"success_count\"]}, 失败={result[\"fail_count\"]}'" in text


def test_v2_index_rebuild_route_returns_summary_for_single_item_requests():
    parts_service = _import_parts_service()
    background_tasks = MagicMock()

    with patch.object(
        parts_service.RailwayPartsManager,
        "rebuild_v2_index",
        AsyncMock(
            return_value={
                "success_count": 3,
                "fail_count": 0,
                "total": 3,
                "processed_item_count": 1,
                "skipped_existing_count": 0,
            }
        ),
        create=True,
    ) as rebuild_mock:
        result = asyncio.run(
            parts_service.rebuild_v2_index(
                item_id="1979020557620613120",
                limit=None,
                rebuild_existing=True,
                background_tasks=background_tasks,
            )
        )

    rebuild_mock.assert_awaited_once_with(
        item_id=1979020557620613120,
        limit=None,
        rebuild_existing=True,
    )
    background_tasks.add_task.assert_not_called()
    assert result.message == "索引重建完成: 成功=3, 失败=0"
    assert result.success_count == 3
    assert result.fail_count == 0
