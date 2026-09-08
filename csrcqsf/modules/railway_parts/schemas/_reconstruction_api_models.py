"""
三维重构 API 模型
"""
from typing import Literal, Optional

from bfrcommon.api_models import PageReq
from pydantic import BaseModel, Field, validator


class ReconstructionTrainReq(BaseModel):
    item_id: str = Field(..., description='配件ID，建议按字符串传递以避免前端精度丢失')
    scene: str = Field(..., description='场景名称（data目录下的文件夹名）')
    iterations: int = Field(default=30000, description='训练迭代次数')
    output_name: Optional[str] = Field(None, description='输出名称（可选）')


class ReconstructionVideoReq(BaseModel):
    item_id: str = Field(..., description='配件ID，建议按字符串传递以避免前端精度丢失')
    iterations: int = Field(..., description='3DGS训练迭代次数')

    class Config:
        extra = "forbid"


class ReconstructionTaskRes(BaseModel):
    task_id: str = Field(..., description='任务ID')
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    mode: str = Field(..., description='模式: train/video')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionVideoUploadRes(BaseModel):
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    bucket: str = Field(..., description='MinIO bucket')
    object_name: str = Field(..., description='MinIO object name')
    video_path: str = Field(..., description='可直接传给 /v2/reconstruct/video 的视频路径')
    size: int = Field(..., description='文件大小，单位字节')
    content_type: str = Field(default='', description='文件类型')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionSourceVideoRes(BaseModel):
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    item_name: str = Field(..., description='配件名称')
    item_code: str = Field(..., description='配件编码')
    height: Optional[float] = Field(None, description='高度')
    length: Optional[float] = Field(None, description='长度')
    width: Optional[float] = Field(None, description='宽度')
    weight: Optional[float] = Field(None, description='重量')
    video_path: Optional[str] = Field(None, description='MinIO视频路径，格式为 bucket/object')
    filename: Optional[str] = Field(None, description='原始文件名')
    size: Optional[int] = Field(None, description='文件大小，单位字节')
    content_type: Optional[str] = Field(None, description='文件类型')
    source_video_updated_at: Optional[str] = Field(None, description='原始视频更新时间')
    message: Optional[str] = Field(None, description='消息')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionSourceVideoListReq(PageReq):
    pass


class ReconstructionSourceVideoListRes(BaseModel):
    total: int = Field(..., description='总数')
    page: int = Field(..., description='当前页码')
    pageSize: int = Field(..., description='每页数量')
    records: list[ReconstructionSourceVideoRes] = Field(default_factory=list, description='原始视频记录')


class ReconstructionSourceVideoMessageRes(BaseModel):
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionMultipartUploadUrlItem(BaseModel):
    part_number: int = Field(..., description="分片编号，从1开始")
    url: str = Field(..., description="完整预签名上传URL")
    expires_at: str | None = Field(default=None, description="URL过期时间")


class ReconstructionMultipartUploadedPartItem(BaseModel):
    part_number: int = Field(..., description="已上传分片编号")
    size: int | None = Field(default=None, description="分片大小，单位字节")
    etag: str = Field(..., description="MinIO返回的ETag，已去掉外围引号")


class ReconstructionVideoUploadInitReq(BaseModel):
    item_id: str = Field(..., description="配件ID")
    file_name: str = Field(..., description="原始文件名")
    file_size: int = Field(..., gt=0, description="文件大小，单位字节")
    content_type: str = Field(default="application/octet-stream", description="文件类型")
    height: Optional[float] = Field(None, description="高度")
    length: Optional[float] = Field(None, description="长度")
    width: Optional[float] = Field(None, description="宽度")
    weight: Optional[float] = Field(None, description="重量")
    storage_mode: str = Field(default="remote", description="上传模式: remote/local")

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)

    @validator("storage_mode", allow_reuse=True)
    def validate_storage_mode(cls, value):
        normalized = str(value).strip().lower()
        if normalized not in {"remote", "local"}:
            raise ValueError("storage_mode 仅支持 remote 或 local")
        return normalized


