"""面向前端的任务级三维重构运维路由。"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Query
from fastapi.responses import StreamingResponse

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.modules.railway_parts.schemas.reconstruction_operations import (
    ReconstructionDiagnosticsRes,
    ReconstructionOutputOperationRes,
    ReconstructionRecoveryPlanRes,
    ReconstructionRecoveryReq,
    ReconstructionRecoverySubmitRes,
)
from csrcqsf.modules.railway_parts.services.reconstruction_operations_service import (
    ReconstructionOperationsError,
    ReconstructionOperationsService,
)

from .router import parts_router


logger = logging.getLogger(__name__)
_TAG = ["算法-3D重建V2-运维"]


def _raise_http_error(exc: ReconstructionOperationsError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


async def _stream_response(open_stream):
    try:
        stream = await open_stream()
    except ReconstructionOperationsError as exc:
        _raise_http_error(exc)
    return StreamingResponse(
        stream.iter_bytes(),
        status_code=200,
        media_type=stream.content_type,
        headers=stream.safe_headers,
    )


@parts_router.get(
    "/v2/reconstruct/tasks/{task_id}/recovery/plan",
    tags=_TAG,
    summary="V2: 查询三维重构任务恢复计划",
    response_model=ReconstructionRecoveryPlanRes,
)
async def get_reconstruction_recovery_plan(task_id: str):
    async with SessionLocal() as session:
        service = ReconstructionOperationsService(session)
        try:
            return await service.get_recovery_plan(task_id)
        except ReconstructionOperationsError as exc:
            _raise_http_error(exc)


@parts_router.post(
    "/v2/reconstruct/tasks/{task_id}/recovery",
    tags=_TAG,
    summary="V2: 恢复失败的三维重构任务",
    response_model=ReconstructionRecoverySubmitRes,
)
async def submit_reconstruction_recovery(
    task_id: str,
    req: ReconstructionRecoveryReq,
):
    # 当前登录体系尚未稳定，操作人统一记为 unauthenticated，便于后续接入可信身份。
    async with SessionLocal() as session:
        service = ReconstructionOperationsService(session)
        try:
            return await service.submit_recovery(
                task_id,
                req,
                operator_id="unauthenticated",
            )
        except ReconstructionOperationsError as exc:
            _raise_http_error(exc)


@parts_router.get(
    "/v2/reconstruct/tasks/{task_id}/logs/download",
    tags=_TAG,
    summary="V2: 下载三维重构任务日志",
)
async def download_reconstruction_task_log(task_id: str):
    async with SessionLocal() as session:
        service = ReconstructionOperationsService(session)
        return await _stream_response(lambda: service.open_task_log(task_id))


@parts_router.get(
    "/v2/reconstruct/tasks/{task_id}/diagnostics",
    tags=_TAG,
    summary="V2: 查询三维重构任务诊断摘要",
    response_model=ReconstructionDiagnosticsRes,
)
async def get_reconstruction_diagnostics(task_id: str):
    async with SessionLocal() as session:
        service = ReconstructionOperationsService(session)
        try:
            return await service.get_diagnostics(task_id)
        except ReconstructionOperationsError as exc:
            _raise_http_error(exc)


@parts_router.get(
    "/v2/reconstruct/tasks/{task_id}/diagnostics/artifacts/download",
    tags=_TAG,
    summary="V2: 下载单个三维重构诊断产物",
)
async def download_reconstruction_diagnostic_artifact(
    task_id: str,
    path: str = Query(..., min_length=1, max_length=1000),
):
    async with SessionLocal() as session:
        service = ReconstructionOperationsService(session)
        return await _stream_response(
            lambda: service.open_diagnostic_artifact(task_id, path)
        )


@parts_router.get(
    "/v2/reconstruct/tasks/{task_id}/diagnostics/download",
    tags=_TAG,
    summary="V2: 下载三维重构任务诊断包",
)
async def download_reconstruction_diagnostics(task_id: str):
    async with SessionLocal() as session:
        service = ReconstructionOperationsService(session)
        return await _stream_response(lambda: service.open_diagnostics_archive(task_id))


@parts_router.delete(
    "/v2/reconstruct/tasks/{task_id}/output",
    tags=_TAG,
    summary="V2: 预览或清理三维重构节点工作目录",
    response_model=ReconstructionOutputOperationRes,
)
async def operate_reconstruction_task_output(
    task_id: str,
    confirm: bool = Query(
        False,
        description="false 仅预览，true 确认删除重构节点工作目录",
    ),
):
    # 该操作只清理重构节点工作目录，不删除 MinIO 业务模型或清空模型 URL。
    async with SessionLocal() as session:
        service = ReconstructionOperationsService(session)
        try:
            return await service.operate_output(
                task_id,
                confirm=confirm,
                operator_id="unauthenticated",
            )
        except ReconstructionOperationsError as exc:
            _raise_http_error(exc)
