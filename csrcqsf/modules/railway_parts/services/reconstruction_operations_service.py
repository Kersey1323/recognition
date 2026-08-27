"""Task-scoped reconstruction recovery, diagnostics, and cleanup orchestration."""

from __future__ import annotations

import json
import logging
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError

from csrcqsf.models.orm.reconstruction import ReconstructionRecord, ReconstructionStatus
from csrcqsf.modules.railway_parts.integrations.reconstruction_client import (
    ReconstructionServiceClient,
    ReconstructionServiceClientError,
    ReconstructionUpstreamStream,
)
from csrcqsf.modules.railway_parts.schemas.reconstruction_operations import (
    ReconstructionDiagnosticsRes,
    ReconstructionOutputOperationRes,
    ReconstructionRecoveryPlanRes,
    ReconstructionRecoveryReq,
    ReconstructionRecoverySubmitRes,
)


logger = logging.getLogger(__name__)

_PUBLIC_ROUTE_PREFIX = "/railway/parts/v2/reconstruct"
_PRESERVED_REMOTE_STATUSES = {404, 409, 422, 503}
_URL_RE = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)
_ABSOLUTE_PATH_RE = re.compile(r"(?<!\w)/(?:[^\s,;]+/)*[^\s,;]*")
_SENSITIVE_SUMMARY_KEYS = {
    "authorization",
    "token",
    "access_token",
    "password",
    "file_body",
    "output_dir",
    "download_url",
    "log_download_url",
}


class ReconstructionOperationsError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _public_error_detail(detail: str) -> str:
    first_line = str(detail).splitlines()[0].strip()
    cleaned = _URL_RE.sub("[内部地址已隐藏]", first_line)
    cleaned = _ABSOLUTE_PATH_RE.sub("[内部路径已隐藏]", cleaned)
    return (cleaned or "重构服务请求失败")[:500]


def _status_value(record: ReconstructionRecord) -> str:
    value = record.status
    return str(getattr(value, "value", value)).lower()


