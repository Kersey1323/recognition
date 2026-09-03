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

# ======================================================================
# 以下常量仅用于 Swagger 文档的 200 响应示例，供前端联调时对照字段。
# ======================================================================
_TASK_UUID = "c87a0d15-2c7c-4e77-a9c8-63b10262ee93"
_ITEM_ID = "1595255167069540352"
_ITEM_NAME = "司机室侧窗玻璃"
_ITEM_CODE = "CRH380B-04-05-01-002"
_TASK_BASE = (
    f"bfr-reconstruction-files/viewer360/{_ITEM_ID}/{_TASK_UUID}"
)

_TASK_START_NEW_EXAMPLE = {
    "task_id": _TASK_UUID,
    "item_id": _ITEM_ID,
    "item_name": _ITEM_NAME,
    "item_code": _ITEM_CODE,
    "status": "pending",
    "reused_existing": False,
}

_TASK_START_REUSED_EXAMPLE = {
    "task_id": _TASK_UUID,
    "item_id": _ITEM_ID,
    "item_name": _ITEM_NAME,
    "item_code": _ITEM_CODE,
    "status": "success",
    "reused_existing": True,
}


def _row_state_example(row_index: int, status: str, with_urls: bool = True) -> dict:
    """构造 Viewer360RowState 文档示例：with_urls=False 时图片字段为 null。"""
    base = {
        "row_index": row_index,
        "status": status,
    }
    if with_urls:
        base.update(
            {
                "image_base_url": f"{_TASK_BASE}/images/row_{row_index:02d}",
                "frame_count": 72,
                "frame_url_template": (
                    f"{_TASK_BASE}/images/row_{row_index:02d}/frame_{{frame_no}}.webp"
                ),
            }
        )
    else:
        base.update(
            {
                "image_base_url": None,
                "frame_count": None,
                "frame_url_template": None,
            }
        )
    return base


_TASK_SUCCESS_EXAMPLE = {
    "task_id": _TASK_UUID,
    "root_task_id": _TASK_UUID,
    "retry_from_task_id": None,
    "item_id": _ITEM_ID,
    "item_name": _ITEM_NAME,
    "item_code": _ITEM_CODE,
    "source_video_object": (
        "bfr-3d-videos/raw-videos/1595255167069540352/20240501/"
        "7f3a9c0e1b2c3d4e5f6a7b8c9d0e1f2a3_viewer360.mp4"
    ),
    "source_video_updated_at": "2024-05-01T10:12:00",
    "rebuild_existing": False,
    "retry_mode": "none",
    "retry_rows_json": None,
    "retry_reason": None,
    "status": "success",
    "current_stage": "completed",
    "progress": 100,
    "row_count": 4,
    "total_frames": 288,
    "processed_frames": 288,
    "reused_row_count": 0,
    "rows": [
        _row_state_example(1, "success"),
        _row_state_example(2, "success"),
        _row_state_example(3, "success"),
        _row_state_example(4, "success"),
    ],
    "manifest_url": f"/{_TASK_BASE}/manifest.json",
    "amount_x": 72,
    "amount_y": 4,
    "fingerprint": "9f2c8a1b3d4e5f60718293a4b5c6d7e8f",
    "error_message": None,
    "cancel_reason": None,
    "result_deleted_at": None,
    "heartbeat_at": "2024-05-01T10:21:00",
    "started_at": "2024-05-01T10:13:05",
    "completed_at": "2024-05-01T10:20:58",
    "time_created": "2024-05-01T10:12:30",
    "time_updated": "2024-05-01T10:20:58",
}

