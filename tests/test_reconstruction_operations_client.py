import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from csrcqsf.modules.railway_parts.integrations.reconstruction_client import (
    ReconstructionServiceClient,
    ReconstructionServiceClientError,
)


@pytest.mark.parametrize(
    ("method_name", "args", "method", "path", "json_payload", "params"),
    [
        (
            "get_recovery_plan",
            ("task-1",),
            "GET",
            "/reconstruction/tasks/task-1/recovery/plan",
            None,
            None,
        ),
        (
            "submit_recovery",
            ("task-1", {"mode": "auto", "reason": None}),
            "POST",
            "/reconstruction/tasks/task-1/recovery",
            {"mode": "auto", "reason": None},
            None,
        ),
        (
            "get_diagnostics",
            ("task-1",),
            "GET",
            "/reconstruction/tasks/task-1/diagnostics",
            None,
            None,
        ),
        (
            "delete_task_output",
            ("task-1",),
            "DELETE",
            "/reconstruction/tasks/task-1/output",
            None,
            {"confirm": "false"},
        ),
    ],
)
def test_operations_client_uses_fixed_json_routes(
    method_name,
    args,
    method,
    path,
    json_payload,
    params,
):
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000")
    client._request = AsyncMock(return_value={"task_id": "task-1"})

    kwargs = {"confirm": False} if method_name == "delete_task_output" else {}
    asyncio.run(getattr(client, method_name)(*args, **kwargs))

    client._request.assert_awaited_once_with(
        method,
        path,
        json=json_payload,
        params=params,
    )


class _ErrorResponse:
    status = 409

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return {"detail": "任务正在恢复"}

    async def text(self):
        return "任务正在恢复"


class _ErrorSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def request(self, *args, **kwargs):
        return _ErrorResponse()


def test_operations_client_preserves_remote_status_and_clean_detail():
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000")

    with patch("aiohttp.ClientSession", return_value=_ErrorSession()):
        with pytest.raises(ReconstructionServiceClientError) as exc_info:
            asyncio.run(client.get_recovery_plan("task-1"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_kind == "remote"
    assert exc_info.value.detail == "任务正在恢复"


@pytest.mark.parametrize(
    ("exception", "error_kind"),
    [
        (aiohttp.ClientConnectionError("offline"), "connection"),
        (asyncio.TimeoutError(), "timeout"),
    ],
)
def test_operations_client_classifies_transport_errors(exception, error_kind):
    client = ReconstructionServiceClient(base_url="http://reconstruction:8000")

    with patch("aiohttp.ClientSession", side_effect=exception):
        with pytest.raises(ReconstructionServiceClientError) as exc_info:
            asyncio.run(client.get_recovery_plan("task-1"))

    assert exc_info.value.status_code is None
    assert exc_info.value.error_kind == error_kind