class ReconstructionVideoUploadInitRes(BaseModel):
    upload_session_id: str = Field(..., description="上传会话ID")
    item_id: str = Field(..., description="配件ID")
    upload_id: str = Field(..., description="MinIO multipart upload id")
    bucket: str = Field(..., description="MinIO bucket")
    object_name: str = Field(..., description="MinIO object name")
    video_path: str = Field(..., description="MinIO对象路径，格式为 bucket/object")
    part_size: int = Field(..., description="分片大小，单位字节")
    total_parts: int = Field(..., description="总分片数")
    upload_urls: list[ReconstructionMultipartUploadUrlItem] = Field(default_factory=list)

    @validator("upload_session_id", "item_id", pre=True, allow_reuse=True)
    def normalize_ids(cls, value):
        return str(value)


class ReconstructionVideoUploadProgressReq(BaseModel):
    upload_session_id: str = Field(..., description="上传会话ID")

    @validator("upload_session_id", pre=True, allow_reuse=True)
    def normalize_upload_session_id(cls, value):
        return str(value)


class ReconstructionVideoUploadProgressRes(BaseModel):
    upload_session_id: str = Field(..., description="上传会话ID")
    item_id: str = Field(..., description="配件ID")
    upload_id: str = Field(..., description="MinIO multipart upload id")
    bucket: str = Field(..., description="MinIO bucket")
    object_name: str = Field(..., description="MinIO object name")
    video_path: str = Field(..., description="MinIO对象路径，格式为 bucket/object")
    part_size: int = Field(..., description="分片大小，单位字节")
    total_parts: int = Field(..., description="总分片数")
    uploaded_parts: list[ReconstructionMultipartUploadedPartItem] = Field(default_factory=list)

    @validator("upload_session_id", "item_id", pre=True, allow_reuse=True)
    def normalize_ids(cls, value):
        return str(value)


class ReconstructionVideoUploadUrlsReq(BaseModel):
    upload_session_id: str = Field(..., description="上传会话ID")
    part_numbers: list[int] = Field(..., min_items=1, description="需要补签名的分片编号列表")

    @validator("upload_session_id", pre=True, allow_reuse=True)
    def normalize_upload_session_id(cls, value):
        return str(value)


class ReconstructionVideoUploadUrlsRes(BaseModel):
    upload_session_id: str = Field(..., description="上传会话ID")
    upload_urls: list[ReconstructionMultipartUploadUrlItem] = Field(default_factory=list)

    @validator("upload_session_id", pre=True, allow_reuse=True)
    def normalize_upload_session_id(cls, value):
        return str(value)


class ReconstructionVideoUploadCompleteReq(BaseModel):
    upload_session_id: str = Field(..., description="上传会话ID")

    @validator("upload_session_id", pre=True, allow_reuse=True)
    def normalize_upload_session_id(cls, value):
        return str(value)


class ReconstructionVideoUploadAbortReq(BaseModel):
    upload_session_id: str = Field(..., description="上传会话ID")

    @validator("upload_session_id", pre=True, allow_reuse=True)
    def normalize_upload_session_id(cls, value):
        return str(value)


class ReconstructionVideoUploadPartReq(BaseModel):
    upload_session_id: str = Field(..., description="上传会话ID")
    part_number: int = Field(..., ge=1, description="分片编号")

    @validator("upload_session_id", pre=True, allow_reuse=True)
    def normalize_upload_session_id(cls, value):
        return str(value)


class ReconstructionVideoUploadPartRes(BaseModel):
    upload_session_id: str = Field(..., description="上传会话ID")
    part_number: int = Field(..., ge=1, description="分片编号")
    size: int = Field(..., ge=0, description="当前分片大小，单位字节")
    etag: str = Field(default="", description="远端分片上传返回的ETag，本地模式为空字符串")
    message: str = Field(..., description="消息")

    @validator("upload_session_id", pre=True, allow_reuse=True)
    def normalize_upload_session_id(cls, value):
        return str(value)