def _sanitize_summary(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_summary(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_SUMMARY_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_summary(item) for item in value[:100]]
    if isinstance(value, str):
        return _public_error_detail(value)
    return value


class ReconstructionOperationsService:
    def __init__(self, session, client: ReconstructionServiceClient | None = None):
        self.session = session
        self.client = client or ReconstructionServiceClient()

    async def get_owned_record(self, task_id: str) -> ReconstructionRecord:
        record = await ReconstructionRecord.get_by_task_id(self.session, task_id)
        if record is None:
            raise ReconstructionOperationsError(404, "三维重构任务不存在")
        return record

    @staticmethod
    def validate_artifact_path(relative_path: str) -> str:
        if not relative_path or len(relative_path) > 1000 or "\x00" in relative_path:
            raise ReconstructionOperationsError(400, "诊断产物路径无效")
        path = PurePosixPath(relative_path.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ReconstructionOperationsError(400, "诊断产物路径无效")
        return relative_path

    @staticmethod
    def _map_client_error(exc: ReconstructionServiceClientError) -> ReconstructionOperationsError:
        if exc.error_kind == "timeout":
            status_code = 504
        elif exc.error_kind == "connection":
            status_code = 502
        elif exc.status_code in _PRESERVED_REMOTE_STATUSES:
            status_code = int(exc.status_code)
        else:
            status_code = 502
        return ReconstructionOperationsError(status_code, _public_error_detail(exc.detail))

    @staticmethod
    def _invalid_remote_response(exc: ValidationError) -> ReconstructionOperationsError:
        logger.warning("重构服务响应格式不符合运维接口契约: %s", exc)
        return ReconstructionOperationsError(502, "重构服务响应格式错误")

    async def get_recovery_plan(self, task_id: str) -> ReconstructionRecoveryPlanRes:
        await self.get_owned_record(task_id)
        try:
            payload = await self.client.get_recovery_plan(task_id)
            return ReconstructionRecoveryPlanRes(**payload)
        except ReconstructionServiceClientError as exc:
            raise self._map_client_error(exc) from exc
        except ValidationError as exc:
            raise self._invalid_remote_response(exc) from exc

    async def submit_recovery(
        self,
        task_id: str,
        request: ReconstructionRecoveryReq,
        *,
        operator_id: str = "unauthenticated",
    ) -> ReconstructionRecoverySubmitRes:
        record = await self.get_owned_record(task_id)
        request_summary = {
            "mode": request.mode.value,
            "reason": request.reason,
        }
        status_code = 200
        response_summary: dict[str, Any] | None = None
        error_message: str | None = None
        try:
            payload = await self.client.submit_recovery(task_id, request_summary)
            result = ReconstructionRecoverySubmitRes(**payload)
            # 下游接受恢复任务后，原业务任务重新进入运行态；旧失败快照不能继续覆盖恢复进度。
            record.status = ReconstructionStatus.TRAINING
            record.current_stage = f"等待人工恢复: {result.resume_from}"
            record.error_message = None
            record.completed_at = None
            record.elapsed_sec = None
            await self.session.commit()
            response_summary = result.dict()
            return result
        except ReconstructionServiceClientError as exc:
            mapped = self._map_client_error(exc)
            status_code = mapped.status_code
            error_message = mapped.detail
            raise mapped from exc
        except ValidationError as exc:
            mapped = self._invalid_remote_response(exc)
            status_code = mapped.status_code
            error_message = mapped.detail
            raise mapped from exc
        except Exception as exc:
            logger.exception("提交三维重构恢复任务失败: task_id=%s", task_id)
            mapped = ReconstructionOperationsError(502, "提交三维重构恢复任务失败")
            status_code = mapped.status_code
            error_message = mapped.detail
            raise mapped from exc
        finally:
            await self._write_audit(
                operation="recovery_submit",
                operator_id=operator_id,
                record=record,
                request_summary=request_summary,
                response_summary=response_summary,
                success=error_message is None,
                status_code=status_code,
                error_message=error_message,
            )

    async def get_diagnostics(self, task_id: str) -> ReconstructionDiagnosticsRes:
        await self.get_owned_record(task_id)
        try:
            payload = await self.client.get_diagnostics(task_id)
            base_url = f"{_PUBLIC_ROUTE_PREFIX}/tasks/{task_id}"
            artifacts = []
            for raw_artifact in payload.get("key_artifacts") or []:
                relative_path = self.validate_artifact_path(
                    str(raw_artifact.get("relative_path") or "")
                )
                artifacts.append(
                    {
                        "relative_path": relative_path,
                        "kind": raw_artifact.get("kind"),
                        "size_bytes": raw_artifact.get("size_bytes"),
                        "modified_at": raw_artifact.get("modified_at"),
                        "download_url": (
                            f"{base_url}/diagnostics/artifacts/download?"
                            f"{urlencode({'path': relative_path})}"
                        ),
                    }
                )
            public_payload = {
                "task_id": payload.get("task_id"),
                "status": payload.get("status"),
                "current_stage": payload.get("current_stage"),
                "file_count": payload.get("file_count", 0),
                "total_size_bytes": payload.get("total_size_bytes", 0),
                "camera_count": payload.get("camera_count"),
                "log_download_url": f"{base_url}/logs/download",
                "diagnostics_download_url": f"{base_url}/diagnostics/download",
                "key_artifacts": artifacts,
            }
            return ReconstructionDiagnosticsRes(**public_payload)
        except ReconstructionServiceClientError as exc:
            raise self._map_client_error(exc) from exc
        except ValidationError as exc:
            raise self._invalid_remote_response(exc) from exc

    async def open_task_log(self, task_id: str) -> ReconstructionUpstreamStream:
        await self.get_owned_record(task_id)
        try:
            return await self.client.stream_task_log(task_id)
        except ReconstructionServiceClientError as exc:
            raise self._map_client_error(exc) from exc

    async def open_diagnostic_artifact(
        self,
        task_id: str,
        relative_path: str,
    ) -> ReconstructionUpstreamStream:
        await self.get_owned_record(task_id)
        relative_path = self.validate_artifact_path(relative_path)
        try:
            return await self.client.stream_diagnostic_artifact(task_id, relative_path)
        except ReconstructionServiceClientError as exc:
            raise self._map_client_error(exc) from exc

    async def open_diagnostics_archive(
        self,
        task_id: str,
    ) -> ReconstructionUpstreamStream:
        await self.get_owned_record(task_id)
        try:
            return await self.client.stream_diagnostics_archive(task_id)
        except ReconstructionServiceClientError as exc:
            raise self._map_client_error(exc) from exc

    async def operate_output(
        self,
        task_id: str,
        *,
        confirm: bool,
        operator_id: str = "unauthenticated",
    ) -> ReconstructionOutputOperationRes:
        record = await self.get_owned_record(task_id)
        request_summary = {"confirm": confirm}
        status_code = 200
        response_summary: dict[str, Any] | None = None
        error_message: str | None = None
        try:
            # 工作目录只允许在任务终态清理，避免删除仍在写入的训练中间产物。
            if _status_value(record) not in {"success", "failed", "cancelled"}:
                raise ReconstructionOperationsError(409, "运行中的任务不能清理工作目录")
            # 成功任务的业务模型必须已进入 MinIO，确认删除时才可释放节点工作目录。
            if confirm and _status_value(record) == "success" and not any(
                (record.ply_url, record.obj_url, record.glb_url)
            ):
                raise ReconstructionOperationsError(
                    409,
                    "业务模型尚未持久化，不能清理重构工作目录",
                )

            payload = await self.client.delete_task_output(task_id, confirm=confirm)
            public_payload = {
                "task_id": payload.get("task_id"),
                "status": payload.get("status"),
                "directory_name": payload.get("directory_name"),
                "file_count": payload.get("file_count"),
                "size_bytes": payload.get("size_bytes"),
                "deleted": payload.get("deleted"),
                "confirmation_required": payload.get("confirmation_required"),
            }
            result = ReconstructionOutputOperationRes(**public_payload)
            if not confirm and result.deleted:
                raise ReconstructionOperationsError(502, "重构服务错误执行了预览请求")
            response_summary = result.dict()
            return result
        except ReconstructionServiceClientError as exc:
            mapped = self._map_client_error(exc)
            status_code = mapped.status_code
            error_message = mapped.detail
            raise mapped from exc
        except ValidationError as exc:
            mapped = self._invalid_remote_response(exc)
            status_code = mapped.status_code
            error_message = mapped.detail
            raise mapped from exc
        except ReconstructionOperationsError as exc:
            status_code = exc.status_code
            error_message = exc.detail
            raise
        except Exception as exc:
            logger.exception("操作三维重构工作目录失败: task_id=%s", task_id)
            mapped = ReconstructionOperationsError(502, "操作三维重构工作目录失败")
            status_code = mapped.status_code
            error_message = mapped.detail
            raise mapped from exc
        finally:
            await self._write_audit(
                operation="output_delete",
                operator_id=operator_id,
                record=record,
                request_summary=request_summary,
                response_summary=response_summary,
                success=error_message is None,
                status_code=status_code,
                error_message=error_message,
            )

    async def _write_audit(
        self,
        *,
        operation: str,
        operator_id: str,
        record: ReconstructionRecord,
        request_summary: dict[str, Any],
        response_summary: dict[str, Any] | None,
        success: bool,
        status_code: int,
        error_message: str | None,
    ) -> None:
        from csrcqsf.infra.db.main_db import SessionLocal
        from csrcqsf.models.orm.reconstruction_operation_audit import (
            ReconstructionOperationAudit,
        )

        try:
            async with SessionLocal.begin() as session:
                session.add(
                    ReconstructionOperationAudit(
                        operation=operation,
                        operator_id=operator_id,
                        task_id=record.task_id,
                        item_id=record.item_id,
                        request_summary_json=json.dumps(
                            _sanitize_summary(request_summary),
                            ensure_ascii=False,
                        ),
                        response_summary_json=(
                            json.dumps(
                                _sanitize_summary(response_summary),
                                ensure_ascii=False,
                            )
                            if response_summary is not None
                            else None
                        ),
                        success=success,
                        status_code=status_code,
                        error_message=(
                            _public_error_detail(error_message)
                            if error_message
                            else None
                        ),
                    )
                )
        except Exception:
            logger.exception("写入三维重构运维审计失败: task_id=%s", record.task_id)