_TASK_RUNNING_EXAMPLE = {
    "task_id": _TASK_UUID,
    "root_task_id": _TASK_UUID,
    "retry_from_task_id": None,
    "item_id": _ITEM_ID,
    "item_name": _ITEM_NAME,
    "item_code": _ITEM_CODE,
    "source_video_object": (
        "bfr-3d-videos/raw-videos/1595255167069540352/20240501/"
        "7f3a9c0e1b2c3d4e5f6a7b8c9d0e1f2a3_viewer360.mp4"
    ),
    "source_video_updated_at": "2024-05-01T10:12:00",
    "rebuild_existing": False,
    "retry_mode": "none",
    "retry_rows_json": None,
    "retry_reason": None,
    "status": "running",
    "current_stage": "segmenting",
    "progress": 50,
    "row_count": 4,
    "total_frames": 288,
    "processed_frames": 144,
    "reused_row_count": 0,
    "rows": [
        _row_state_example(1, "success", with_urls=False),
        _row_state_example(2, "success", with_urls=False),
        _row_state_example(3, "pending", with_urls=False),
        _row_state_example(4, "pending", with_urls=False),
    ],
    "manifest_url": None,
    "amount_x": None,
    "amount_y": None,
    "fingerprint": None,
    "error_message": None,
    "cancel_reason": None,
    "result_deleted_at": None,
    "heartbeat_at": "2024-05-01T10:17:30",
    "started_at": "2024-05-01T10:13:05",
    "completed_at": None,
    "time_created": "2024-05-01T10:12:30",
    "time_updated": "2024-05-01T10:17:30",
}

_TASK_CANCELLING_EXAMPLE = {
    "task_id": _TASK_UUID,
    "root_task_id": _TASK_UUID,
    "retry_from_task_id": None,
    "item_id": _ITEM_ID,
    "item_name": _ITEM_NAME,
    "item_code": _ITEM_CODE,
    "source_video_object": (
        "bfr-3d-videos/raw-videos/1595255167069540352/20240501/"
        "7f3a9c0e1b2c3d4e5f6a7b8c9d0e1f2a3_viewer360.mp4"
    ),
    "source_video_updated_at": "2024-05-01T10:12:00",
    "rebuild_existing": False,
    "retry_mode": "none",
    "retry_rows_json": None,
    "retry_reason": None,
    "status": "cancelling",
    "current_stage": "segmenting",
    "progress": 37,
    "row_count": 4,
    "total_frames": 288,
    "processed_frames": 72,
    "reused_row_count": 0,
    "rows": [
        _row_state_example(1, "success", with_urls=False),
        _row_state_example(2, "pending", with_urls=False),
        _row_state_example(3, "pending", with_urls=False),
        _row_state_example(4, "pending", with_urls=False),
    ],
    "manifest_url": None,
    "amount_x": None,
    "amount_y": None,
    "fingerprint": None,
    "error_message": None,
    "cancel_reason": "用户取消",
    "result_deleted_at": None,
    "heartbeat_at": "2024-05-01T10:14:07",
    "started_at": "2024-05-01T10:13:05",
    "completed_at": None,
    "time_created": "2024-05-01T10:12:30",
    "time_updated": "2024-05-01T10:14:07",
}

_TASK_DELETED_EXAMPLE = {
    "task_id": _TASK_UUID,
    "root_task_id": _TASK_UUID,
    "retry_from_task_id": None,
    "item_id": _ITEM_ID,
    "item_name": _ITEM_NAME,
    "item_code": _ITEM_CODE,
    "source_video_object": (
        "bfr-3d-videos/raw-videos/1595255167069540352/20240501/"
        "7f3a9c0e1b2c3d4e5f6a7b8c9d0e1f2a3_viewer360.mp4"
    ),
    "source_video_updated_at": "2024-05-01T10:12:00",
    "rebuild_existing": False,
    "retry_mode": "none",
    "retry_rows_json": None,
    "retry_reason": None,
    "status": "success",
    "current_stage": "completed",
    "progress": 100,
    "row_count": 4,
    "total_frames": 288,
    "processed_frames": 288,
    "reused_row_count": 0,
    "rows": [
        _row_state_example(1, "success", with_urls=False),
        _row_state_example(2, "success", with_urls=False),
        _row_state_example(3, "success", with_urls=False),
        _row_state_example(4, "success", with_urls=False),
    ],
    "manifest_url": f"/{_TASK_BASE}/manifest.json",
    "amount_x": 72,
    "amount_y": 4,
    "fingerprint": "9f2c8a1b3d4e5f60718293a4b5c6d7e8f",
    "error_message": None,
    "cancel_reason": None,
    "result_deleted_at": "2024-06-10T09:30:00",
    "heartbeat_at": "2024-05-01T10:21:00",
    "started_at": "2024-05-01T10:13:05",
    "completed_at": "2024-05-01T10:20:58",
    "time_created": "2024-05-01T10:12:30",
    "time_updated": "2024-06-10T09:30:00",
}

