"""
三维重构 API 模型
"""
from typing import Optional

from bfrcommon.api_models import PageReq
from pydantic import BaseModel, Field, validator


class ReconstructionTrainReq(BaseModel):
    item_id: str = Field(..., description='配件ID，建议按字符串传递以避免前端精度丢失')
    scene: str = Field(..., description='场景名称（data目录下的文件夹名）')
    iterations: int = Field(default=30000, description='训练迭代次数')
    output_name: Optional[str] = Field(None, description='输出名称（可选）')


class ReconstructionVideoReq(BaseModel):
    item_id: str = Field(..., description='配件ID，建议按字符串传递以避免前端精度丢失')
    iterations: int = Field(default=30000, description='训练迭代次数')
    fps: float = Field(default=3, description='提帧率')
    image_size: int = Field(default=1600, description='图片最大边长')
    blur_threshold: float = Field(default=0, description='模糊阈值，0=自适应')
    dedup_threshold: int = Field(default=25, description='去重汉明距离')
    min_frames: int = Field(default=30, description='最小帧数')
    is_sam3: bool = Field(default=False, description='是否启用SAM3分割，模型路径由服务端SAM3_MODEL_PATH配置')
    text_prompt: str = Field(default="object", description='SAM3文本提示词')
    mask_dilate: int = Field(default=15, description='Mask膨胀像素')
    camera: str = Field(default="OPENCV", description='相机模型')
    no_gpu: bool = Field(default=True, description='不使用GPU')
    skip_extract: bool = Field(default=False, description='跳过提帧')
    skip_filter: bool = Field(default=False, description='跳过帧筛选')
    skip_colmap: bool = Field(default=False, description='跳过COLMAP')
    skip_sam3: bool = Field(default=False, description='跳过SAM3')

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


class ReconstructionVideoUploadMinioHealthRes(BaseModel):
    available: bool = Field(..., description="MinIO 是否可用")
    message: str = Field(..., description="检查结果")
    total_pending: int = Field(..., description="待同步任务数")
    synced_count: int = Field(..., description="同步成功数")
    failed_count: int = Field(..., description="同步失败数")


class ReconstructionResultMessageRes(BaseModel):
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    result_path: Optional[str] = Field(None, description='被删除或清理的当前重构结果路径')
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
    total_frames: Optional[int] = Field(None, description='总帧数')
    filtered_frames: Optional[int] = Field(None, description='筛选后帧数')
    colmap_points: Optional[int] = Field(None, description='COLMAP点数')
    time_created: Optional[str] = Field(None, description='创建时间')
    time_updated: Optional[str] = Field(None, description='更新时间')

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionAllTasksReq(PageReq):
    status: Optional[str] = Field(None, description='任务状态筛选（可选）')


class ReconstructionAllTasksRes(BaseModel):
    total: int = Field(..., description='总任务数')
    page: int = Field(..., description='当前页码')
    pageSize: int = Field(..., description='每页数量')
    records: list[ReconstructionTaskListItem] = Field(default_factory=list, description='任务列表')


class ReconstructionIndexRebuildRes(BaseModel):
    message: str = Field(..., description='消息')
    item_id: Optional[str] = Field(None, description='配件ID，字符串返回以避免前端精度丢失')
    limit: Optional[str | int] = Field(None, description='处理数量限制')
    rebuild_existing: bool = Field(False, description='是否重建已存在的索引')
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