class ReconstructionVideoUploadMinioHealthRes(BaseModel):
    available: bool = Field(..., description="MinIO 是否可用")
    message: str = Field(..., description="检查结果")
    total_pending: int = Field(..., description="待同步任务数")
    synced_count: int = Field(..., description="同步成功数")
    failed_count: int = Field(..., description="同步失败数")


class ReconstructionResultMessageRes(BaseModel):
    task_id: str = Field(..., description='重构任务ID')
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    result_path: Optional[str] = Field(None, description='被删除或清理的任务重构结果路径')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionResultUploadRes(BaseModel):
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    ply_url: str = Field(..., description='PLY 文件 MinIO 路径')
    filename: str = Field(..., description='原始文件名')
    size: int = Field(..., description='文件大小，单位字节')
    content_type: str = Field(default='', description='文件类型')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionStatusRes(BaseModel):
    task_id: str = Field(..., description='任务ID')
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    item_name: Optional[str] = Field(None, description='配件名称')
    status: str = Field(..., description='任务状态')
    progress: int = Field(..., description='进度 0-100')
    current_stage: Optional[str] = Field(None, description='当前阶段')
    error_message: Optional[str] = Field(None, description='错误信息')
    ply_url: Optional[str] = Field(None, description='PLY文件URL')
    glb_url: Optional[str] = Field(None, description='GLB文件URL')
    is_ply_del: bool = Field(False, description='该任务生成的三维模型是否已删除')
    total_frames: Optional[int] = Field(None, description='总帧数')
    filtered_frames: Optional[int] = Field(None, description='筛选后帧数')
    colmap_points: Optional[int] = Field(None, description='COLMAP点数')
    time_created: Optional[str] = Field(None, description='创建时间')
    time_updated: Optional[str] = Field(None, description='更新时间')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionStatisticsReq(BaseModel):
    pass


class ReconstructionStatisticsRes(BaseModel):
    total_tasks: int = Field(default=0, description='重构任务总数')
    running_tasks: int = Field(default=0, description='运行中的任务数')
    success_tasks: int = Field(default=0, description='成功任务数')
    failed_tasks: int = Field(default=0, description='失败任务数')
    cancelled_tasks: int = Field(default=0, description='已取消任务数')
    success_rate: float = Field(default=0, description='成功率，仅按成功+失败计算')
    avg_success_elapsed_sec: Optional[float] = Field(default=None, description='成功任务平均耗时，单位秒')
    min_success_elapsed_sec: Optional[float] = Field(default=None, description='成功任务最短耗时，单位秒')
    max_success_elapsed_sec: Optional[float] = Field(default=None, description='成功任务最长耗时，单位秒')


class ReconstructionListRes(BaseModel):
    records: list[ReconstructionStatusRes] = Field(default_factory=list, description='记录列表')


class ReconstructionTaskListItem(BaseModel):
    task_id: str = Field(..., description='任务ID')
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    item_name: Optional[str] = Field(None, description='配件名称')
    task_type: str = Field(..., description='任务类型')
    status: str = Field(..., description='任务状态')
    progress: int = Field(..., description='进度 0-100')
    current_stage: Optional[str] = Field(None, description='当前阶段')
    scene_name: Optional[str] = Field(None, description='场景名称')
    error_message: Optional[str] = Field(None, description='错误信息')
    ply_url: Optional[str] = Field(None, description='PLY文件URL')
    glb_url: Optional[str] = Field(None, description='GLB文件URL')
    is_ply_del: bool = Field(False, description='该任务生成的三维模型是否已删除')
    total_frames: Optional[int] = Field(None, description='总帧数')
    filtered_frames: Optional[int] = Field(None, description='筛选后帧数')
    colmap_points: Optional[int] = Field(None, description='COLMAP点数')
    time_created: Optional[str] = Field(None, description='创建时间')
    time_updated: Optional[str] = Field(None, description='更新时间')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionTaskItemDetailReq(BaseModel):
    task_id: str = Field(..., description='重构任务ID')