_FAILURE_LIST_EXAMPLE = {
    "total": 1,
    "page": 1,
    "pageSize": 20,
    "records": [
        {
            "row_index": 2,
            "frame_index": None,
            "stage": "model_segmentation",
            "error_type": "Viewer360PipelineError",
            "error_message": "row_02 分割任务执行失败，请检查源视频清晰度后重试",
            "time_created": "2024-05-01T10:15:20",
        }
    ],
}

_CURRENT_RESULT_HAS_EXAMPLE = {
    "item_id": _ITEM_ID,
    "item_name": _ITEM_NAME,
    "item_code": _ITEM_CODE,
    "task_id": _TASK_UUID,
    "has_viewer360": True,
    "manifest_url": f"/{_TASK_BASE}/manifest.json",
    "amount_x": 72,
    "amount_y": 4,
    "time_updated": "2024-05-01T10:20:58",
}

_CURRENT_RESULT_EMPTY_EXAMPLE = {
    "item_id": _ITEM_ID,
    "item_name": _ITEM_NAME,
    "item_code": _ITEM_CODE,
    "task_id": None,
    "has_viewer360": False,
    "manifest_url": None,
    "amount_x": None,
    "amount_y": None,
    "time_updated": None,
}


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
    responses={
        200: {
            "description": "创建成功；新建任务排队执行，或复用配件已有结果",
            "content": {
                "application/json": {
                    "examples": {
                        "新建任务入队": {
                            "summary": "无已有结果或 rebuild_existing=true，新任务排队执行",
                            "value": _TASK_START_NEW_EXAMPLE,
                        },
                        "复用已有结果": {
                            "summary": "已有结果且 rebuild_existing=false，直接复用不创建新任务",
                            "value": _TASK_START_REUSED_EXAMPLE,
                        },
                    }
                }
            },
        },
        404: {"description": "配件不存在"},
        409: {
            "description": (
                "配件未绑定源视频 / 配件已有任务正在执行 / Viewer360 功能未启用；"
                "detail 形如 {\"message\": \"原因\", \"active_task_id\": \"冲突任务ID\"}"
            )
        },
    },
)
async def create_viewer360_task(req: Viewer360TaskCreateReq):
    """
    为指定配件创建 Viewer360 任务：后台将对配件的三维重构源视频按固定节拍分割为
    多个角度行（row_01...row_04），逐行抠图并对齐网格，发布为前端可展示的结果。

    请求体字段说明（字段含义见下方 Schema）：
    - `item_id`: 配件 ID，需为正整数字符串，且配件存在并已绑定源视频
    - `rebuild_existing`: false=配件已有结果时直接复用（不再创建任务，返回的
      `reused_existing=true`）；true=忽略已有结果，创建完整新版本排队执行

    响应字段说明（Viewer360TaskStartRes，任务详情请随后调用查询接口）：
    - `task_id`: 新任务/被复用任务的 ID，后续查询进度、取消、重试、删结果都使用它
    - `item_id`/`item_name`/`item_code`: 配件 ID、名称、编码（配件已删除时
      item_name/item_code 为 null）
    - `status`: pending=新任务排队中；success=复用了已有结果，任务实际已完成
    - `reused_existing`: 是否直接复用已有结果

    错误说明：
    - 404：配件不存在
    - 409：配件尚未绑定源视频 / 同一配件已有活动任务 / 功能未启用；
      冲突时 detail.active_task_id 给出正在执行的任务 ID，可直接用于取消
    """
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
    responses={
        200: {
            "description": "分页任务列表查询成功",
            "content": {
                "application/json": {
                    "example": {
                        "total": 1,
                        "page": 1,
                        "pageSize": 20,
                        "records": [_TASK_SUCCESS_EXAMPLE],
                    }
                }
            },
        },
    },
)
async def list_viewer360_tasks(req: Viewer360TaskListReq):
    """
    按配件、状态分页查询 Viewer360 任务。

    请求体字段说明（字段含义见下方 Schema）：
    - `page`: 页码，从 1 开始
    - `pageSize`: 每页数量，范围 1-100
    - `status`: 任务状态筛选；`all`=全部；`active`=进行中
      （pending/running/cancelling 的并集）；其余取值按精确状态匹配：
      `pending`、`running`、`cancelling`、`success`、`failed`、`cancelled`、`interrupted`
    - `item_id`: 可选；传 null 或省略则查询全部配件

    响应说明：
    - `total`: 符合筛选条件的任务总数（用于前端分页）
    - `records`: 任务数组，每个元素即完整任务对象，包含配件三字段 `item_id`（配件 ID）、
      `item_name`（配件名称）、`item_code`（配件编码；配件已删除时后两者为 null），
      便于列表页直接渲染。其余字段含义见下方 Schema；重点字段：
      - `status`/`current_stage`/`progress`: 任务状态、当前阶段与整体进度
      - `rows`: 每个角度行的状态及图片地址；只有任务成功发布且结果未删除时，
        `image_base_url`/`frame_count`/`frame_url_template` 才非 null，
        图片帧地址 = `frame_url_template` 中把 `{frame_no}` 替换成 1..amount_x 的四位帧号
      - `time_created`/`started_at`/`completed_at` 等时间字段均为 ISO8601 字符串
    """
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
    responses={
        200: {
            "description": "任务详情查询成功（示例为执行中任务，图片地址在发布后才返回）",
            "content": {
                "application/json": {
                    "example": _TASK_RUNNING_EXAMPLE,
                }
            },
        },
        404: {"description": "任务不存在"},
    },
)
async def get_viewer360_task(task_id: TaskIdPath):
    """
    查询单个 Viewer360 任务的完整状态与结果信息。

    路径参数：
    - `task_id`: 任务 ID（UUID），取自已创建任务/任务列表

    响应字段说明（完整字段清单与含义见下方 Schema，字段较多时前端可先只关注）：
    - `item_id`/`item_name`/`item_code`: 配件 ID、名称、编码（配件已删除时
      item_name/item_code 为 null）
    - `status`/`current_stage`/`progress`: 状态机三要素；任务状态取值：
      pending（排队）→ running（执行）→ success / failed / cancelled；
      running 期间用户取消会先进入 cancelling，后台停止后转 cancelled；
      服务重启导致执行中断时状态为 interrupted，可用重试接口恢复
    - `current_stage`: 执行到哪一步（downloading_video/extracting/segmenting/...），
      前端可在 running 时轮询该接口刷新进度条
    - `rows`: 角度行明细；任务发布后每行提供帧图片目录与 URL 模板
      （替换 `{frame_no}` 为四位帧号即可拼出 frame_0001.webp 等图片地址）
    - `manifest_url`: 结果 manifest 地址；任务未发布/被取消/失败时为 null
    - `error_message`/`cancel_reason`: failed 时看 error_message，cancelled 时看 cancel_reason
    """
    task = await viewer360_task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Viewer360 任务不存在: {task_id}")
    return Viewer360TaskStatusRes(**task)


