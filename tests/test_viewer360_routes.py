import asyncio
import importlib
import os
import sys

import pytest
from pydantic import ValidationError

os.environ["SGO_KINGBASE_PORT"] = "54321"
os.environ["SGO_MYSQL_PORT"] = "3306"

from csrcqsf.modules.railway_parts.schemas.viewer360 import (
    Viewer360FailureListReq,
    Viewer360RetryReq,
    Viewer360TaskCreateReq,
    Viewer360TaskListReq,
    Viewer360TaskStatusRes,
    Viewer360StatisticsReq,
)


def _prepare_sgo_import():
    from csrcqsf.core import settings

    settings.ai_settings.sgo_mysql_port = "3306"
    settings.ai_settings.sgo_kingbase_port = "54321"


def test_viewer360_request_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        Viewer360TaskCreateReq(item_id="12", rebuild_existing=False, unknown=True)
    with pytest.raises(ValidationError):
        Viewer360RetryReq(
            retry_mode="resegment_rows",
            row_indexes=[2],
            prompt_box=[1, 2, 3, 4],
        )


def test_viewer360_request_fields_have_swagger_descriptions_and_examples():
    for model in (
        Viewer360TaskCreateReq,
        Viewer360TaskListReq,
        Viewer360FailureListReq,
        Viewer360RetryReq,
    ):
        schema = model.schema(by_alias=True)
        assert all(
            property_schema.get("description")
            for property_schema in schema["properties"].values()
        )

    retry_schema = Viewer360RetryReq.schema(by_alias=True)
    assert retry_schema["example"] == {
        "retry_mode": "resume",
        "row_indexes": None,
        "reason": "复用断点重新执行 Viewer360 任务",
    }
    assert "复用原 task_id" in retry_schema["properties"]["retry_mode"]["description"]
    assert "failed" in retry_schema["properties"]["retry_mode"]["description"]
    assert "1-based" in retry_schema["properties"]["row_indexes"]["description"]

    row_schema = Viewer360TaskStatusRes.schema()["definitions"]["Viewer360RowState"]
    assert row_schema["properties"]["image_base_url"]["description"]
    assert row_schema["properties"]["frame_url_template"]["description"]


def test_viewer360_routes_are_registered():
    _prepare_sgo_import()
    # 其他结构测试会临时注入空路由模块，重新导入以验证真实注册结果。
    for module_name in (
        "csrcqsf.modules.railway_parts.routes.viewer360_routes",
        "csrcqsf.modules.railway_parts.routes.router",
        "csrcqsf.modules.railway_parts.routes",
    ):
        sys.modules.pop(module_name, None)
    parts_router = importlib.import_module(
        "csrcqsf.modules.railway_parts.routes.router"
    ).parts_router

    paths = {route.path for route in parts_router.routes}
    assert {
        "/railway/parts/v2/viewer360/tasks",
        "/railway/parts/v2/viewer360/tasks/list",
        "/railway/parts/v2/viewer360/tasks/statistics",
        "/railway/parts/v2/viewer360/tasks/{task_id}",
        "/railway/parts/v2/viewer360/tasks/{task_id}/failures/list",
        "/railway/parts/v2/viewer360/tasks/{task_id}/cancel",
        "/railway/parts/v2/viewer360/tasks/{task_id}/retry",
        "/railway/parts/v2/viewer360/items/{item_id}/result",
        "/railway/parts/v2/viewer360/tasks/{task_id}/result",
    }.issubset(paths)


def test_viewer360_statistics_route_returns_stable_statistics(monkeypatch):
    _prepare_sgo_import()
    from csrcqsf.modules.railway_parts.routes import viewer360_routes

    async def statistics():
        return {
            "total_tasks": 8,
            "running_tasks": 1,
            "success_tasks": 5,
            "failed_tasks": 1,
            "cancelled_tasks": 1,
            "success_rate": 5 / 6,
            "avg_success_elapsed_sec": 120.0,
            "min_success_elapsed_sec": 100.0,
            "max_success_elapsed_sec": 150.0,
        }

    monkeypatch.setattr(viewer360_routes.viewer360_task_manager, "statistics", statistics)
    result = asyncio.run(
        viewer360_routes.get_viewer360_statistics(Viewer360StatisticsReq())
    )

    assert result.total_tasks == 8
    assert result.success_rate == 5 / 6


def test_create_route_returns_stable_start_response(monkeypatch):
    _prepare_sgo_import()
    from csrcqsf.modules.railway_parts.routes import viewer360_routes

    async def submit(**_kwargs):
        return {
            "task_id": "task-1",
            "item_id": "12",
            "status": "pending",
            "reused_existing": False,
        }

    monkeypatch.setattr(viewer360_routes.viewer360_task_manager, "submit", submit)
    result = asyncio.run(
        viewer360_routes.create_viewer360_task(
            Viewer360TaskCreateReq(item_id="12", rebuild_existing=False)
        )
    )

    assert result.task_id == "task-1"
    assert result.item_id == "12"
    assert result.reused_existing is False