class ReconstructionTaskItemDetailRes(ReconstructionTaskListItem):
    item_code: Optional[str] = Field(None, description='配件编码')
    height: Optional[float] = Field(None, description='高度')
    length: Optional[float] = Field(None, description='长度')
    width: Optional[float] = Field(None, description='宽度')
    weight: Optional[float] = Field(None, description='重量')
    video_path: Optional[str] = Field(None, description='原始视频路径')
    size_str: Optional[str] = Field(None, description='尺寸描述')
    parent_item_id: Optional[str] = Field(None, description='父配件ID')
    parent_item_name: Optional[str] = Field(None, description='父配件名称')
    parent_item_code: Optional[str] = Field(None, description='父配件编码')
    created_at: Optional[str] = Field(None, description='配件创建时间')
    updated_at: Optional[str] = Field(None, description='配件更新时间')

    @validator("parent_item_id", pre=True, allow_reuse=True)
    def normalize_parent_item_id(cls, value):
        if value is None:
            return None
        return str(value)


class ReconstructionAllTasksReq(PageReq):
    status: Optional[str] = Field(None, description='任务状态筛选（可选）')


class ReconstructionAllTasksRes(BaseModel):
    total: int = Field(..., description='总任务数')
    page: int = Field(..., description='当前页码')
    pageSize: int = Field(..., description='每页数量')
    records: list[ReconstructionTaskListItem] = Field(default_factory=list, description='任务列表')


class ReconstructionIndexRebuildRes(BaseModel):
    message: str = Field(..., description='任务提交结果说明')
    task_id: Optional[str] = Field(
        None,
        description='任务提交后立即返回的后台索引任务ID，用于查询进度、取消或重试',
    )
    status: Optional[str] = Field(
        None,
        description='任务初始状态，正常提交时为 pending',
    )
    item_id: Optional[str] = Field(
        None,
        description='单配件任务的配件ID；批量任务为 null，字符串返回以避免前端精度丢失',
    )
    limit: Optional[str | int] = Field(
        None,
        description='批量任务的配件数量上限；未限制时返回 all，不代表图片数量',
    )
    rebuild_existing: bool = Field(
        False,
        description='false 仅补建未索引图片；true 清理旧索引和分割产物后重建全部有效图片',
    )
    success_count: int | None = Field(None, description='成功建立索引的图片数量')
    fail_count: int | None = Field(None, description='失败的图片数量')
    total: int | None = Field(None, description='本次处理的图片总数')
    processed_item_count: int | None = Field(None, description='本次实际处理的配件数量')
    skipped_existing_count: int | None = Field(None, description='跳过已存在索引的配件数量')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        if value is None:
            return None
        return str(value)


