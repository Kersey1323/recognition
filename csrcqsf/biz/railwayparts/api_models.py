from pydantic import BaseModel
from bfrcommon.api_models import PageReq, PageRes
from pydantic import Field
from csrcqsf.models.sgo import ImageSourceType
from csrcqsf.models.search_history import SearchParameters
from enum import Enum


class FeatureMode(str, Enum):
    """特征提取模式
    
    - STANDARD: ResNet34, 512维向量，速度快
    - HIGH_PRECISION: DINOv2-Large, 1024维向量，精度高 (默认)
    """
    STANDARD = "standard"
    HIGH_PRECISION = "hp"


class CreateItemReq(BaseModel):
    item_name: str
    obj_url: str | None
    item_code: str
    height: float | None
    length: float | None
    width: float | None
    parent_item_id: str | None


class ListItemReq(PageReq):
    query: str | None = Field(default=None, description='搜索关键词', example="司机室")
    parent_item_id: str | None = Field(default=None, description='父配件ID', example=None)
    only_has_index: int = Field(description='只查看有索引的配件.1 为是 0为否', default=0, example=0)
    has_inquery_code: int = Field(description='只查看有询码记录的配件.1为是 0为否', default=0, example=0)
    has_images: int = Field(description='只查看有图片的配件.1 为是 0为否', default=0, example=0)
    
    class Config:
        json_schema_extra = {
            "example": {
                "page": 1,
                "pageSize": 20,
                "query": "司机室",
                "parent_item_id": None,
                "only_has_index": 0,
                "has_inquery_code": 0,
                "has_images": 0
            }
        }


class ListItem(BaseModel):
    item_name: str
    obj_url: str | None
    item_code: str
    height: float | None
    length: float | None
    width: float | None
    created_at: str
    features: list[str] = Field(default=[], description='文字特征')
    features_num: int = 0
    images_total_num: int = Field(description='图片总数', default=0)
    # parent_item_num: int = Field(description='父配件数目')
    # son_item_num: int = Field(description='子配件数目')
    images_total_indexed_num: int = Field(description='图片已索引的总数', default=0)
    id: str


class LisItemRes(PageRes):
    items: list[ListItem] = []


class DeleteItemReq(BaseModel):
    item_id_list: list[str]


class UpdateItemReq(BaseModel):
    obj_url: str | None
    height: float | None
    length: float | None
    width: float | None
    item_name: str
    item_code: str
    parent_item_id: str | None
    id: str


class ItemImageIndexInfo(BaseModel):
    image_id: str
    image_url: str


class ItemImageItem(BaseModel):
    image_id: str
    has_indexed: int = Field(default=0, description='为1时已经进行过索引，其他为未索引')
    image_url: str | None
    source_type: ImageSourceType = None


class GetItemDetailReq(BaseModel):
    item_id: str = Field(description='配件ID', example="2023080809420000001")
    
    class Config:
        json_schema_extra = {
            "example": {
                "item_id": "2023080809420000001"
            }
        }


class GetItemDetailRes(BaseModel):
    obj_url: str | None
    height: float | None
    length: float | None
    width: float | None
    name: str
    item_code: str
    id: str
    created_at: str
    updated_at: str
    images: list[ItemImageItem] = []
    images_index_list: list[ItemImageIndexInfo] | None = []
    parent_item_name: str | None
    parent_item_code: str | None
    parent_item_id: str | None
    size_str: str | None
    features: list[str] = []


class CreateItemImagesReq(BaseModel):
    item_id: str
    images_url: list[str] = []


class CreateItemImagesIndexItem(BaseModel):
    image_id: str = Field(description='原图片id', default='0')
    image_url: str = Field(description="裁剪后的图片地址", default='')


class CreateItemImagesIndexReq(BaseModel):
    item_id: str
    images: list[CreateItemImagesIndexItem] = []
    features: list[str] = Field(description='图片对应的文字特征', default=[])


class DeleteFeaturesReq(BaseModel):
    features: list[str] = []
    item_id: str


class UpdateFeatureReq(BaseModel):
    item_id: str
    old_feature: str
    new_feature: str


class ListFeaturesReq(BaseModel):
    item_id: str = Field(description='配件ID', example="2023080809420000001")
    
    class Config:
        json_schema_extra = {
            "example": {
                "item_id": "2023080809420000001"
            }
        }


class ListFeautresRes(BaseModel):
    features: list[str] = []


