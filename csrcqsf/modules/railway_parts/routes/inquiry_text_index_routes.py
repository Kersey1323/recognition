from typing import Annotated

from fastapi import HTTPException, Path

from csrcqsf.modules.railway_parts.routes.router import parts_router
from csrcqsf.modules.railway_parts.schemas._inquiry_text_index_api_models import (
    InquiryTextIndexFailureListReq,
    InquiryTextIndexFailureListRes,
    InquiryTextIndexFailureRecord,
    InquiryTextIndexTaskCancelReq,
    InquiryTextIndexTaskListReq,
    InquiryTextIndexTaskListRes,
    InquiryTextIndexTaskStartRes,
    InquiryTextIndexTaskStatusRes,
)
from csrcqsf.modules.railway_parts.services.inquiry_text_index_task_manager import (
    inquiry_text_index_task_manager,
)


TAG = "算法-询码语义索引"


@parts_router.post(
    "/v2/inquiry-text-index/rebuild",
    tags=[TAG],
    summary="全量重建询码语义索引",
    response_model=InquiryTextIndexTaskStartRes,
)
async def rebuild_inquiry_text_index():
    """创建全量后台任务；构建完成后原子切换当前 Milvus Collection。"""
    task = await inquiry_text_index_task_manager.enqueue_full()
    return InquiryTextIndexTaskStartRes(
        message="询码语义索引全量重建任务已提交",
        task_id=task["task_id"],
        task_scope="full",
        status=task["status"],
    )


@parts_router.post(
    "/v2/inquiry-text-index/tasks/list",
    tags=[TAG],
    summary="查询询码语义索引任务列表",
    response_model=InquiryTextIndexTaskListRes,
)
async def list_inquiry_text_index_tasks(req: InquiryTextIndexTaskListReq):
    records, total = await inquiry_text_index_task_manager.list(
        page=req.page,
        per_page=req.per_page,
        status=req.status,
        task_scope=req.task_scope,
    )
    return InquiryTextIndexTaskListRes(
        total=total,
        page=req.page,
        pageSize=req.per_page,
        records=[InquiryTextIndexTaskStatusRes(**record) for record in records],
    )


@parts_router.get(
    "/v2/inquiry-text-index/tasks/{task_id}",
    tags=[TAG],
    summary="查询询码语义索引任务详情",
    response_model=InquiryTextIndexTaskStatusRes,
)
async def get_inquiry_text_index_task(
    task_id: Annotated[str, Path(description="询码语义索引任务 ID")],
):
    task = await inquiry_text_index_task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"询码语义索引任务不存在: {task_id}")
    return InquiryTextIndexTaskStatusRes(**task)


@parts_router.post(
    "/v2/inquiry-text-index/tasks/{task_id}/cancel",
    tags=[TAG],
    summary="取消询码语义索引任务",
    response_model=InquiryTextIndexTaskStatusRes,
)
async def cancel_inquiry_text_index_task(
    task_id: Annotated[str, Path(description="询码语义索引任务 ID")],
    req: InquiryTextIndexTaskCancelReq,
):
    try:
        task = await inquiry_text_index_task_manager.cancel(task_id, req.cancel_reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"询码语义索引任务不存在: {task_id}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return InquiryTextIndexTaskStatusRes(**task)


@parts_router.post(
    "/v2/inquiry-text-index/tasks/{task_id}/retry",
    tags=[TAG],
    summary="重试询码语义索引任务",
    response_model=InquiryTextIndexTaskStartRes,
)
async def retry_inquiry_text_index_task(
    task_id: Annotated[str, Path(description="failed/cancelled/interrupted 任务 ID")],
):
    try:
        task = await inquiry_text_index_task_manager.retry(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"询码语义索引任务不存在: {task_id}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return InquiryTextIndexTaskStartRes(
        message="询码语义索引重试任务已提交",
        task_id=task["task_id"],
        task_scope=task["task_scope"],
        status=task["status"],
    )


@parts_router.post(
    "/v2/inquiry-text-index/tasks/{task_id}/failures/list",
    tags=[TAG],
    summary="分页查询询码语义索引失败明细",
    response_model=InquiryTextIndexFailureListRes,
)
async def list_inquiry_text_index_failures(
    task_id: Annotated[str, Path(description="询码语义索引任务 ID")],
    req: InquiryTextIndexFailureListReq,
):
    if await inquiry_text_index_task_manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail=f"询码语义索引任务不存在: {task_id}")
    records, total = await inquiry_text_index_task_manager.list_failures(
        task_id,
        page=req.page,
        per_page=req.per_page,
    )
    return InquiryTextIndexFailureListRes(
        total=total,
        page=req.page,
        pageSize=req.per_page,
        records=[InquiryTextIndexFailureRecord(**record) for record in records],
    )
