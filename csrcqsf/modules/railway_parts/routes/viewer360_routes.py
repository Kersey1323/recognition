"""Viewer360 后台任务与当前结果接口。"""

from typing import Annotated

from fastapi import HTTPException, Path

from csrcqsf.modules.railway_parts.routes.router import parts_router
from csrcqsf.modules.railway_parts.schemas.viewer360 import (
    Viewer360CancelReq,
    Viewer360CurrentResultRes,
    Viewer360FailureListReq,
    Viewer360FailureListRes,
    Viewer360FailureRecord,
    Viewer360RetryReq,
    Viewer360TaskCreateReq,
    Viewer360TaskListReq,
    Viewer360TaskListRes,
    Viewer360TaskStartRes,
    Viewer360TaskStatusRes,
)
from csrcqsf.modules.railway_parts.services.viewer360_task_manager import (
    Viewer360ConflictError,
    Viewer360NotFoundError,
    viewer360_task_manager,
)


TAG = "业务-Viewer360"
TaskIdPath = Annotated[
    str,
    Path(
        description="Viewer360 来源任务 ID，从创建任务或任务列表响应的 task_id 获取",
        example="c87a0d15-2c7c-4e77-a9c8-63b10262ee93",
    ),
]
ItemIdPath = Annotated[
    str,
    Path(
        description="配件 ID",
        example="1595255167069540352",
    ),
]


def _raise_business_error(exc: Exception) -> None:
    if isinstance(exc, Viewer360NotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, Viewer360ConflictError):
        detail = {"message": str(exc), "active_task_id": exc.task_id}
        raise HTTPException(status_code=409, detail=detail) from exc
    raise exc


@parts_router.post(
    "/v2/viewer360/tasks",
    tags=[TAG],
    summary="创建 Viewer360 任务",
    response_model=Viewer360TaskStartRes,
)
async def create_viewer360_task(req: Viewer360TaskCreateReq):
    try:
        task = await viewer360_task_manager.submit(
            item_id=int(req.item_id),
            rebuild_existing=req.rebuild_existing,
        )
    except (Viewer360NotFoundError, Viewer360ConflictError) as exc:
        _raise_business_error(exc)
    return Viewer360TaskStartRes(**task)


@parts_router.post(
    "/v2/viewer360/tasks/list",
    tags=[TAG],
    summary="分页查询 Viewer360 任务",
    response_model=Viewer360TaskListRes,
)
async def list_viewer360_tasks(req: Viewer360TaskListReq):
    records, total = await viewer360_task_manager.list(
        page=req.page,
        per_page=req.per_page,
        status=req.status,
        item_id=int(req.item_id) if req.item_id else None,
    )
    return Viewer360TaskListRes(
        total=total,
        page=req.page,
        pageSize=req.per_page,
        records=[Viewer360TaskStatusRes(**record) for record in records],
    )


@parts_router.get(
    "/v2/viewer360/tasks/{task_id}",
    tags=[TAG],
    summary="查询 Viewer360 任务详情",
    response_model=Viewer360TaskStatusRes,
)
async def get_viewer360_task(task_id: TaskIdPath):
    task = await viewer360_task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Viewer360 任务不存在: {task_id}")
    return Viewer360TaskStatusRes(**task)


@parts_router.post(
    "/v2/viewer360/tasks/{task_id}/failures/list",
    tags=[TAG],
    summary="分页查询 Viewer360 失败明细",
    response_model=Viewer360FailureListRes,
)
async def list_viewer360_failures(
    task_id: TaskIdPath,
    req: Viewer360FailureListReq,
):
    if await viewer360_task_manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail=f"Viewer360 任务不存在: {task_id}")
    records, total = await viewer360_task_manager.list_failures(
        task_id,
        page=req.page,
        per_page=req.per_page,
    )
    return Viewer360FailureListRes(
        total=total,
        page=req.page,
        pageSize=req.per_page,
        records=[Viewer360FailureRecord(**record) for record in records],
    )


@parts_router.post(
    "/v2/viewer360/tasks/{task_id}/cancel",
    tags=[TAG],
    summary="取消 Viewer360 任务",
    response_model=Viewer360TaskStatusRes,
)
async def cancel_viewer360_task(
    task_id: TaskIdPath,
    req: Viewer360CancelReq,
):
    try:
        task = await viewer360_task_manager.cancel(task_id, req.cancel_reason)
    except (Viewer360NotFoundError, Viewer360ConflictError) as exc:
        _raise_business_error(exc)
    return Viewer360TaskStatusRes(**task)


@parts_router.post(
    "/v2/viewer360/tasks/{task_id}/retry",
    tags=[TAG],
    summary="原任务恢复或重新分割指定角度",
    response_model=Viewer360TaskStartRes,
)
async def retry_viewer360_task(
    task_id: TaskIdPath,
    req: Viewer360RetryReq,
):
    try:
        task = await viewer360_task_manager.retry(
            task_id,
            retry_mode=req.retry_mode,
            row_indexes=req.row_indexes,
            reason=req.reason,
        )
    except (Viewer360NotFoundError, Viewer360ConflictError) as exc:
        _raise_business_error(exc)
    return Viewer360TaskStartRes(**task)


@parts_router.get(
    "/v2/viewer360/items/{item_id}/result",
    tags=[TAG],
    summary="查询配件当前 Viewer360 结果",
    response_model=Viewer360CurrentResultRes,
)
async def get_viewer360_current_result(item_id: ItemIdPath):
    if not item_id.isdigit():
        raise HTTPException(status_code=422, detail="item_id must be an integer")
    return Viewer360CurrentResultRes(
        **await viewer360_task_manager.get_current_result(int(item_id))
    )


@parts_router.delete(
    "/v2/viewer360/tasks/{task_id}/result",
    tags=[TAG],
    summary="删除指定 Viewer360 版本",
    response_model=Viewer360TaskStatusRes,
)
async def delete_viewer360_result(task_id: TaskIdPath):
    try:
        task = await viewer360_task_manager.delete_result(task_id)
    except (Viewer360NotFoundError, Viewer360ConflictError) as exc:
        _raise_business_error(exc)
    return Viewer360TaskStatusRes(**task)
