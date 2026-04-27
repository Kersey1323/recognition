"""
三维重构 API 模型
"""
from typing import Optional

from bfrcommon.api_models import PageReq
from pydantic import BaseModel, Field, validator


class ReconstructionTrainReq(BaseModel):
    """从已有场景数据训练的请求"""
    item_id: str = Field(..., description='配件ID，建议按字符串传递以避免前端精度丢失')
    scene: str = Field(..., description='场景名称（data目录下的文件夹名）')
    iterations: int = Field(default=30000, description='训练迭代次数')
    output_name: Optional[str] = Field(None, description='输出名称（可选）')


class ReconstructionVideoReq(BaseModel):
    """从视频重建的请求"""
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
    """重建任务响应"""
    task_id: str = Field(..., description='任务ID')
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    mode: str = Field(..., description='模式: train/video')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionVideoUploadRes(BaseModel):
    """重建原始视频上传响应"""
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    bucket: str = Field(..., description='MinIO bucket')
    object_name: str = Field(..., description='MinIO object name')
    video_path: str = Field(..., description='可直接传给 /v2/reconstruct/video 的视频路径')
    size: int = Field(..., description='文件大小，单位字节')
    content_type: str = Field(default='', description='文件类型')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionSourceVideoRes(BaseModel):
    """当前原始视频资产响应"""
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

    @validator("item_id", pre=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionSourceVideoListReq(PageReq):
    """原始视频分页查询请求"""
    pass


class ReconstructionSourceVideoListRes(BaseModel):
    """当前原始视频分页响应"""
    total: int = Field(..., description='总数')
    page: int = Field(..., description='当前页码')
    pageSize: int = Field(..., description='每页数量')
    records: list[ReconstructionSourceVideoRes] = Field(default_factory=list, description='原始视频记录')


class ReconstructionSourceVideoMessageRes(BaseModel):
    """当前原始视频操作消息响应"""
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionResultMessageRes(BaseModel):
    """当前三维重构结果操作消息响应"""
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    result_path: Optional[str] = Field(None, description='被删除或清理的当前重构结果路径')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionResultUploadRes(BaseModel):
    """线下三维重构结果上传响应"""
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    ply_url: str = Field(..., description='PLY 文件 MinIO 路径')
    filename: str = Field(..., description='原始文件名')
    size: int = Field(..., description='文件大小，单位字节')
    content_type: str = Field(default='', description='文件类型')
    message: str = Field(..., description='消息')

    @validator("item_id", pre=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionStatusRes(BaseModel):
    """重建任务状态响应"""
    task_id: str = Field(..., description='任务ID')
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
    status: str = Field(..., description='任务状态')
    progress: int = Field(..., description='进度 0-100')
    current_stage: Optional[str] = Field(None, description='当前阶段')
    error_message: Optional[str] = Field(None, description='错误信息')
    
    # 结果
    ply_url: Optional[str] = Field(None, description='PLY文件URL')
    glb_url: Optional[str] = Field(None, description='GLB文件URL')
    
    # 统计
    total_frames: Optional[int] = Field(None, description='总帧数')
    filtered_frames: Optional[int] = Field(None, description='筛选后帧数')
    colmap_points: Optional[int] = Field(None, description='COLMAP点数')
    
    # 时间
    time_created: Optional[str] = Field(None, description='创建时间')
    time_updated: Optional[str] = Field(None, description='更新时间')

    @validator("item_id", pre=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionListRes(BaseModel):
    """重建记录列表响应"""
    records: list[ReconstructionStatusRes] = Field(default_factory=list, description='记录列表')


class ReconstructionTaskListItem(BaseModel):
    """重建任务列表项"""
    task_id: str = Field(..., description='任务ID')
    item_id: str = Field(..., description='配件ID，字符串返回以避免前端精度丢失')
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

    @validator("item_id", pre=True)
    def normalize_item_id(cls, value):
        return str(value)


class ReconstructionAllTasksReq(PageReq):
    """重构任务分页查询请求"""
    status: Optional[str] = Field(None, description='任务状态筛选（可选）')


class ReconstructionAllTasksRes(BaseModel):
    """所有重建任务分页响应"""
    total: int = Field(..., description='总任务数')
    page: int = Field(..., description='当前页码')
    pageSize: int = Field(..., description='每页数量')
    records: list[ReconstructionTaskListItem] = Field(default_factory=list, description='任务列表')


class ReconstructionIndexRebuildRes(BaseModel):
    """V2 索引重建响应"""
    message: str = Field(..., description='消息')
    item_id: Optional[str] = Field(None, description='配件ID，字符串返回以避免前端精度丢失')
    limit: Optional[str | int] = Field(None, description='处理数量限制')
    rebuild_existing: bool = Field(False, description='是否重建已存在的索引')

    @validator("item_id", pre=True)
    def normalize_item_id(cls, value):
        if value is None:
            return None
        return str(value)
