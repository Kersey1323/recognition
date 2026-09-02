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
    task_id: str
    item_id: str
    status: str
    reused_existing: bool = False


class Viewer360RowState(BaseModel):
    row_index: int
    status: str
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
    task_id: str
    root_task_id: str | None = None
    retry_from_task_id: str | None = None
    item_id: str
    source_video_object: str | None = None
    source_video_updated_at: str | None = None
    rebuild_existing: bool = False
    retry_mode: str = "none"
    retry_rows_json: list[int] | None = None
    retry_reason: str | None = None
    status: str
    current_stage: str | None = None
    progress: int = Field(0, ge=0, le=100)
    row_count: int = 0
    total_frames: int = 0
    processed_frames: int = 0
    reused_row_count: int = 0
    rows: list[Viewer360RowState] = Field(default_factory=list)
    manifest_url: str | None = None
    amount_x: int | None = None
    amount_y: int | None = None
    fingerprint: str | None = None
    error_message: str | None = None
    cancel_reason: str | None = None
    result_deleted_at: str | None = None
    heartbeat_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    time_created: str | None = None
    time_updated: str | None = None


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
    total: int
    page: int
    pageSize: int
    records: list[Viewer360TaskStatusRes] = Field(default_factory=list)


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
    row_index: int | None = None
    frame_index: int | None = None
    stage: str
    error_type: str
    error_message: str
    time_created: str | None = None


class Viewer360FailureListRes(BaseModel):
    total: int
    page: int
    pageSize: int
    records: list[Viewer360FailureRecord] = Field(default_factory=list)


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
        description="可选重试原因，将记录到新任务中",
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
    item_id: str
    task_id: str | None = None
    has_viewer360: bool
    manifest_url: str | None = None
    amount_x: int | None = None
    amount_y: int | None = None
    time_updated: str | None = None
