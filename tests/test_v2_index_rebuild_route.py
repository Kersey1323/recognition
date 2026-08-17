import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

from csrcqsf.modules.railway_parts.schemas import reconstruction as real_reconstruction_api_models  # noqa: F401


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
        subset.get_v2_index_rebuild_status = module.get_v2_index_rebuild_status
        return subset


def test_v2_index_rebuild_route_accepts_rebuild_existing_flag():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/search_routes.py"
    ).read_text(encoding="utf-8")

    assert "async def rebuild_v2_index(" in text
    assert "rebuild_existing: bool = False" in text


def test_v2_index_rebuild_route_passes_rebuild_existing_to_managed_task():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/search_routes.py"
    ).read_text(encoding="utf-8")

    assert "rebuild_existing=rebuild_existing" in text
    assert "ReconstructionIndexRebuildRes(" in text


def test_v2_index_rebuild_route_has_one_managed_execution_path():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/search_routes.py"
    ).read_text(encoding="utf-8")

    assert "should_background" not in text
    assert "await RailwayPartsManager.rebuild_v2_index" not in text


def test_v2_index_rebuild_route_submits_single_item_without_awaiting_rebuild():
    parts_service = _import_parts_service()
    task_manager = MagicMock()
    task_manager.start.return_value = {
        "task_id": "index-task-single",
        "status": "pending",
    }

    with patch.dict(
        parts_service.rebuild_v2_index.__globals__,
        {"index_rebuild_task_manager": task_manager},
    ), patch.object(
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
            )
        )

    rebuild_mock.assert_not_awaited()
    task_manager.start.assert_called_once_with(
        runner=rebuild_mock,
        item_id=1979020557620613120,
        limit=None,
        rebuild_existing=True,
    )
    assert result.task_id == "index-task-single"
    assert result.status == "pending"


def test_v2_index_rebuild_route_submits_large_batch_without_awaiting_rebuild():
    parts_service = _import_parts_service()
    task_manager = MagicMock()
    task_manager.start.return_value = {
        "task_id": "index-task-1",
        "status": "pending",
    }

    with patch.dict(
        parts_service.rebuild_v2_index.__globals__,
        {"index_rebuild_task_manager": task_manager},
    ), patch.object(
        parts_service.RailwayPartsManager,
        "rebuild_v2_index",
        AsyncMock(
            return_value={
                "success_count": 0,
                "fail_count": 0,
                "total": 0,
                "processed_item_count": 0,
                "skipped_existing_count": 0,
            }
        ),
        create=True,
    ) as rebuild_mock:
        result = asyncio.run(
            parts_service.rebuild_v2_index(
                item_id=None,
                limit=500,
                rebuild_existing=False,
            )
        )

    rebuild_mock.assert_not_awaited()
    task_manager.start.assert_called_once()
    assert getattr(result, "task_id", None) == "index-task-1"
    assert getattr(result, "status", None) == "pending"


def test_v2_index_rebuild_status_route_returns_managed_task_snapshot():
    parts_service = _import_parts_service()
    status_route = getattr(parts_service, "get_v2_index_rebuild_status", None)

    assert callable(status_route)

    task_manager = MagicMock()
    task_manager.get.return_value = {
        "task_id": "index-task-1",
        "status": "running",
        "progress": 40,
        "total_items": 500,
        "processed_items": 200,
        "success_count": 790,
        "fail_count": 3,
        "segmented_count": 700,
        "fallback_count": 90,
        "current_item_id": "1595252389601431552",
        "estimated_remaining_seconds": 600,
        "estimated_remaining": "约10分钟",
        "error_message": None,
    }
    with patch.dict(
        status_route.__globals__,
        {"index_rebuild_task_manager": task_manager},
    ):
        result = asyncio.run(status_route("index-task-1"))

    assert result.task_id == "index-task-1"
    assert result.progress == 40
    assert result.estimated_remaining_seconds == 600
    assert result.segmented_count == 700
    assert result.fallback_count == 90
