import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException

from csrcqsf.modules.railway_parts.schemas import reconstruction as real_reconstruction_api_models  # noqa: F401
from csrcqsf.modules.railway_parts.services import index_rebuild_task_manager as real_index_task_manager  # noqa: F401


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


_PARTS_SERVICE = None


def _clear_module(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


def _seed_routes_package() -> None:
    package = ModuleType("csrcqsf.modules.railway_parts.routes")
    package.__path__ = [str(Path("csrcqsf/modules/railway_parts/routes").resolve())]
    sys.modules["csrcqsf.modules.railway_parts.routes"] = package


def _import_parts_service():
    global _PARTS_SERVICE
    if _PARTS_SERVICE is not None:
        return _PARTS_SERVICE

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
        subset.parts_router = module.parts_router
        subset.rebuild_v2_index = module.rebuild_v2_index
        subset.get_v2_index_rebuild_status = module.get_v2_index_rebuild_status
        subset.list_v2_index_rebuild_tasks = module.list_v2_index_rebuild_tasks
        subset.cancel_v2_index_rebuild_task = module.cancel_v2_index_rebuild_task
        subset.retry_v2_index_rebuild_task = module.retry_v2_index_rebuild_task
        subset.ReconstructionIndexTaskListReq = module.ReconstructionIndexTaskListReq
        subset.ReconstructionIndexTaskCancelReq = module.ReconstructionIndexTaskCancelReq
        _PARTS_SERVICE = subset
        return _PARTS_SERVICE


def _resolve_openapi_schema(schema: dict, schema_or_ref: dict) -> dict:
    schema_ref = schema_or_ref.get("$ref")
    if schema_ref is None:
        return schema_or_ref
    return schema["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]


def test_v2_index_rebuild_openapi_documents_frontend_task_contract():
    parts_service = _import_parts_service()
    app = FastAPI()
    app.include_router(parts_service.parts_router)
    schema = app.openapi()

    rebuild_operation = schema["paths"]["/railway/parts/v2/index/rebuild"]["post"]
    parameters = {
        parameter["name"]: parameter
        for parameter in rebuild_operation["parameters"]
    }
    assert "指定配件" in parameters["item_id"]["description"]
    assert "配件数量上限" in parameters["limit"]["description"]
    assert "未索引图片" in parameters["rebuild_existing"]["description"]
    assert "CREATEBYSELF" in rebuild_operation["description"]

    rebuild_response = _resolve_openapi_schema(
        schema,
        rebuild_operation["responses"]["200"]["content"]["application/json"]["schema"],
    )
    assert "task_id" in rebuild_response["properties"]
    assert "立即返回" in rebuild_response["properties"]["task_id"]["description"]

    status_operation = schema["paths"][
        "/railway/parts/v2/index/rebuild/status/{task_id}"
    ]["get"]
    status_response = _resolve_openapi_schema(
        schema,
        status_operation["responses"]["200"]["content"]["application/json"]["schema"],
    )
    status_properties = status_response["properties"]
    assert "pending" in status_properties["status"]["description"]
    assert "CREATEBYSELF" in status_properties["segmented_count"]["description"]
    assert "原图" in status_properties["fallback_count"]["description"]
    assert "item_code" in status_properties
    assert "current_item_code" in status_properties
    assert "last_completed_item_code" in status_properties
    assert "item_id" not in status_properties
    assert "current_item_id" not in status_properties
    assert "last_completed_item_id" not in status_properties

    list_operation = schema["paths"][
        "/railway/parts/v2/index/rebuild/tasks/list"
    ]["post"]
    list_description = list_operation["description"]
    assert "`active`" in list_description
    assert "等待中、运行中、取消中" in list_description
    assert "`single`" in list_description
    assert "最多并行 16 个" in list_description
    assert "`batch`" in list_description
    assert "不能与其他索引任务并行" in list_description
    list_body_ref = list_operation["requestBody"]["content"]["application/json"]["schema"]
    list_body = _resolve_openapi_schema(schema, list_body_ref)
    assert "等待、运行和取消中" in list_body["properties"]["status"]["description"]
    assert "单配件任务" in list_body["properties"]["task_scope"]["description"]
    assert list_body["example"] == {
        "page": 1,
        "pageSize": 20,
        "status": "active",
        "task_scope": "all",
    }

    cancel_operation = schema["paths"][
        "/railway/parts/v2/index/rebuild/tasks/{task_id}/cancel"
    ]["post"]
    cancel_body_ref = cancel_operation["requestBody"]["content"]["application/json"]["schema"]
    cancel_body = _resolve_openapi_schema(schema, cancel_body_ref)
    assert "前端展示" in cancel_body["properties"]["cancel_reason"]["description"]

    retry_operation = schema["paths"][
        "/railway/parts/v2/index/rebuild/tasks/{task_id}/retry"
    ]["post"]
    retry_response = _resolve_openapi_schema(
        schema,
        retry_operation["responses"]["200"]["content"]["application/json"]["schema"],
    )
    assert "task_id" in retry_response["properties"]


def test_v2_index_rebuild_route_accepts_rebuild_existing_flag():
    text = Path(
        "csrcqsf/modules/railway_parts/routes/search_routes.py"
    ).read_text(encoding="utf-8")

    assert "async def rebuild_v2_index(" in text
    assert "rebuild_existing: bool = Query(" in text


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
    task_manager.start = AsyncMock(return_value={
        "task_id": "index-task-single",
        "status": "pending",
    })

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
    task_manager.start.assert_awaited_once_with(
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
    task_manager.start = AsyncMock(return_value={
        "task_id": "index-task-1",
        "status": "pending",
    })

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
    task_manager.start.assert_awaited_once()
    assert getattr(result, "task_id", None) == "index-task-1"
    assert getattr(result, "status", None) == "pending"


def test_v2_index_rebuild_status_route_returns_managed_task_snapshot():
    parts_service = _import_parts_service()
    status_route = getattr(parts_service, "get_v2_index_rebuild_status", None)

    assert callable(status_route)

    task_manager = MagicMock()
    task_manager.get = AsyncMock(return_value={
        "task_id": "index-task-1",
        "item_id": "2096852949048233984",
        "status": "running",
        "progress": 40,
        "total_items": 500,
        "processed_items": 200,
        "success_count": 790,
        "fail_count": 3,
        "segmented_count": 700,
        "fallback_count": 90,
        "current_item_id": "1595252389601431552",
        "last_completed_item_id": "1595252389601431551",
        "estimated_remaining_seconds": 600,
        "estimated_remaining": "约10分钟",
        "error_message": None,
    })
    session = AsyncMock()
    code_rows = [
        (2096852949048233984, "4000205744"),
        (1595252389601431552, "4000205745"),
        (1595252389601431551, "4000205743"),
    ]
    with patch.dict(
        status_route.__globals__,
        {
            "index_rebuild_task_manager": task_manager,
            "SessionLocal": MagicMock(return_value=_AsyncSessionContext(session)),
        },
    ), patch.object(
        status_route.__globals__["Items"],
        "list_item_id_codes_by_ids",
        AsyncMock(return_value=code_rows),
    ) as codes_mock:
        result = asyncio.run(status_route("index-task-1"))

    assert result.task_id == "index-task-1"
    assert result.progress == 40
    assert result.estimated_remaining_seconds == 600
    assert result.segmented_count == 700
    assert result.fallback_count == 90
    assert result.item_code == "4000205744"
    assert result.current_item_code == "4000205745"
    assert result.last_completed_item_code == "4000205743"
    assert not hasattr(result, "item_id")
    codes_mock.assert_awaited_once()


def test_v2_index_rebuild_status_route_returns_404_for_missing_task():
    parts_service = _import_parts_service()
    task_manager = MagicMock()
    task_manager.get = AsyncMock(return_value=None)

    with patch.dict(
        parts_service.get_v2_index_rebuild_status.__globals__,
        {"index_rebuild_task_manager": task_manager},
    ), pytest.raises(HTTPException) as exc_info:
        asyncio.run(parts_service.get_v2_index_rebuild_status("missing-task"))

    assert exc_info.value.status_code == 404


def test_v2_index_rebuild_task_list_returns_persisted_records():
    parts_service = _import_parts_service()
    task_manager = MagicMock()
    task_manager.list = AsyncMock(return_value=(
        [
            {
                "task_id": "index-task-1",
                "status": "running",
                "progress": 40,
                "total_items": 10,
                "processed_items": 4,
                "completed_item_count": 4,
                "success_count": 8,
                "fail_count": 1,
                "segmented_count": 6,
                "fallback_count": 2,
                "current_item_id": "101",
                "estimated_remaining_seconds": 30,
                "estimated_remaining": "约30秒",
                "error_message": None,
                "task_scope": "batch",
            }
        ],
        1,
    ))
    req = parts_service.ReconstructionIndexTaskListReq(
        page=1,
        pageSize=20,
        status="active",
        task_scope="all",
    )
    session = AsyncMock()

    with patch.dict(
        parts_service.list_v2_index_rebuild_tasks.__globals__,
        {
            "index_rebuild_task_manager": task_manager,
            "SessionLocal": MagicMock(return_value=_AsyncSessionContext(session)),
        },
    ), patch.object(
        parts_service.list_v2_index_rebuild_tasks.__globals__["Items"],
        "list_item_id_codes_by_ids",
        AsyncMock(return_value=[(101, "4000205745")]),
    ) as codes_mock:
        result = asyncio.run(parts_service.list_v2_index_rebuild_tasks(req))

    task_manager.list.assert_awaited_once_with(
        page=1,
        per_page=20,
        status="active",
        task_scope="all",
        item_id=None,
    )
    assert result.total == 1
    assert result.records[0].task_id == "index-task-1"
    assert result.records[0].current_item_code == "4000205745"
    assert not hasattr(result.records[0], "current_item_id")
    codes_mock.assert_awaited_once()


def test_v2_index_rebuild_cancel_route_forwards_reason():
    parts_service = _import_parts_service()
    task_manager = MagicMock()
    task_manager.cancel = AsyncMock(return_value={
        "task_id": "index-task-1",
        "status": "cancelling",
        "progress": 40,
        "total_items": 10,
        "processed_items": 4,
        "success_count": 8,
        "fail_count": 1,
        "segmented_count": 6,
        "fallback_count": 2,
        "current_item_id": "101",
        "estimated_remaining_seconds": None,
        "estimated_remaining": None,
        "error_message": None,
        "cancel_reason": "用户取消",
    })
    req = parts_service.ReconstructionIndexTaskCancelReq(cancel_reason="用户取消")
    session = AsyncMock()

    with patch.dict(
        parts_service.cancel_v2_index_rebuild_task.__globals__,
        {
            "index_rebuild_task_manager": task_manager,
            "SessionLocal": MagicMock(return_value=_AsyncSessionContext(session)),
        },
    ), patch.object(
        parts_service.cancel_v2_index_rebuild_task.__globals__["Items"],
        "list_item_id_codes_by_ids",
        AsyncMock(return_value=[(101, "4000205745")]),
    ) as codes_mock:
        result = asyncio.run(
            parts_service.cancel_v2_index_rebuild_task("index-task-1", req)
        )

    task_manager.cancel.assert_awaited_once_with("index-task-1", "用户取消")
    assert result.status == "cancelling"
    assert result.current_item_code == "4000205745"
    assert not hasattr(result, "current_item_id")
    codes_mock.assert_awaited_once()


def test_v2_index_rebuild_cancel_route_maps_missing_task_to_404():
    parts_service = _import_parts_service()
    task_manager = MagicMock()
    task_manager.cancel = AsyncMock(side_effect=KeyError("missing-task"))
    req = parts_service.ReconstructionIndexTaskCancelReq()

    with patch.dict(
        parts_service.cancel_v2_index_rebuild_task.__globals__,
        {"index_rebuild_task_manager": task_manager},
    ), pytest.raises(HTTPException) as exc_info:
        asyncio.run(parts_service.cancel_v2_index_rebuild_task("missing-task", req))

    assert exc_info.value.status_code == 404


def test_v2_index_rebuild_retry_route_returns_new_task_id():
    parts_service = _import_parts_service()
    task_manager = MagicMock()
    task_manager.retry = AsyncMock(return_value={
        "task_id": "retry-task-2",
        "status": "pending",
        "item_id": None,
        "item_limit": 6,
        "rebuild_existing": True,
    })
    rebuild_runner = AsyncMock()

    with patch.dict(
        parts_service.retry_v2_index_rebuild_task.__globals__,
        {"index_rebuild_task_manager": task_manager},
    ), patch.object(
        parts_service.RailwayPartsManager,
        "rebuild_v2_index",
        rebuild_runner,
        create=True,
    ):
        result = asyncio.run(parts_service.retry_v2_index_rebuild_task("source-task"))

    task_manager.retry.assert_awaited_once_with(
        "source-task",
        runner=rebuild_runner,
    )
    assert result.task_id == "retry-task-2"


def test_v2_index_rebuild_retry_route_maps_lifecycle_conflict_to_409():
    parts_service = _import_parts_service()
    task_manager = MagicMock()
    task_manager.retry = AsyncMock(
        side_effect=RuntimeError("当前索引任务不可重试: status=running")
    )

    with patch.dict(
        parts_service.retry_v2_index_rebuild_task.__globals__,
        {"index_rebuild_task_manager": task_manager},
    ), patch.object(
        parts_service.RailwayPartsManager,
        "rebuild_v2_index",
        AsyncMock(),
        create=True,
    ), pytest.raises(HTTPException) as exc_info:
        asyncio.run(parts_service.retry_v2_index_rebuild_task("running-task"))

    assert exc_info.value.status_code == 409
