"""
三维重构 API 模型
"""
from pydantic import BaseModel, Field
from typing import Optional


class ReconstructionTrainReq(BaseModel):
    """从已有场景数据训练的请求"""
    item_id: int = Field(..., description='配件ID')
    scene: str = Field(..., description='场景名称（data目录下的文件夹名）')
    iterations: int = Field(default=30000, description='训练迭代次数')
    output_name: Optional[str] = Field(None, description='输出名称（可选）')


class ReconstructionVideoReq(BaseModel):
    """从视频重建的请求"""
    item_id: int = Field(..., description='配件ID')
    video_path: str = Field(..., description='视频文件路径，支持服务器本地绝对路径或 MinIO 对象路径（如 bfr-3d-videos/raw-videos/...mp4）')
    name: str = Field(..., description='场景名称')
    iterations: int = Field(default=30000, description='训练迭代次数')
    fps: float = Field(default=3, description='提帧率')
    image_size: int = Field(default=1600, description='图片最大边长')
    blur_threshold: float = Field(default=0, description='模糊阈值，0=自适应')
    dedup_threshold: int = Field(default=25, description='去重汉明距离')
    min_frames: int = Field(default=30, description='最小帧数')
    sam3_model: str = Field(default="", description='SAM3模型路径，为空则不分割')
    text_prompt: str = Field(default="object", description='SAM3文本提示词')
    mask_dilate: int = Field(default=15, description='Mask膨胀像素')
    camera: str = Field(default="OPENCV", description='相机模型')
    no_gpu: bool = Field(default=True, description='不使用GPU')
    skip_extract: bool = Field(default=False, description='跳过提帧')
    skip_filter: bool = Field(default=False, description='跳过帧筛选')
    skip_colmap: bool = Field(default=False, description='跳过COLMAP')
    skip_sam3: bool = Field(default=False, description='跳过SAM3')
    output_name: Optional[str] = Field(None, description='输出名称（可选）')


class ReconstructionTaskRes(BaseModel):
    """重建任务响应"""
    task_id: str = Field(..., description='任务ID')
    item_id: int = Field(..., description='配件ID')
    mode: str = Field(..., description='模式: train/video')
    message: str = Field(..., description='消息')


class ReconstructionVideoUploadRes(BaseModel):
    """重建原始视频上传响应"""
    item_id: int = Field(..., description='配件ID')
    bucket: str = Field(..., description='MinIO bucket')
    object_name: str = Field(..., description='MinIO object name')
    video_path: str = Field(..., description='可直接传给 /v2/reconstruct/video 的视频路径')
    size: int = Field(..., description='文件大小，单位字节')
    content_type: str = Field(default='', description='文件类型')
    message: str = Field(..., description='消息')


class ReconstructionStatusRes(BaseModel):
    """重建任务状态响应"""
    task_id: str = Field(..., description='任务ID')
    item_id: int = Field(..., description='配件ID')
    status: str = Field(..., description='任务状态')
    progress: int = Field(..., description='进度 0-100')
    current_stage: Optional[str] = Field(None, description='当前阶段')
    error_message: Optional[str] = Field(None, description='错误信息')
    
    # 结果
    ply_url: Optional[str] = Field(None, description='PLY文件URL')
    obj_url: Optional[str] = Field(None, description='OBJ文件URL')
    glb_url: Optional[str] = Field(None, description='GLB文件URL')
    
    # 统计
    total_frames: Optional[int] = Field(None, description='总帧数')
    filtered_frames: Optional[int] = Field(None, description='筛选后帧数')
    colmap_points: Optional[int] = Field(None, description='COLMAP点数')
    
    # 时间
    created_at: Optional[str] = Field(None, description='创建时间')
    updated_at: Optional[str] = Field(None, description='更新时间')


class ReconstructionListRes(BaseModel):
    """重建记录列表响应"""
    records: list[ReconstructionStatusRes] = Field(default_factory=list, description='记录列表')