@parts_router.post(
    "/v2/viewer360/tasks/{task_id}/failures/list",
    tags=[TAG],
    summary="分页查询 Viewer360 失败明细",
    response_model=Viewer360FailureListRes,
    responses={
        200: {
            "description": "失败明细查询成功（任务成功或无失败记录时 records 为空数组）",
            "content": {
                "application/json": {
                    "example": _FAILURE_LIST_EXAMPLE,
                }
            },
        },
        404: {"description": "任务不存在"},
    },
)
async def list_viewer360_failures(
    task_id: TaskIdPath,
    req: Viewer360FailureListReq,
):
    """
    查询指定任务执行过程中记录的分段失败明细，用于定位失败发生在哪个角度/环节。

    请求体字段说明（字段含义见下方 Schema）：
    - `page`: 页码，从 1 开始
    - `pageSize`: 每页数量，范围 1-100

    响应字段说明（见下方 Schema）：
    - `records[].row_index`: 失败关联的角度行（1-based）；与具体行无关时为 null
    - `records[].stage`: 失败环节，如 downloading_video/extracting/segmenting/
      model_segmentation/validating/publishing 等
    - `records[].error_type`/`error_message`: 异常类型与错误详情
    - `records[].time_created`: 失败发生时间（ISO8601）
    """
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
    responses={
        200: {
            "description": "取消成功（示例：running 任务取消后进入 cancelling）",
            "content": {
                "application/json": {
                    "example": _TASK_CANCELLING_EXAMPLE,
                }
            },
        },
        404: {"description": "任务不存在"},
        409: {
            "description": (
                "任务已处于终态（success/failed/interrupted）不可取消；"
                "detail 形如 {\"message\": \"原因\", \"active_task_id\": \"任务ID\"}"
            )
        },
    },
)
async def cancel_viewer360_task(
    task_id: TaskIdPath,
    req: Viewer360CancelReq,
):
    """
    取消排队中或执行中的 Viewer360 任务。

    请求体字段说明（字段含义见下方 Schema）：
    - `cancel_reason`: 可选，取消原因（最长 500 字），将记录到任务的
      `cancel_reason` 字段便于排查，前端取消弹窗可收集用户输入

    行为说明：
    - 任务为 pending（排队中）：直接置为 cancelled（终态）
    - 任务为 running（执行中）：先置为 cancelling，后台收到信号停止处理并
      删除未发布的部分结果后转为 cancelled；前端可用轮询观察到状态变化
    - 任务已为 cancelling/cancelled：幂等返回当前状态，不会重复处理
    - 任务为 success/failed/interrupted 等终态：返回 409 不可取消

    响应字段说明：完整任务对象（字段同"查询任务详情"），取消场景重点关注
    `status`（cancelling/cancelled）与 `cancel_reason`。
    """
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
    responses={
        200: {
            "description": "重试成功，任务重新排队执行（响应示例同创建任务）",
            "content": {
                "application/json": {
                    "example": _TASK_START_NEW_EXAMPLE,
                }
            },
        },
        404: {"description": "任务不存在"},
        409: {
            "description": (
                "当前任务状态不允许该重试模式 / 配件已有活动任务 / 功能未启用；"
                "detail 形如 {\"message\": \"原因\", \"active_task_id\": \"冲突任务ID\"}"
            )
        },
    },
)
async def retry_viewer360_task(
    task_id: TaskIdPath,
    req: Viewer360RetryReq,
):
    """
    对指定任务执行恢复（resume）或指定角度重做（resegment_rows）。
    两种模式都复用原 task_id，不产生新任务，前端始终跟踪同一条记录即可。

    请求体字段说明（字段含义见下方 Schema）：
    - `retry_mode`: 重试方式
      - `resume`: 断点恢复，仅适用于 failed/cancelled/interrupted 任务，
        从最近成功阶段继续执行
      - `resegment_rows`: 质量重做，仅适用于结果仍存在（未删除）的 success 任务，
        只重新分割传入的角度行，其余行继续复用旧结果
    - `row_indexes`: 需重新分割的 1-based 角度行号列表，1->row_01、2->row_02、
      3->row_03、4->row_04；仅 resegment_rows 使用，resume 时传 null 或省略
    - `reason`: 可选重试原因（最长 500 字），记录到 `retry_reason` 字段

    响应字段说明：同"创建任务"接口，返回任务摘要：
    - `task_id`: 原任务 ID（保持不变）
    - `item_id`/`item_name`/`item_code`: 配件 ID、名称、编码（配件已删除时
      item_name/item_code 为 null）
    - `status`: 重试后回到 pending（排队中）
    - `reused_existing`: 恒为 false（resegment_rows 复用的行数在
      `reused_row_count` 字段体现，可稍后查询任务详情）

    错误说明：
    - 404：任务不存在
    - 409：状态不允许该模式（如 resume 一个 success 任务）、
      同一配件已有活动任务、功能未启用
    """
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
    responses={
        200: {
            "description": "查询成功；示例给出有结果与无结果两种形态",
            "content": {
                "application/json": {
                    "examples": {
                        "配件已有结果": {
                            "summary": "配件存在可展示的 Viewer360 结果",
                            "value": _CURRENT_RESULT_HAS_EXAMPLE,
                        },
                        "配件暂无结果": {
                            "summary": "配件从未生成过结果或结果已被删除",
                            "value": _CURRENT_RESULT_EMPTY_EXAMPLE,
                        },
                    }
                }
            },
        },
    },
)
async def get_viewer360_current_result(item_id: ItemIdPath):
    """
    查询某个配件当前最新可用的 Viewer360 结果（每个配件同时只保留一个有效结果）。

    路径参数：
    - `item_id`: 配件 ID（正整数字符串）

    响应字段说明（见下方 Schema）：
    - `item_id`/`item_name`/`item_code`: 配件 ID、名称、编码（与是否有结果无关，均实时返回；
      配件已删除时 item_name/item_code 为 null）
    - `has_viewer360`: false 表示无可用结果（此时 task_id/manifest_url 等均为
      null），前端应展示"暂无可展示结果"状态
    - `manifest_url`: 结果 manifest 的公开访问 URL（以 / 开头，需拼部署域名前缀）
    - `amount_x`/`amount_y`: 网格规模；`amount_x` 同时是每个角度的图片帧数
    """
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
    responses={
        200: {
            "description": "删除成功（示例：原成功任务的结果已删除）",
            "content": {
                "application/json": {
                    "example": _TASK_DELETED_EXAMPLE,
                }
            },
        },
        404: {"description": "任务不存在"},
        409: {
            "description": (
                "活动任务（pending/running/cancelling）不能删除结果，请先取消；"
                "detail 形如 {\"message\": \"原因\", \"active_task_id\": \"任务ID\"}"
            )
        },
    },
)
async def delete_viewer360_result(task_id: TaskIdPath):
    """
    删除指定任务发布的三维展示结果（OSS 文件与当前结果指针）。
    删除后该任务记录的 result_deleted_at 被写入；若该任务此前是配件的当前结果，
    配件将回到"无结果"状态（查询当前结果接口 has_viewer360=false）。

    路径参数：
    - `task_id`: 任务 ID（UUID）

    行为说明：
    - 任务处于 pending/running/cancelling（活动）时返回 409，需先取消任务
    - 结果已被删除过时幂等返回，不报错

    响应字段说明：完整任务对象（字段同"查询任务详情"），删除场景重点关注：
    - `result_deleted_at`: 非 null 即表示该任务结果已删除
    - `rows[].image_base_url`/`frame_url_template`: 删除后为 null
    - `manifest_url`: 指向的 OSS 对象已被删除，前端不应再使用该地址展示
    """
    try:
        task = await viewer360_task_manager.delete_result(task_id)
    except (Viewer360NotFoundError, Viewer360ConflictError) as exc:
        _raise_business_error(exc)
    return Viewer360TaskStatusRes(**task)
