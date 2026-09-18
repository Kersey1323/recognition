from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, validator


class ListInqueryItem(BaseModel):
    id: str
    inquiry_num: str | None = Field(description='询码记录流水号')
    creater_org_name: str | None = Field(description='提报部门隶属名称')
    creater: str | None = Field(description='提报人名称')
    item_name: str | None = Field(description='名称描述')
    return_item_code: str | None = Field(
        default=None,
        description='甲方闭环时人工确认的配件编码；尚未确认时为 null',
    )
    return_item_name: str | None = Field(
        default=None,
        description='甲方闭环时人工确认的配件名称；尚未确认时为 null',
    )
    subordinate_component: str | None = Field(description='隶属部件')
    train_no: str | None = Field(description='列号')
    car_num: str | None = Field(description='车厢号')
    vehicle: str | None = Field(description='车型')
    submission_date: str | None = Field(description='提报部门隶属名称')
    remark: str | None = Field(description='提报备注')
    current_status: str | None = Field(
        description='CREATE:技术部待回复\r\nCONFIRMAUDIT:编码确认审核中\r\nFINISH:结束（闭环）\r\nBACKAUDIT:驳回审核中\r\nSUPPLIERRES:供应商处理中\r\nBACK:技术部驳回\r\nGREEN:绿色通道\r\nREGING:编码注册中'
    )
    supplier_name: str | None = Field(description='需求供应商名')
    supplier_code: str | None = Field(description='需求供应商')
    nameplate_photos: str | None = Field(description='铭牌照片')
    detailed_photos: str | None = Field(description="远近照片")
    detailed_photos_urls: list[str] = []
    nameplate_photos_urls: list[str] = []


class ImageSourceType(str, Enum):
    INQUERY = "INQUERY"
    BASEINFO = 'BASEINFO'
    CREATEBYSELF = 'CREATEBYSELF'


class SegmentStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class SgoSyncTaskStartRes(BaseModel):
    message: str = Field(..., description="任务提交结果")
    task_id: str = Field(..., description="持久化同步任务 ID")
    task_type: str = Field(
        ...,
        description="任务类型：parts 配件、images 图片、inquiry-history 询码历史",
    )
    status: str = Field(..., description="任务提交时状态，通常为 pending")


class SgoA9CleanupItem(BaseModel):
    item_id: str
    item_code: str
    item_name: str | None = None


class SgoA9CleanupPreviewRes(BaseModel):
    source_a9_code_count: int = Field(..., ge=0, description="甲方 A9 板块编码数")
    shared_code_count: int = Field(..., ge=0, description="同时存在于 A1/A3/A5 的编码数")
    exclusive_code_count: int = Field(..., ge=0, description="仅存在于 A9 的编码数")
    local_item_count: int = Field(..., ge=0, description="已进入 item_info 的独占 A9 配件数")
    sample_items: list[SgoA9CleanupItem] = Field(
        default_factory=list,
        description="待清理配件样例，最多返回 100 条",
    )


class SgoA9CleanupExecuteReq(BaseModel):
    confirmation: Literal["DELETE_A9_DEMO_DATA"] = Field(
        ...,
        description="固定确认词，防止误触发演示数据清理",
    )


class SgoSyncFailureDetail(BaseModel):
    item_id: str = Field(..., description="同步失败的配件内部 ID 或源数据 ID")
    item_code: str | None = Field(None, description="同步失败的甲方配件编码")
    item_name: str | None = Field(None, description="同步失败的甲方配件名称")
    error_code: str | None = Field(None, description="稳定业务错误码；旧数据迁移后可用")
    stage: str = Field(
        ...,
        description=(
            "失败阶段：source_validation 源数据校验，base_images 基础图，"
            "inquiry_images 询码图"
        ),
    )
    error_type: str = Field(..., description="异常类型")
    error_message: str = Field(..., description="具体异常原因")


class SgoSyncFailureGroup(BaseModel):
    error_code: str = Field(..., description="用于查看该类错误明细的稳定筛选码")
    stage: str = Field(..., description="失败阶段")
    error_type: str = Field(..., description="异常类型")
    error_message: str = Field(..., description="该类错误的一条示例原因，仅用于展示")
    count: int = Field(..., ge=1, description="该类失败的配件数量")


