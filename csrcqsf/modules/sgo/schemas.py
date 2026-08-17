from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ListInqueryItem(BaseModel):
    id: str
    inquiry_num: str | None = Field(description='询码记录流水号')
    creater_org_name: str | None = Field(description='提报部门隶属名称')
    creater: str | None = Field(description='提报人名称')
    item_name: str | None = Field(description='名称描述')
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
    task_id: str = Field(..., description="进程内同步任务 ID")
    task_type: str = Field(..., description="任务类型：parts/images")
    status: str = Field(..., description="任务状态")


class SgoSyncTaskStatusRes(BaseModel):
    task_id: str
    task_type: str
    status: str = Field(..., description="pending/running/success/failed/cancelled")
    progress: int = Field(..., ge=0, le=100)
    total_items: int
    processed_items: int
    success_count: int
    fail_count: int
    created_count: int
    skipped_count: int
    synced_image_count: int
    current_item_id: str | None = None
    estimated_remaining_seconds: int | None = None
    estimated_remaining: str | None = None
    failed_item_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None
    time_created: str | None = None
    time_updated: str | None = None
