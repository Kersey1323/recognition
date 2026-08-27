import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI

from csrcqsf.modules.railway_parts.routes import parts_router
from csrcqsf.modules.railway_parts.routes.reconstruction_routes import (
    get_reconstruct_v2_status,
)


EXPECTED_OPERATIONS = {
    ("GET", "/railway/parts/v2/reconstruct/tasks/{task_id}/recovery/plan"),
    ("POST", "/railway/parts/v2/reconstruct/tasks/{task_id}/recovery"),
    ("GET", "/railway/parts/v2/reconstruct/tasks/{task_id}/logs/download"),
    ("GET", "/railway/parts/v2/reconstruct/tasks/{task_id}/diagnostics"),
    (
        "GET",
        "/railway/parts/v2/reconstruct/tasks/{task_id}/diagnostics/artifacts/download",
    ),
    ("GET", "/railway/parts/v2/reconstruct/tasks/{task_id}/diagnostics/download"),
    ("DELETE", "/railway/parts/v2/reconstruct/tasks/{task_id}/output"),
}


def _openapi():
    app = FastAPI()
    app.include_router(parts_router)
    return app.openapi()


def test_operations_routes_are_explicit_and_global_cleanup_is_not_exposed():
    schema = _openapi()
    operations = {
        (method.upper(), path)
        for path, path_item in schema["paths"].items()
        for method in path_item
        if method.upper() in {"GET", "POST", "DELETE", "PUT", "PATCH"}
    }

    assert EXPECTED_OPERATIONS.issubset(operations)
    assert all("outputs/cleanup" not in path for _, path in operations)


def test_recovery_openapi_accepts_only_mode_and_reason():
    schema = _openapi()
    operation = schema["paths"][
        "/railway/parts/v2/reconstruct/tasks/{task_id}/recovery"
    ]["post"]
    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    component_name = body_schema["$ref"].rsplit("/", 1)[-1]
    properties = schema["components"]["schemas"][component_name]["properties"]

    assert set(properties) == {"mode", "reason"}
    assert "iterations" not in properties


def test_recovery_and_cleanup_routes_have_no_auth_dependency_for_current_phase():
    openapi = _openapi()

    recovery = openapi["paths"][
        "/railway/parts/v2/reconstruct/tasks/{task_id}/recovery"
    ]["post"]
    cleanup = openapi["paths"][
        "/railway/parts/v2/reconstruct/tasks/{task_id}/output"
    ]["delete"]

    assert not recovery.get("security")
    assert not cleanup.get("security")


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_existing_status_route_checks_local_task_before_manager_call():
    status_payload = {
        "task_id": "task-1",
        "item_id": "1001",
        "status": "success",
        "progress": 100,
    }

    with (
        patch(
            "csrcqsf.modules.railway_parts.routes.reconstruction_routes.SessionLocal",
            return_value=_SessionContext(),
        ),
        patch(
            "csrcqsf.modules.railway_parts.routes.reconstruction_routes."
            "ReconstructionOperationsService.get_owned_record",
            new=AsyncMock(),
        ) as ownership,
        patch(
            "csrcqsf.modules.railway_parts.routes.reconstruction_routes."
            "ReconstructionManager.get_task_status",
            new=AsyncMock(return_value=status_payload),
        ) as manager,
    ):
        result = asyncio.run(get_reconstruct_v2_status("task-1"))

    ownership.assert_awaited_once_with("task-1")
    manager.assert_awaited_once_with("task-1")
    assert result.task_id == "task-1"