class ImageSearchReq(BaseModel):
    images_url: list[str] = Field(default=[], description='图片URL列表', example=["http://192.168.100.2:9000/bfr-ai-files/1725402784070635520.jpg"])
    radius: float = Field(default=0.8, description='相似度，-1到1的浮点数，越大要求越严格', example=0.8)
    texts: list[str] = Field(default=[], description='文字特征列表', example=["控制主机", "司机室"])
    
    class Config:
        json_schema_extra = {
            "example": {
                "images_url": ["http://192.168.100.2:9000/bfr-ai-files/1725402784070635520.jpg"],
                "radius": 0.8,
                "texts": []
            }
        }


class ImageSearchItem(ListItem):
    # item_id: str
    item_name: str
    item_code: str 
    image_url_distance: dict[str, float] = Field(
        default={}, description='查询出来的配件照片与查询照片的相似度,越大越相似')
    max_distance: float


class ImageSearchRes(BaseModel):
    items: list[ImageSearchItem] = []


class UpdateItemSizeStr(BaseModel):
    item_id: str
    item_size_desc: str


class ListIndexedItemImageReq(BaseModel):
    item_id: str


class IndexedItemImageItem(BaseModel):
    source_image_id: str
    source_image_url: str
    image_url: str


class ListIndexedItemImageRes(BaseModel):
    items: list[IndexedItemImageItem] = []


class DeleteImageIndexedReq(BaseModel):
    item_id: str = ''
    image_file_url: list[str] = []


class SearchItem(BaseModel):
    item_id: str = 0
    item_code: str = ''
    item_name: str = ''
    image_url: str = ''
    rate: float = 0

class SearchRes(BaseModel):
    data: list[SearchItem] = []
    message: str | None 



class IndexStatisticsRes(BaseModel):
    total_item_num: int = Field(default=0,description='配件总数')
    total_indexed_item_num: int = Field(default=0,description='已做索引的配件')
    total_index: int = Field(default=0,description='索引总数')
    total_image_index: int = Field(default=0,description='图片索引')
    total_feature_index: int = Field(default=0,description='文字特征总数')
    recognition_number: int = Field(default=0,description='识别测试总数')
    corrrect_recognition_number: int = Field(default=0,description='识别测试总数')
    recognition_ration: float = Field(default=0,description='识别率')


class IndexStatisticsReq(BaseModel):
    pass


# ===== 自动分割建立索引 API 模型 =====

class AutoSegmentReq(BaseModel):
    """自动分割请求 - 只需配件ID"""
    item_id: str = Field(description='配件ID')
    rebuild: bool = Field(default=False, description='是否重建 (删除现有分割记录)')


class AutoSegmentRes(BaseModel):
    """自动分割响应"""
    item_id: str = ''
    total_baseinfo_images: int = Field(default=0, description='BASEINFO图片总数')
    segmented_count: int = Field(default=0, description='成功分割数量')
    indexed_count: int = Field(default=0, description='成功建立索引数量')
    skipped_count: int = Field(default=0, description='跳过数量')
    failed_count: int = Field(default=0, description='失败数量')
    message: str = ''


class SegmentedImageItem(BaseModel):
    """分割记录项"""
    id: str = ''
    source_image_url: str = ''
    segmented_image_url: str = ''
    status: str = ''
    mask_area: int = 0
    bbox: list[int] = []
    is_indexed: bool = False
    error_message: str = ''


class ListSegmentedImagesRes(BaseModel):
    """分割记录列表响应"""
    item_id: str = ''
    records: list[SegmentedImageItem] = []


# ===== 3D 重建 API 模型 =====

class Reconstruct3DReq(BaseModel):
    """3D 重建请求"""
    item_id: str = Field(description='配件ID')
    image_urls: list[str] = Field(description='多角度照片URL列表 (建议50-100张)')


class Reconstruct3DTaskRes(BaseModel):
    """3D 重建任务响应"""
    task_id: str = Field(description='任务ID，用于查询进度')
    item_id: str = ''
    status: str = Field(description='任务状态: pending/downloading/colmap/training/extracting/uploading/completed/failed')
    progress: int = Field(default=0, description='进度 0-100')
    message: str = ''


class TaskProgressRes(BaseModel):
    """任务进度响应"""
    task_id: str = ''
    item_id: str = ''
    status: str = ''
    progress: int = 0
    message: str = ''
    
    # 统计信息
    total_images: int = Field(default=0, description='总图片数')
    downloaded_images: int = Field(default=0, description='已下载图片数')
    colmap_points: int = Field(default=0, description='COLMAP重建点数')
    mesh_vertices: int = Field(default=0, description='网格顶点数')
    mesh_faces: int = Field(default=0, description='网格面数')
    
    # 结果
    obj_url: str = Field(default='', description='生成的OBJ文件URL')
    
    # 时间
    created_at: str = ''
    started_at: str = ''
    completed_at: str = ''
    
    # 错误
    error: str = ''