class SgoSyncTaskStatusRes(BaseModel):
    task_id: str = Field(..., description="当前任务 ID")
    root_task_id: str = Field(..., description="整条重试链首次任务 ID")
    retry_from_task_id: str | None = Field(None, description="直接来源任务 ID")
    task_type: str = Field(
        ...,
        description="parts 配件、images 图片、inquiry-history 询码历史",
    )
    task_params_json: dict = Field(default_factory=dict, description="创建任务时的原始参数")
    status: str = Field(
        ...,
        description=(
            "pending/running/cancelling/success/failed/cancelled/interrupted"
        ),
    )
    progress: int = Field(..., ge=0, le=100, description="任务进度百分比")
    total_items: int = Field(..., description="本次任务处理总数")
    processed_items: int = Field(..., description="已处理数量")
    success_count: int = Field(..., description="成功同步数量")
    fail_count: int = Field(..., description="无法同步数量")
    created_count: int = Field(..., description="主库新增数量")
    skipped_count: int = Field(..., description="已存在并跳过数量")
    synced_image_count: int = Field(..., description="成功同步图片数量")
    updated_metadata_count: int = Field(0, description="本次更新的配件规格/材质数量")
    synced_supplier_count: int = Field(0, description="本次新增或更新的供应商关系数量")
    deleted_supplier_count: int = Field(0, description="本次清理的失效供应商关系数量")
    unmatched_supplier_count: int = Field(0, description="尚未关联本地配件的供应商关系数量")
    hierarchy_total_count: int = Field(0, description="SGO 层级源记录总数")
    synced_hierarchy_count: int = Field(0, description="本次新增或更新的层级关系数量")
    deleted_hierarchy_count: int = Field(0, description="本次清理的失效层级关系数量")
    unresolved_vehicle_count: int = Field(0, description="尚未映射车型名称的层级关系数量")
    invalid_hierarchy_count: int = Field(0, description="自环或源父节点缺失等异常层级关系数量")
    current_item_id: str | None = Field(None, description="当前处理的配件 ID")
    estimated_remaining_seconds: int | None = Field(None, description="预计剩余秒数")
    estimated_remaining: str | None = Field(None, description="可直接展示的预计剩余时间")
    failed_item_ids: list[str] = Field(
        default_factory=list,
        description="兼容字段，仅返回前 20 条失败记录的配件 ID",
    )
    failure_details: list[SgoSyncFailureDetail] = Field(
        default_factory=list,
        description="兼容字段，仅返回前 20 条；完整失败明细请调用分页接口",
    )
    failure_groups: list[SgoSyncFailureGroup] = Field(
        default_factory=list,
        description="按稳定业务错误码聚合的失败摘要；查看详情请传 error_code",
    )
    error_message: str | None = Field(None, description="任务异常或业务失败摘要")
    cancel_reason: str | None = Field(None, description="任务取消原因")
    semantic_index_task_id: str | None = Field(
        None,
        description="询码同步后创建的语义索引任务 ID；其他同步类型为空",
    )
    semantic_index_triggered: bool = Field(
        False,
        description="本次询码同步是否创建或合并到 BGE 增量索引任务",
    )
    semantic_index_warning: str | None = Field(
        None,
        description="语义索引任务创建失败原因；不影响询码同步成功状态",
    )
    heartbeat_at: str | None = Field(None, description="最近一次进度持久化时间")
    started_at: str | None = Field(None, description="开始时间")
    completed_at: str | None = Field(None, description="结束时间")
    time_created: str | None = Field(None, description="任务创建时间")
    time_updated: str | None = Field(None, description="任务更新时间")


class SgoSyncTaskListReq(BaseModel):
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
    ] = Field("all", description="任务状态筛选，active 表示所有活动状态")
    task_type: Literal["all", "parts", "images", "inquiry-history", "parts-cleanup"] = Field(
        "all",
        description="任务类型筛选",
    )

    class Config:
        allow_population_by_field_name = True


class SgoSyncTaskListRes(BaseModel):
    total: int = Field(..., description="任务总数")
    page: int = Field(..., description="当前页码")
    pageSize: int = Field(..., description="每页数量")
    records: list[SgoSyncTaskStatusRes] = Field(default_factory=list)


class SgoSyncTaskStatisticsReq(BaseModel):
    type: Literal["parts", "images", "inquiry-history", "parts-cleanup"] = Field(
        ..., description="同步页签类型：配件、图片或询码历史"
    )


class SgoSyncTaskStatisticsRes(BaseModel):
    task_success_rate: int = Field(..., description="任务成功率，按全部任务计算的整数百分比")
    total_tasks: int = Field(..., description="任务总数，包含取消和中断")
    successful_tasks: int = Field(..., description="成功任务数")
    failed_tasks: int = Field(..., description="失败任务数")
    active_tasks: int = Field(..., description="执行中任务数，包含等待、执行和取消中")


class SgoSyncTaskCancelReq(BaseModel):
    cancel_reason: str | None = Field(None, max_length=500, description="可选取消原因")


class SgoSyncTaskDeleteReq(BaseModel):
    task_id_list: list[str] = Field(
        ...,
        min_items=1,
        max_items=100,
        description="待删除的已结束同步任务 ID，最多 100 个",
    )

    @validator("task_id_list")
    def normalize_task_ids(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(str(value).strip() for value in values))
        if not normalized or any(not value for value in normalized):
            raise ValueError("任务 ID 不能为空")
        return normalized


class SgoSyncTaskDeleteRes(BaseModel):
    requested_count: int = Field(..., ge=1, description="请求删除的去重任务数")
    deleted_task_count: int = Field(..., ge=0, description="实际删除的任务数")
    deleted_failure_count: int = Field(..., ge=0, description="同步删除的失败明细数")
    missing_task_ids: list[str] = Field(default_factory=list, description="删除前已不存在的任务 ID")


class SgoSyncFailureListReq(BaseModel):
    page: int = Field(1, ge=1, description="页码，从 1 开始")
    per_page: int = Field(20, ge=1, le=100, alias="pageSize", description="每页数量")
    error_code: str | None = Field(None, description="按聚合返回的稳定业务错误码筛选")
    stage: str | None = Field(None, description="按失败阶段精确筛选")
    error_type: str | None = Field(None, description="按异常类型精确筛选")
    error_message: str | None = Field(None, description="按具体失败原因精确筛选")

    class Config:
        allow_population_by_field_name = True


class SgoSyncFailureRecord(SgoSyncFailureDetail):
    time_created: datetime | None = Field(None, description="失败记录时间")


class SgoSyncFailureListRes(BaseModel):
    total: int = Field(..., description="失败记录总数")
    page: int = Field(..., description="当前页码")
    pageSize: int = Field(..., description="每页数量")
    records: list[SgoSyncFailureRecord] = Field(default_factory=list)
