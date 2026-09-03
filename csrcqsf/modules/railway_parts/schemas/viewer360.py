"""Viewer360 任务管理接口的严格请求与稳定响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, validator


class _StrictRequest(BaseModel):
    class Config:
        extra = "forbid"
        allow_population_by_field_name = True


class Viewer360TaskCreateReq(_StrictRequest):
    item_id: str = Field(..., description="配件 ID")
    rebuild_existing: bool = Field(
        False,
        description="false=已有结果时直接复用；true=忽略已有结果并创建完整新版本",
    )

    @validator("item_id")
    def validate_item_id(cls, value: str) -> str:
        if not value.isdigit() or int(value) <= 0:
            raise ValueError("item_id must be a positive integer string")
        return value

    class Config(_StrictRequest.Config):
        schema_extra = {
            "example": {
                "item_id": "1595255167069540352",
                "rebuild_existing": False,
            }
        }


class Viewer360TaskStartRes(BaseModel):
    task_id: str = Field(..., description="任务 ID（UUID）；后续查询、取消、删除、重试均使用该 ID")
    item_id: str = Field(..., description="配件 ID")
    item_name: str | None = Field(
        None,
        description="配件名称；配件已删除或查询不到时为 null",
    )
    item_code: str | None = Field(
        None,
        description="配件编码；配件已删除或查询不到时为 null",
    )
    status: str = Field(
        ...,
        description=(
            "任务状态：pending=排队中、running=执行中、cancelling=取消中、success=成功、"
            "failed=失败、cancelled=已取消、interrupted=服务中断；"
            "新建任务为 pending，直接复用已有结果时为 success"
        ),
    )
    reused_existing: bool = Field(
        False,
        description="true=直接复用了配件已有的 Viewer360 结果，未创建新任务",
    )


class Viewer360RowState(BaseModel):
    row_index: int = Field(..., description="1-based 角度行号，1 对应 row_01、2 对应 row_02")
    status: str = Field(
        ...,
        description=(
            "该角度行状态：pending=待处理、segmenting=分割处理中、success=成功、"
            "failed=失败、reused=本次执行复用旧结果未重新处理、"
            "fallback=分割校验未通过，本行使用原始帧兜底"
        ),
    )
    image_base_url: str | None = Field(
        None,
        description=(
            "不带开头斜杠的角度 WebP 图片相对目录；任务尚未发布或结果已删除时为空"
        ),
    )
    frame_count: int | None = Field(
        None,
        description="该角度可加载的图片帧数",
    )
    frame_url_template: str | None = Field(
        None,
        description=(
            "不带开头斜杠的帧图片 URL 模板；将 frame_no 替换为从 0001 开始的四位帧号"
        ),
    )

    class Config:
        extra = "allow"


class Viewer360TaskStatusRes(BaseModel):
    task_id: str = Field(..., description="任务 ID（UUID）")
    root_task_id: str | None = Field(
        None,
        description="任务族根任务 ID；重试沿用原 task_id 执行，通常与 task_id 相同",
    )
    retry_from_task_id: str | None = Field(
        None,
        description="重试来源任务 ID；非重试产生的任务为 null",
    )
    item_id: str = Field(..., description="配件 ID")
    item_name: str | None = Field(
        None,
        description="配件名称（实时取自配件表）；配件已删除或查询不到时为 null",
    )
    item_code: str | None = Field(
        None,
        description="配件编码（实时取自配件表）；配件已删除或查询不到时为 null",
    )
    source_video_object: str | None = Field(
        None,
        description="源视频在 MinIO 的存储位置（桶名/对象名），如 bfr-3d-videos/raw-videos/...",
    )
    source_video_updated_at: str | None = Field(
        None,
        description="源视频最后更新时间（ISO8601）",
    )
    rebuild_existing: bool = Field(
        False,
        description="创建任务时是否忽略已有结果强制重建",
    )
    retry_mode: str = Field(
        "none",
        description=(
            "重试模式：none=原始任务、resume=断点恢复继续执行、"
            "resegment_rows=对成功结果中指定角度重新分割"
        ),
    )
    retry_rows_json: list[int] | None = Field(
        None,
        description="resegment_rows 模式待重做的 1-based 角度行号列表；其他模式为 null",
    )
    retry_reason: str | None = Field(None, description="重试原因")
    status: str = Field(
        ...,
        description=(
            "任务状态：pending=排队中、running=执行中、cancelling=取消中、success=成功、"
            "failed=失败、cancelled=已取消、interrupted=服务中断"
        ),
    )
    current_stage: str | None = Field(
        None,
        description=(
            "当前执行阶段：preparing、downloading_video、extracting、segmenting、"
            "postprocessing、validating、publishing、cleanup；任务成功发布后为 completed，"
            "失败/取消/中断时保留最后一次上报的阶段，尚未开始为 null"
        ),
    )
    progress: int = Field(0, ge=0, le=100, description="整体进度百分比 0-100")
    row_count: int = Field(0, description="角度行总数（配置值，一般为 4）")
    total_frames: int = Field(0, description="本次执行需要处理的帧总数")
    processed_frames: int = Field(0, description="已处理完成的帧数")
    reused_row_count: int = Field(
        0,
        description="复用已有断点/旧结果、本次未重新处理的角度行数",
    )
    rows: list[Viewer360RowState] = Field(
        default_factory=list,
        description=(
            "各角度行状态；任务成功发布且结果未删除时，每行带图片访问信息，"
            "否则 image_base_url/frame_count/frame_url_template 为 null"
        ),
    )
    manifest_url: str | None = Field(
        None,
        description="结果 manifest 文件访问 URL（以 / 开头，需拼部署前缀）；未发布为 null",
    )
    amount_x: int | None = Field(
        None,
        description="每个角度行的图片帧数；frame_url_template 中 frame_no 取 1..amount_x",
    )
    amount_y: int | None = Field(
        None,
        description="有效角度行数（发布结果时与 row_count 相同）",
    )
    fingerprint: str | None = Field(
        None,
        description="结果数据指纹，用于断点复用与版本比对",
    )
    render_mode: Literal["segmented", "original"] | None = Field(
        None,
        description="结果渲染模式：segmented=透明分割图，original=原始帧兜底；未发布为 null",
    )
    fallback_reason: str | None = Field(
        None,
        description="切换为 original 的原因；正常透明分割结果或未发布时为 null",
    )
    error_message: str | None = Field(None, description="任务失败原因")
    cancel_reason: str | None = Field(None, description="取消原因")
    result_deleted_at: str | None = Field(
        None,
        description="结果删除时间（ISO8601）；null 表示结果仍存在",
    )
    heartbeat_at: str | None = Field(
        None,
        description="最近一次心跳/进度更新时间（ISO8601）",
    )
    started_at: str | None = Field(None, description="任务开始执行时间（ISO8601）")
    completed_at: str | None = Field(
        None,
        description="任务结束时间（ISO8601），成功/失败/取消/中断时写入",
    )
    time_created: str | None = Field(None, description="任务创建时间（ISO8601）")
    time_updated: str | None = Field(None, description="任务记录最后更新时间（ISO8601）")


class Viewer360TaskListReq(_StrictRequest):
    page: int = Field(1, ge=1, description="页码，从 1 开始")
    per_page: int = Field(
        20,
        ge=1,
        le=100,
        alias="pageSize",
        description="每页数量，范围 1-100",
    )
    status: Literal[
        "all",
        "active",
        "pending",
        "running",
        "cancelling",
        "success",
        "failed",
        "cancelled",
        "interrupted",
    ] = Field(
        "all",
        description="任务状态筛选；all=全部，active=所有进行中状态，其余值为精确状态",
    )
    item_id: str | None = Field(None, description="可选配件 ID；为空时查询全部配件")

    class Config(_StrictRequest.Config):
        schema_extra = {
            "example": {
                "page": 1,
                "pageSize": 20,
                "status": "all",
                "item_id": None,
            }
        }


class Viewer360TaskListRes(BaseModel):
    total: int = Field(..., description="符合筛选条件的任务总数")
    page: int = Field(..., description="当前页码，从 1 开始")
    pageSize: int = Field(..., description="本次返回的每页数量")
    records: list[Viewer360TaskStatusRes] = Field(
        default_factory=list,
        description=(
            "任务列表；每个元素是完整的任务详情对象，含 item_id、item_name（配件名称）、"
            "item_code（配件编码）等字段"
        ),
    )


class Viewer360StatisticsReq(_StrictRequest):
    """Viewer360 统计目前不需要筛选条件。"""

    class Config(_StrictRequest.Config):
        schema_extra = {"example": {}}


class Viewer360StatisticsRes(BaseModel):
    total_tasks: int = Field(default=0, description="Viewer360 任务总数")
    running_tasks: int = Field(default=0, description="排队、运行或取消中的任务数")
    success_tasks: int = Field(default=0, description="成功任务数")
    failed_tasks: int = Field(default=0, description="失败或服务中断的任务数")
    cancelled_tasks: int = Field(default=0, description="已取消任务数")
    success_rate: float = Field(default=0, description="成功率，仅按成功+失败计算")
    avg_success_elapsed_sec: float | None = Field(
        default=None,
        description="成功任务平均耗时，单位秒",
    )
    min_success_elapsed_sec: float | None = Field(
        default=None,
        description="成功任务最短耗时，单位秒",
    )
    max_success_elapsed_sec: float | None = Field(
        default=None,
        description="成功任务最长耗时，单位秒",
    )


class Viewer360FailureListReq(_StrictRequest):
    page: int = Field(1, ge=1, description="失败明细页码，从 1 开始")
    per_page: int = Field(
        20,
        ge=1,
        le=100,
        alias="pageSize",
        description="每页失败明细数量，范围 1-100",
    )

    class Config(_StrictRequest.Config):
        schema_extra = {"example": {"page": 1, "pageSize": 20}}


class Viewer360FailureRecord(BaseModel):
    row_index: int | None = Field(
        None,
        description="失败关联的角度行号（1-based）；与具体行无关的失败为 null",
    )
    frame_index: int | None = Field(
        None,
        description="失败关联的帧号；当前实现固定为 null，保留字段",
    )
    stage: str = Field(
        ...,
        description=(
            "失败阶段：source_video、preparing、downloading_video、extracting、"
            "segmenting、model_segmentation、postprocess、validating、publishing、"
            "cleanup 等；无法归类时为 pipeline"
        ),
    )
    error_type: str = Field(..., description="异常类型名称，如 Viewer360PipelineError")
    error_message: str = Field(..., description="错误详情")
    time_created: str | None = Field(None, description="失败记录创建时间（ISO8601）")


class Viewer360FailureListRes(BaseModel):
    total: int = Field(..., description="失败记录总数")
    page: int = Field(..., description="当前页码，从 1 开始")
    pageSize: int = Field(..., description="本次返回的每页数量")
    records: list[Viewer360FailureRecord] = Field(
        default_factory=list,
        description="失败明细列表",
    )


class Viewer360CancelReq(_StrictRequest):
    cancel_reason: str | None = Field(
        None,
        max_length=500,
        description="可选取消原因，用于后续问题排查",
    )

    class Config(_StrictRequest.Config):
        schema_extra = {"example": {"cancel_reason": "用户取消"}}


class Viewer360RetryReq(_StrictRequest):
    retry_mode: Literal["resume", "resegment_rows"] = Field(
        ...,
        description=(
            "重试方式（复用原 task_id）：resume=继续 failed/cancelled/interrupted "
            "任务并复用有效断点；resegment_rows=对成功结果中的指定角度重新分割"
        ),
    )
    row_indexes: list[int] | None = Field(
        None,
        description=(
            "需要重新分割的 1-based 角度行号，仅 resegment_rows 使用；"
            "resume 请传 null 或省略"
        ),
    )
    reason: str | None = Field(
        None,
        max_length=500,
        description="可选重试原因，将记录到原任务的本次执行中",
    )

    @validator("row_indexes")
    def validate_rows(cls, value):
        if value is not None and any(index < 1 for index in value):
            raise ValueError("row_indexes must contain positive 1-based values")
        return value

    class Config(_StrictRequest.Config):
        schema_extra = {
            "example": {
                "retry_mode": "resume",
                "row_indexes": None,
                "reason": "复用断点重新执行 Viewer360 任务",
            }
        }


class Viewer360CurrentResultRes(BaseModel):
    item_id: str = Field(..., description="配件 ID")
    item_name: str | None = Field(
        None,
        description="配件名称；配件已删除或查询不到时为 null",
    )
    item_code: str | None = Field(
        None,
        description="配件编码；配件已删除或查询不到时为 null",
    )
    task_id: str | None = Field(
        None,
        description="产生当前结果的任务 ID；无结果时为 null",
    )
    has_viewer360: bool = Field(
        ...,
        description="该配件当前是否存在可用的 Viewer360 结果",
    )
    manifest_url: str | None = Field(
        None,
        description="结果 manifest 文件公开访问 URL；无结果时为 null",
    )
    amount_x: int | None = Field(
        None,
        description="每个角度行的图片帧数（帧号取 1..amount_x）",
    )
    amount_y: int | None = Field(
        None,
        description="有效角度行数",
    )
    time_updated: str | None = Field(
        None,
        description="结果最近更新时间（ISO8601）；无结果时为 null",
    )