class ReconstructionIndexRebuildStatusRes(BaseModel):
    task_id: str = Field(..., description='当前后台索引任务ID')
    root_task_id: Optional[str] = Field(None, description='整条重试链首次提交的任务ID')
    retry_from_task_id: Optional[str] = Field(None, description='创建当前任务的直接来源任务ID')
    task_scope: Optional[str] = Field(
        None,
        description='任务范围：single 为指定单个配件，batch 为按条件选择多个配件',
    )
    item_code: Optional[str] = Field(None, description='single 任务的配件编码；batch 任务为 null')
    item_limit: Optional[int] = Field(
        None,
        description='任务提交时设置的配件数量上限；null 表示不限制，不是图片数量',
    )
    rebuild_existing: bool = Field(
        False,
        description='false 仅补建未索引图片；true 清理后重建全部有效图片',
    )
    status: str = Field(
        ...,
        description='任务状态：pending/running/cancelling/success/failed/cancelled/interrupted',
    )
    progress: int = Field(..., ge=0, le=100, description='按已完成配件数计算的进度百分比')
    total_items: int = Field(..., description='本次任务实际选中的配件总数')
    processed_items: int = Field(..., description='已完成处理的配件数，用于前端展示进度')
    completed_item_count: int = Field(0, description='已写入持久化检查点的配件数，重试从该检查点继续')
    success_count: int = Field(..., description='成功同时写入 SigLIP 和 DINOv2 索引的图片数量')
    fail_count: int = Field(
        ...,
        description='失败计数：单图处理失败通常记1，配件级处理异常也会记1',
    )
    segmented_count: int = Field(
        0,
        description='CREATEBYSELF 图片成功获得或复用分割图并进入本次索引处理的数量',
    )
    fallback_count: int = Field(
        0,
        description='CREATEBYSELF 图片因主体未识别、空 Mask 或无效 Mask 而改走原图索引路径的数量',
    )
    current_item_code: Optional[str] = Field(None, description='当前正在处理的配件编码')
    last_completed_item_code: Optional[str] = Field(None, description='最近完成的配件编码')
    last_completed_item_created_at: Optional[str] = Field(None, description='最近完成配件的创建时间')
    estimated_remaining_seconds: Optional[int] = Field(
        None,
        description='根据已完成配件平均耗时估算的剩余秒数；样本不足或任务结束时可能为 null',
    )
    estimated_remaining: Optional[str] = Field(
        None,
        description='可直接展示的预计剩余时间，例如“约10分30秒”',
    )
    error_message: Optional[str] = Field(None, description='任务状态为 failed 时的具体失败原因')
    cancel_reason: Optional[str] = Field(None, description='调用取消接口时提交的取消原因')
    heartbeat_at: Optional[str] = Field(None, description='最近一次任务心跳时间')
    started_at: Optional[str] = Field(None, description='任务开始时间')
    completed_at: Optional[str] = Field(None, description='任务结束时间')
    time_created: Optional[str] = Field(None, description='任务创建时间')
    time_updated: Optional[str] = Field(None, description='状态更新时间')

    @validator(
        "item_code",
        "current_item_code",
        "last_completed_item_code",
        pre=True,
        allow_reuse=True,
    )
    def normalize_index_item_code(cls, value):
        if value is None:
            return None
        return str(value)


class ReconstructionIndexTaskListReq(PageReq):
    page: int = Field(
        ...,
        ge=0,
        description='页码；沿用公共分页参数，前端通常从 1 开始',
        example=1,
    )
    per_page: int = Field(
        ...,
        ge=0,
        alias='pageSize',
        description='每页任务数量',
        example=20,
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
        description=(
            '任务状态筛选：all 全部；active 包含等待、运行和取消中的任务；其余值分别对应 '
            'pending、running、cancelling、success、failed、cancelled、interrupted'
        ),
    )
    task_scope: Literal["all", "single", "batch"] = Field(
        "all",
        description='任务范围筛选：all 全部；single 单配件任务；batch 批量任务',
    )
    item_id: Optional[str] = Field(
        None,
        description='按配件ID筛选 single 任务，建议按字符串传递；null 表示不限制配件',
    )

    class Config:
        schema_extra = {
            "example": {
                "page": 1,
                "pageSize": 20,
                "status": "active",
                "task_scope": "all",
            }
        }


class ReconstructionIndexTaskListRes(BaseModel):
    total: int = Field(..., description='总任务数')
    page: int = Field(..., description='当前页码')
    pageSize: int = Field(..., description='每页数量')
    records: list[ReconstructionIndexRebuildStatusRes] = Field(
        default_factory=list,
        description='索引任务列表',
    )


class ReconstructionIndexTaskCancelReq(BaseModel):
    cancel_reason: Optional[str] = Field(
        None,
        max_length=500,
        description='可选取消原因，将随任务记录持久化并供前端展示，最长500字符',
    )
