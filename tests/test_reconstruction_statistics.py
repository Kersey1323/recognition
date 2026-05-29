import asyncio
import importlib
import sys
from datetime import datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.reconstruction import ReconstructionStatus


def _clear_module(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_list_all_tasks_uses_completed_at_as_time_updated_for_terminal_tasks():
    from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager

    session = AsyncMock()
    records = [
        SimpleNamespace(
            task_id="done-task",
            item_id=2023080809420000001,
            task_type="video",
            status=ReconstructionStatus.SUCCESS,
            progress=100,
            current_stage="完成",
            scene_name="scene-a",
            error_message=None,
            ply_url="bfr-reconstruction-files/results/a/point_cloud.ply",
            glb_url=None,
            total_frames=None,
            filtered_frames=None,
            colmap_points=None,
            completed_at=datetime(2026, 4, 28, 16, 27, 53),
            elapsed_sec=493.4,
            time_created=datetime(2026, 4, 28, 16, 19, 27),
            time_updated=datetime(2026, 4, 28, 16, 40, 3),
        )
    ]

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_all_tasks", AsyncMock(return_value=(records, 1))):
        result = asyncio.run(ReconstructionManager.list_all_tasks(page=1, page_size=10))

    assert result["records"][0]["time_updated"] == "2026-04-28T16:27:53"


def test_list_all_tasks_backfills_item_name_from_items_table():
    from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager

    session = AsyncMock()
    records = [
        SimpleNamespace(
            task_id="done-task",
            item_id=2023080809420000001,
            task_type="video",
            status=ReconstructionStatus.SUCCESS,
            progress=100,
            current_stage="完成",
            scene_name="scene-a",
            error_message=None,
            ply_url="bfr-reconstruction-files/results/a/point_cloud.ply",
            glb_url=None,
            total_frames=None,
            filtered_frames=None,
            colmap_points=None,
            completed_at=datetime(2026, 4, 28, 16, 27, 53),
            elapsed_sec=493.4,
            time_created=datetime(2026, 4, 28, 16, 19, 27),
            time_updated=datetime(2026, 4, 28, 16, 40, 3),
        )
    ]

    async def fake_get_item_by_id_list(_session, item_id_list):
        assert item_id_list == [2023080809420000001]
        yield SimpleNamespace(id=2023080809420000001, item_name="螺栓M8X22")

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_all_tasks", AsyncMock(return_value=(records, 1))), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.get_item_by_id_list", fake_get_item_by_id_list):
        result = asyncio.run(ReconstructionManager.list_all_tasks(page=1, page_size=10))

    assert result["records"][0]["item_name"] == "螺栓M8X22"


def test_list_item_tasks_backfills_item_name_from_items_table():
    from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager

    session = AsyncMock()
    records = [
        SimpleNamespace(
            task_id="done-task",
            item_id=2023080809420000001,
            status=ReconstructionStatus.SUCCESS,
            progress=100,
            current_stage="完成",
            error_message=None,
            ply_url="bfr-reconstruction-files/results/a/point_cloud.ply",
            glb_url=None,
            total_frames=None,
            filtered_frames=None,
            colmap_points=None,
            completed_at=datetime(2026, 4, 28, 16, 27, 53),
            time_created=datetime(2026, 4, 28, 16, 19, 27),
            time_updated=datetime(2026, 4, 28, 16, 40, 3),
        )
    ]

    async def fake_get_item_by_id_list(_session, item_id_list):
        assert item_id_list == [2023080809420000001]
        yield SimpleNamespace(id=2023080809420000001, item_name="螺栓M8X22")

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_item_id", AsyncMock(return_value=records)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.get_item_by_id_list", fake_get_item_by_id_list):
        result = asyncio.run(ReconstructionManager.list_item_tasks(item_id=2023080809420000001))

    assert result[0]["item_name"] == "螺栓M8X22"


def test_list_item_tasks_does_not_refresh_status_from_celery_during_read():
    from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager

    session = AsyncMock()
    records = [
        SimpleNamespace(
            task_id="done-task",
            item_id=2023080809420000001,
            status=ReconstructionStatus.TRAINING,
            progress=50,
            current_stage="训练中",
            error_message=None,
            ply_url=None,
            glb_url=None,
            total_frames=None,
            filtered_frames=None,
            colmap_points=None,
            completed_at=None,
            time_created=datetime(2026, 4, 28, 16, 19, 27),
            time_updated=datetime(2026, 4, 28, 16, 40, 3),
        )
    ]

    async def fake_get_item_by_id_list(_session, item_id_list):
        yield SimpleNamespace(id=2023080809420000001, item_name="螺栓M8X22")

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_by_item_id", AsyncMock(return_value=records)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.get_item_by_id_list", fake_get_item_by_id_list):
        result = asyncio.run(ReconstructionManager.list_item_tasks(item_id=2023080809420000001))

    assert result[0]["status"] == ReconstructionStatus.TRAINING


def test_list_scenes_reads_from_remote_client():
    from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager

    fake_client = SimpleNamespace(
        list_scenes=AsyncMock(return_value={"scenes": ["scene-a", "scene-b"]})
    )

    with patch.object(ReconstructionManager, "_get_reconstruction_client", return_value=fake_client):
        scenes = asyncio.run(ReconstructionManager.list_scenes())

    assert scenes == ["scene-a", "scene-b"]


