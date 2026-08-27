import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from csrcqsf.modules.railway_parts.integrations.reconstruction_client import (
    ReconstructionServiceClientError,
)
from csrcqsf.modules.railway_parts.schemas.reconstruction_operations import (
    ReconstructionRecoveryReq,
)
from csrcqsf.modules.railway_parts.services.reconstruction_operations_service import (
    ReconstructionOperationsError,
    ReconstructionOperationsService,
)
from csrcqsf.models.orm.reconstruction import ReconstructionStatus


def _record(**overrides):
    values = {
        "task_id": "task-1",
        "item_id": 1001,
        "status": "failed",
        "ply_url": None,
        "obj_url": None,
        "glb_url": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_missing_owned_task_stops_before_downstream_call():
    client = SimpleNamespace(get_recovery_plan=AsyncMock())
    service = ReconstructionOperationsService(session=object(), client=client)

    with patch(
        "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
        "ReconstructionRecord.get_by_task_id",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(ReconstructionOperationsError) as exc_info:
            asyncio.run(service.get_recovery_plan("missing"))

    assert exc_info.value.status_code == 404
    client.get_recovery_plan.assert_not_awaited()


@pytest.mark.parametrize(
    "path",
    ["", "../secret", "/etc/passwd", "train/../secret", "a\x00b", "x" * 1001],
)
def test_artifact_path_rejects_unsafe_values(path):
    with pytest.raises(ReconstructionOperationsError) as exc_info:
        ReconstructionOperationsService.validate_artifact_path(path)

    assert exc_info.value.status_code == 400


def test_diagnostics_removes_internal_paths_and_rewrites_download_urls():
    client = SimpleNamespace(
        get_diagnostics=AsyncMock(
            return_value={
                "task_id": "task-1",
                "status": "FAILED",
                "current_stage": "train",
                "output_dir": "/srv/reconstruction/outputs/scene-task-1",
                "file_count": 2,
                "total_size_bytes": 123,
                "camera_count": 4,
                "log_download_url": "http://reconstruction:8000/internal/log",
                "key_artifacts": [
                    {
                        "relative_path": "train/ours_30000/render 1.png",
                        "kind": "render",
                        "size_bytes": 12,
                        "modified_at": "2026-08-27T08:00:00+00:00",
                        "download_url": "http://reconstruction/internal/artifact",
                    }
                ],
            }
        )
    )
    service = ReconstructionOperationsService(session=object(), client=client)

    with patch(
        "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
        "ReconstructionRecord.get_by_task_id",
        new=AsyncMock(return_value=_record()),
    ):
        result = asyncio.run(service.get_diagnostics("task-1"))

    payload = result.dict()
    assert "output_dir" not in payload
    assert payload["log_download_url"].endswith("/tasks/task-1/logs/download")
    assert payload["diagnostics_download_url"].endswith(
        "/tasks/task-1/diagnostics/download"
    )
    artifact_url = payload["key_artifacts"][0]["download_url"]
    assert "path=train%2Fours_30000%2Frender+1.png" in artifact_url
    assert "reconstruction:8000" not in str(payload)


@pytest.mark.parametrize(
    ("client_error", "expected_status"),
    [
        (ReconstructionServiceClientError("not found", status_code=404), 404),
        (ReconstructionServiceClientError("conflict", status_code=409), 409),
        (ReconstructionServiceClientError("invalid", status_code=422), 422),
        (ReconstructionServiceClientError("redis down", status_code=503), 503),
        (ReconstructionServiceClientError("bad gateway", status_code=500), 502),
        (ReconstructionServiceClientError("offline", error_kind="connection"), 502),
        (ReconstructionServiceClientError("slow", error_kind="timeout"), 504),
    ],
)
def test_downstream_errors_are_mapped(client_error, expected_status):
    client = SimpleNamespace(get_recovery_plan=AsyncMock(side_effect=client_error))
    service = ReconstructionOperationsService(session=object(), client=client)

    with patch(
        "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
        "ReconstructionRecord.get_by_task_id",
        new=AsyncMock(return_value=_record()),
    ):
        with pytest.raises(ReconstructionOperationsError) as exc_info:
            asyncio.run(service.get_recovery_plan("task-1"))

    assert exc_info.value.status_code == expected_status


def test_public_error_removes_internal_url_and_absolute_path():
    error = ReconstructionServiceClientError(
        "failed at /srv/private/task; see http://reconstruction:8000/debug",
        status_code=422,
    )
    client = SimpleNamespace(get_recovery_plan=AsyncMock(side_effect=error))
    service = ReconstructionOperationsService(session=object(), client=client)

    with patch(
        "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
        "ReconstructionRecord.get_by_task_id",
        new=AsyncMock(return_value=_record()),
    ):
        with pytest.raises(ReconstructionOperationsError) as exc_info:
            asyncio.run(service.get_recovery_plan("task-1"))

    assert "/srv/private" not in exc_info.value.detail
    assert "http://" not in exc_info.value.detail


def test_recovery_submission_does_not_forward_iterations():
    client = SimpleNamespace(
        submit_recovery=AsyncMock(
            return_value={
                "task_id": "task-1",
                "recovery_task_id": "recovery-1",
                "recovery_attempt": 1,
                "mode": "restart_training",
                "resume_from": "train",
                "status": "SUBMITTED",
            }
        )
    )
    service = ReconstructionOperationsService(session=AsyncMock(), client=client)

    with (
        patch(
            "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
            "ReconstructionRecord.get_by_task_id",
            new=AsyncMock(return_value=_record()),
        ),
        patch.object(service, "_write_audit", new=AsyncMock()),
    ):
        asyncio.run(
            service.submit_recovery(
                "task-1",
                ReconstructionRecoveryReq(mode="auto", reason="retry"),
            )
        )

    payload = client.submit_recovery.await_args.args[1]
    assert payload == {"mode": "auto", "reason": "retry"}
    assert "iterations" not in payload


def test_successful_recovery_submission_reopens_failed_business_record():
    session = AsyncMock()
    record = _record(
        status=ReconstructionStatus.FAILED,
        progress=55,
        current_stage="失败",
        error_message="COLMAP match database is incomplete",
        completed_at=datetime(2026, 8, 27, 11, 27, 47),
        elapsed_sec=356.0,
    )
    client = SimpleNamespace(
        submit_recovery=AsyncMock(
            return_value={
                "task_id": "task-1",
                "recovery_task_id": "recovery-1",
                "recovery_attempt": 1,
                "mode": "colmap",
                "resume_from": "colmap",
                "status": "RECOVERY_QUEUED",
            }
        )
    )
    service = ReconstructionOperationsService(session=session, client=client)

    with (
        patch(
            "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
            "ReconstructionRecord.get_by_task_id",
            new=AsyncMock(return_value=record),
        ),
        patch.object(service, "_write_audit", new=AsyncMock()),
    ):
        asyncio.run(service.submit_recovery("task-1", ReconstructionRecoveryReq()))

    assert record.status == ReconstructionStatus.TRAINING
    assert record.progress == 55
    assert record.current_stage == "等待人工恢复: colmap"
    assert record.error_message is None
    assert record.completed_at is None
    assert record.elapsed_sec is None
    session.commit.assert_awaited_once()


def test_failed_recovery_submission_keeps_terminal_business_record():
    session = AsyncMock()
    completed_at = datetime(2026, 8, 27, 11, 27, 47)
    record = _record(
        status=ReconstructionStatus.FAILED,
        progress=55,
        current_stage="失败",
        error_message="COLMAP failed",
        completed_at=completed_at,
        elapsed_sec=356.0,
    )
    client = SimpleNamespace(
        submit_recovery=AsyncMock(
            side_effect=ReconstructionServiceClientError("conflict", status_code=409)
        )
    )
    service = ReconstructionOperationsService(session=session, client=client)

    with (
        patch(
            "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
            "ReconstructionRecord.get_by_task_id",
            new=AsyncMock(return_value=record),
        ),
        patch.object(service, "_write_audit", new=AsyncMock()),
    ):
        with pytest.raises(ReconstructionOperationsError):
            asyncio.run(service.submit_recovery("task-1", ReconstructionRecoveryReq()))

    assert record.status == ReconstructionStatus.FAILED
    assert record.current_stage == "失败"
    assert record.error_message == "COLMAP failed"
    assert record.completed_at == completed_at
    assert record.elapsed_sec == 356.0
    session.commit.assert_not_awaited()


def test_output_preview_never_reports_deleted_and_strips_output_dir():
    client = SimpleNamespace(
        delete_task_output=AsyncMock(
            return_value={
                "task_id": "task-1",
                "status": "FAILED",
                "output_dir": "/srv/private/task-1",
                "directory_name": "scene-task-1",
                "file_count": 10,
                "size_bytes": 1000,
                "deleted": False,
                "confirmation_required": True,
            }
        )
    )
    service = ReconstructionOperationsService(session=object(), client=client)

    with (
        patch(
            "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
            "ReconstructionRecord.get_by_task_id",
            new=AsyncMock(return_value=_record()),
        ),
        patch.object(service, "_write_audit", new=AsyncMock()),
    ):
        result = asyncio.run(service.operate_output("task-1", confirm=False))

    assert result.deleted is False
    assert "output_dir" not in result.dict()
    client.delete_task_output.assert_awaited_once_with("task-1", confirm=False)


@pytest.mark.parametrize("status", ["pending", "training", "converting"])
def test_output_cleanup_rejects_non_terminal_task(status):
    client = SimpleNamespace(delete_task_output=AsyncMock())
    service = ReconstructionOperationsService(session=object(), client=client)

    with (
        patch(
            "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
            "ReconstructionRecord.get_by_task_id",
            new=AsyncMock(return_value=_record(status=status)),
        ),
        patch.object(service, "_write_audit", new=AsyncMock()) as audit,
    ):
        with pytest.raises(ReconstructionOperationsError) as exc_info:
            asyncio.run(service.operate_output("task-1", confirm=True))

    assert exc_info.value.status_code == 409
    client.delete_task_output.assert_not_awaited()
    assert audit.await_args.kwargs["success"] is False
    assert audit.await_args.kwargs["status_code"] == 409


def test_confirmed_cleanup_requires_persisted_business_model_for_success_task():
    client = SimpleNamespace(delete_task_output=AsyncMock())
    service = ReconstructionOperationsService(session=object(), client=client)

    with (
        patch(
            "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
            "ReconstructionRecord.get_by_task_id",
            new=AsyncMock(return_value=_record(status="success")),
        ),
        patch.object(service, "_write_audit", new=AsyncMock()) as audit,
    ):
        with pytest.raises(ReconstructionOperationsError) as exc_info:
            asyncio.run(service.operate_output("task-1", confirm=True))

    assert exc_info.value.status_code == 409
    client.delete_task_output.assert_not_awaited()
    assert audit.await_args.kwargs["success"] is False
    assert audit.await_args.kwargs["status_code"] == 409


def test_confirmed_cleanup_does_not_clear_persisted_business_model_urls():
    record = _record(
        status="success",
        ply_url="bfr-reconstruction-files/result.ply",
    )
    client = SimpleNamespace(
        delete_task_output=AsyncMock(
            return_value={
                "task_id": "task-1",
                "status": "SUCCESS",
                "directory_name": "scene-task-1",
                "file_count": 10,
                "size_bytes": 1000,
                "deleted": True,
                "confirmation_required": False,
            }
        )
    )
    service = ReconstructionOperationsService(session=object(), client=client)

    with (
        patch(
            "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
            "ReconstructionRecord.get_by_task_id",
            new=AsyncMock(return_value=record),
        ),
        patch.object(service, "_write_audit", new=AsyncMock()),
    ):
        result = asyncio.run(service.operate_output("task-1", confirm=True))

    assert result.deleted is True
    assert record.ply_url == "bfr-reconstruction-files/result.ply"


def test_unexpected_recovery_error_is_audited_as_failure():
    client = SimpleNamespace(submit_recovery=AsyncMock(side_effect=RuntimeError("boom")))
    service = ReconstructionOperationsService(session=object(), client=client)

    with (
        patch(
            "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
            "ReconstructionRecord.get_by_task_id",
            new=AsyncMock(return_value=_record()),
        ),
        patch.object(service, "_write_audit", new=AsyncMock()) as audit,
    ):
        with pytest.raises(ReconstructionOperationsError) as exc_info:
            asyncio.run(
                service.submit_recovery("task-1", ReconstructionRecoveryReq())
            )

    assert exc_info.value.status_code == 502
    assert audit.await_args.kwargs["success"] is False
    assert audit.await_args.kwargs["status_code"] == 502


def test_unexpected_cleanup_error_is_audited_as_failure():
    client = SimpleNamespace(
        delete_task_output=AsyncMock(side_effect=RuntimeError("boom"))
    )
    service = ReconstructionOperationsService(session=object(), client=client)

    with (
        patch(
            "csrcqsf.modules.railway_parts.services.reconstruction_operations_service."
            "ReconstructionRecord.get_by_task_id",
            new=AsyncMock(return_value=_record()),
        ),
        patch.object(service, "_write_audit", new=AsyncMock()) as audit,
    ):
        with pytest.raises(ReconstructionOperationsError) as exc_info:
            asyncio.run(service.operate_output("task-1", confirm=False))

    assert exc_info.value.status_code == 502
    assert audit.await_args.kwargs["success"] is False
    assert audit.await_args.kwargs["status_code"] == 502
