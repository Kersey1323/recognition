from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class InquiryTextIndexTaskStartRes(BaseModel):
    message: str = Field(..., description="任务提交结果")
    task_id: str = Field(..., description="询码语义索引任务 ID")
    task_scope: Literal["incremental", "full"] = Field(..., description="任务范围")
    status: str = Field(..., description="提交时状态，通常为 pending")


class InquiryTextIndexFailureRecord(BaseModel):
    history_id: str | None = Field(None, description="本地主库询码历史 ID")
    inquiry_id: str | None = Field(None, description="SGO 询码记录 ID")
    item_id: str | None = Field(None, description="关联配件 ID")
    stage: str = Field(..., description="失败阶段")
    error_type: str = Field(..., description="异常类型")
    error_message: str = Field(..., description="异常原因")
    time_created: datetime | None = Field(None, description="失败时间")

    class Config:
        json_encoders = {int: str}


class InquiryTextIndexTaskStatusRes(BaseModel):
    task_id: str
    root_task_id: str
    retry_from_task_id: str | None = None
    source_sync_task_id: str | None = None
    source_sync_task_ids: list[str] = Field(
        default_factory=list,
        description="触发或合并到当前任务的全部询码同步任务 ID",
    )
    trigger_source: Literal["sgo_inquiry_sync", "manual"] = Field(
        "manual",
        description="任务来源：询码同步自动触发或人工创建",
    )
    task_scope: Literal["incremental", "full"]
    status: str = Field(
        ...,
        description="pending/running/cancelling/success/failed/cancelled/interrupted",
    )
    progress: int = Field(0, ge=0, le=100)
    total_items: int = 0
    processed_items: int = 0
    indexed_count: int = 0
    skipped_count: int = 0
    fail_count: int = 0
    deleted_count: int = 0
    current_inquiry_id: str | None = None
    error_message: str | None = None
    cancel_reason: str | None = None
    heartbeat_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    time_created: str | None = None
    time_updated: str | None = None


class InquiryTextIndexTaskListReq(BaseModel):
    page: int = Field(1, ge=1, description="页码，从 1 开始")
    per_page: int = Field(20, ge=1, le=100, alias="pageSize", description="每页数量")
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
    ] = Field("all", description="任务状态；active 表示全部活动状态")
    task_scope: Literal["all", "incremental", "full"] = Field(
        "all",
        description="任务范围：incremental 增量，full 全量",
    )

    class Config:
        allow_population_by_field_name = True


class InquiryTextIndexTaskListRes(BaseModel):
    total: int
    page: int
    pageSize: int
    records: list[InquiryTextIndexTaskStatusRes] = Field(default_factory=list)


class InquiryTextIndexTaskCancelReq(BaseModel):
    cancel_reason: str | None = Field(None, max_length=500, description="取消原因")


class InquiryTextIndexFailureListReq(BaseModel):
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100, alias="pageSize")

    class Config:
        allow_population_by_field_name = True


class InquiryTextIndexFailureListRes(BaseModel):
    total: int
    page: int
    pageSize: int
    records: list[InquiryTextIndexFailureRecord] = Field(default_factory=list)