def test_reconstruction_statistics_maps_aggregate_counts_and_elapsed_metrics():
    from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager

    session = AsyncMock()
    fake_summary = {
        "total_tasks": 35,
        "running_tasks": 1,
        "success_tasks": 28,
        "failed_tasks": 5,
        "cancelled_tasks": 1,
        "avg_success_elapsed_sec": 486.2,
        "min_success_elapsed_sec": 301.4,
        "max_success_elapsed_sec": 921.7,
    }

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.summarize_tasks", AsyncMock(return_value=fake_summary)):
        result = asyncio.run(ReconstructionManager.statistics())

    assert result == {
        "total_tasks": 35,
        "running_tasks": 1,
        "success_tasks": 28,
        "failed_tasks": 5,
        "cancelled_tasks": 1,
        "success_rate": 28 / 33,
        "avg_success_elapsed_sec": 486.2,
        "min_success_elapsed_sec": 301.4,
        "max_success_elapsed_sec": 921.7,
    }


def test_list_all_tasks_does_not_refresh_status_from_celery_during_read():
    from csrcqsf.modules.railway_parts.services.reconstruction_service import ReconstructionManager

    session = AsyncMock()
    records = [
        SimpleNamespace(
            task_id="done-task",
            item_id=2023080809420000001,
            task_type="video",
            status=ReconstructionStatus.TRAINING,
            progress=50,
            current_stage="训练中",
            error_message=None,
            ply_url=None,
            glb_url=None,
            total_frames=None,
            filtered_frames=None,
            colmap_points=None,
            completed_at=None,
            elapsed_sec=None,
            time_created=datetime(2026, 4, 28, 16, 19, 27),
            time_updated=datetime(2026, 4, 28, 16, 40, 3),
        )
    ]

    async def fake_get_item_by_id_list(_session, item_id_list):
        yield SimpleNamespace(id=2023080809420000001, item_name="螺栓M8X22")

    with patch("csrcqsf.modules.railway_parts.services.reconstruction_service.SessionLocal", return_value=_AsyncSessionContext(session)), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.ReconstructionRecord.get_all_tasks", AsyncMock(return_value=(records, 1))), \
         patch("csrcqsf.modules.railway_parts.services.reconstruction_service.Items.get_item_by_id_list", fake_get_item_by_id_list):
        result = asyncio.run(ReconstructionManager.list_all_tasks(page=1, page_size=10))

    assert result["records"][0]["status"] == ReconstructionStatus.TRAINING


def test_reconstruction_statistics_route_returns_manager_payload():
    from csrcqsf.biz.railwayparts.reconstruction_api_models import ReconstructionStatisticsReq

    fake_parts_service_module = ModuleType("csrcqsf.modules.railway_parts.services.parts_service")
    fake_parts_service_module.RailwayPartsManager = type("RailwayPartsManager", (), {})
    fake_reconstruction_service_module = ModuleType("csrcqsf.modules.railway_parts.services.reconstruction_service")
    fake_reconstruction_service_module.ReconstructionManager = type("ReconstructionManager", (), {})
    fake_auto_processor_module = ModuleType("csrcqsf.biz.railwayparts.auto_processor")
    fake_auto_processor_module.AutoPartProcessor = type("AutoPartProcessor", (), {})
    fake_state_manager_module = ModuleType("csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager")
    fake_state_manager_module.MilvusStateManagerV2 = type("MilvusStateManagerV2", (), {})
    fake_sgo_module = ModuleType("csrcqsf.biz.sgo")
    fake_sgo_module.SGOBiz = type("SGOBiz", (), {"list_parts_sgo_image": staticmethod(lambda item_id: [])})

    payload = {
        "total_tasks": 35,
        "running_tasks": 1,
        "success_tasks": 28,
        "failed_tasks": 5,
        "cancelled_tasks": 1,
        "success_rate": 0.8485,
        "avg_success_elapsed_sec": 486.2,
        "min_success_elapsed_sec": 301.4,
        "max_success_elapsed_sec": 921.7,
    }

    with patch.dict(
        sys.modules,
        {
            "csrcqsf.modules.railway_parts.services.parts_service": fake_parts_service_module,
            "csrcqsf.modules.railway_parts.services.reconstruction_service": fake_reconstruction_service_module,
            "csrcqsf.biz.railwayparts.auto_processor": fake_auto_processor_module,
            "csrcqsf.modules.railway_parts.vector_search.storage.milvus_state_manager": fake_state_manager_module,
            "csrcqsf.biz.sgo": fake_sgo_module,
        },
    ):
        _clear_module("csrcqsf.modules.railway_parts.routes")
        _clear_module("csrcqsf.modules.railway_parts.services")
        parts_service = importlib.import_module("csrcqsf.modules.railway_parts.routes")

    with patch.object(parts_service.ReconstructionManager, "statistics", AsyncMock(return_value=payload)):
        result = asyncio.run(parts_service.reconstruct_v2_statistics(ReconstructionStatisticsReq()))

    assert result.total_tasks == 35
    assert result.success_rate == 0.8485
