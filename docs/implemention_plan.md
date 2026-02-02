# 动车配件图像识别系统 - 优化实施计划

## 项目概述

对 `csrcqsf` 项目进行全面优化，包括性能提升、自动配件检测功能、API接口开发等。

**预计总工期**: 2-3周  
**涉及核心模块**: `csrcqsf/biz/railwayparts/`

---

## Phase 0: 高精度模型升级 (预计2天)

> [!IMPORTANT]
> 保留现有Milvus集合不变，新建高精度特征集合，支持A/B测试和平滑迁移

### 0.1 模型升级: ResNet34 → DINOv2-Large

#### [MODIFY] milvus.py

**新增 `DINOv2Extractor` 类** (保留原有的 `FeatureExtractor`):

```python
import torch

class DINOv2Extractor:
    """高精度特征提取器 - DINOv2-Large"""
    
    def __init__(self):
        self.model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vitl14')
        self.model.eval()
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = self.model.to(self.device)
        
        # DINOv2 预处理
        from torchvision import transforms
        self.preprocess = transforms.Compose([
            transforms.Resize(518, interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.CenterCrop(518),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
    
    def __call__(self, image):
        from PIL import Image
        from sklearn.preprocessing import normalize
        
        image = Image.fromarray(image)
        input_tensor = self.preprocess(image).unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            features = self.model(input_tensor)
        
        feature_vector = features.cpu().numpy().squeeze()
        return normalize(feature_vector.reshape(1, -1), norm="l2").flatten()
    
    def __call_batch__(self, images: list):
        """批量提取特征"""
        from PIL import Image
        from sklearn.preprocessing import normalize
        
        tensors = torch.stack([
            self.preprocess(Image.fromarray(img)) for img in images
        ]).to(self.device)
        
        with torch.no_grad():
            features = self.model(tensors)
        
        return [normalize(f.cpu().numpy().reshape(1, -1), norm="l2").flatten() 
                for f in features]
```

**修改 `ColletionEnum`** - 添加新集合:

```python
class ColletionEnum(str, Enum):
    IMAGECOLLECTION = "PARTS_IMAGE_COLLETION_NEW4"           # 旧集合(保留)
    FEATURESCOLLECTION = 'PARTS_FEATURES_COLLECTION_NEW4'    # 旧集合(保留)
    NEWCOLLECTION = "PARTS_INDEX"                             # 旧集合(保留)
    
    # ===== 新增高精度集合 =====
    HP_IMAGE_COLLECTION = "PARTS_HP_IMAGE_V1"       # 高精度图像特征
    HP_FEATURES_COLLECTION = "PARTS_HP_FEATURES_V1" # 高精度文本特征
    HP_INDEX_COLLECTION = "PARTS_HP_INDEX_V1"       # 高精度混合索引
```

**修改 `MilvusManager`** - 添加高精度提取器:

```python
class MilvusManager:
    # 保留旧的
    extractor = FeatureExtractor("resnet34")              # 512维
    _embedding_model = SentenceTransformer('./embedding_models')
    
    # 新增高精度
    hp_extractor = None  # 延迟加载
    
    @classmethod
    def get_hp_extractor(cls):
        """延迟加载高精度模型"""
        if cls.hp_extractor is None:
            cls.hp_extractor = DINOv2Extractor()
        return cls.hp_extractor
    
    @classmethod
    def extract_hp_image_tensor(cls, image):
        """高精度特征提取"""
        return cls.get_hp_extractor()(image)
    
    @classmethod
    def extract_hp_image_tensor_batch(cls, images: list):
        """高精度批量特征提取"""
        return cls.get_hp_extractor().__call_batch__(images)
```

---

### 0.2 新建高精度Milvus集合

#### [MODIFY] milvus.py

**添加 `__init_hp_collections` 方法**:

```python
@classmethod
def __init_hp_collections(cls):
    """初始化高精度特征集合"""
    if not milvus_client.has_collection(ColletionEnum.HP_INDEX_COLLECTION.value):
        schema = MilvusClient.create_schema(enable_dynamic_field=True, auto_id=False)
        
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="item_id", datatype=DataType.INT64)
        schema.add_field(field_name="parent_item_info", 
                        datatype=DataType.ARRAY, element_type=DataType.INT64, max_capacity=1000)
        schema.add_field(field_name="vechile_info",
                        datatype=DataType.ARRAY, element_type=DataType.VARCHAR, 
                        max_capacity=1000, max_length=2000)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=2000)
        
        # ===== 高精度图像特征: 1024维 (DINOv2-Large) =====
        image_struct = MilvusClient.create_struct_field_schema()
        image_struct.add_field("image_id", DataType.INT64)
        image_struct.add_field("image_vector", DataType.FLOAT_VECTOR, dim=1024, mmap_enabled=True)
        image_struct.add_field("filename", DataType.VARCHAR, max_length=20000)
        image_struct.add_field("image_index_created", DataType.VARCHAR, max_length=20000)
        
        schema.add_field("images", DataType.ARRAY, element_type=DataType.STRUCT,
                        struct_schema=image_struct, max_capacity=1000)
        
        # 文本特征: 保持512维
        feature_struct = MilvusClient.create_struct_field_schema()
        feature_struct.add_field("feature", DataType.VARCHAR, max_length=65535)
        feature_struct.add_field("feature_vector", DataType.FLOAT_VECTOR, dim=512, mmap_enabled=True)
        feature_struct.add_field("feature_index_created", DataType.VARCHAR, max_length=20000)
        
        schema.add_field("features", DataType.ARRAY, element_type=DataType.STRUCT,
                        struct_schema=feature_struct, max_capacity=1000)
        
        # 索引配置
        index_params = milvus_client.prepare_index_params()
        index_params.add_index(field_name="item_id", index_type="AUTOINDEX")
        index_params.add_index(field_name="images[image_vector]", 
                              index_type="HNSW", metric_type="COSINE",
                              params={"M": 32, "efConstruction": 256})
        index_params.add_index(field_name="features[feature_vector]",
                              index_type="HNSW", metric_type="COSINE",
                              params={"M": 32, "efConstruction": 256})
        
        milvus_client.create_collection(
            collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
            schema=schema,
            index_params=index_params
        )
    
    milvus_client.load_collection(ColletionEnum.HP_INDEX_COLLECTION.value)
```

**修改 `_init_collection` 方法**:

```python
@classmethod
def _init_collection(cls):
    cls.__init_new_collections()      # 保留旧集合
    cls.__init_hp_collections()       # 新增高精度集合
```

---

### 0.3 双模式API支持

#### [MODIFY] api_models.py

```python
from enum import Enum

class FeatureMode(str, Enum):
    STANDARD = "standard"   # ResNet34, 512维
    HIGH_PRECISION = "hp"   # DINOv2, 1024维

class SearchReqV2(BaseModel):
    images: list[str] = []
    features: list[str] = []
    lower_rate: float = 0.8
    mode: FeatureMode = FeatureMode.STANDARD  # 新增模式选择
```

---

### 0.4 时间规划

| 任务 | 时间 |
|------|------|
| DINOv2模型集成 | 0.5天 |
| 新Milvus集合创建 | 0.5天 |
| 双模式API支持 | 0.5天 |
| 测试验证 | 0.5天 |

---

## Phase 1: 性能优化 (预计3天)

### 1.1 批量特征提取

#### [MODIFY] milvus.py

**修改 `FeatureExtractor` 类**:
- 添加 `__call_batch__` 方法支持批量推理
- 使用 `torch.stack` 合并多张图片tensor
- 单次前向传播处理批量数据

```python
def __call_batch__(self, images: list):
    """批量提取图像特征"""
    tensors = torch.stack([
        self.preprocess(Image.fromarray(img)) for img in images
    ])
    
    with torch.no_grad():
        outputs = self.model(tensors)
    
    return [normalize(f.numpy().reshape(1, -1), norm="l2").flatten() 
            for f in outputs]
```

**修改 `MilvusManager` 类**:
- 添加 `extract_image_tensor_batch` 类方法
- 添加 `embedding_encode_batch` 批量文本编码

---

#### [MODIFY] parts.py

**修改 `create_item_index` 方法** (L355-430):
- 并发加载所有图片
- 批量提取特征向量
- 批量编码文本特征

```python
# 并发加载图片
images = await asyncio.gather(*[
    run_sync(cls.get_image_from_oss, img.image_url) 
    for img in req.images
])

# 批量提取特征
tensors = await run_sync(MilvusManager.extract_image_tensor_batch, images)
```

---

### 1.2 混合精度推理

#### [MODIFY] milvus.py

**修改 `FeatureExtractor.__init__`** (L59-73):
```python
def __init__(self, modelname):
    self.model = timm.create_model(...)
    self.model.eval()
    
    self.device = "cuda" if torch.cuda.is_available() else "cpu"
    if self.device == "cuda":
        self.model = self.model.cuda().half()  # FP16
```

**修改 `FeatureExtractor.__call__`** (L75-92):
```python
def __call__(self, image):
    input_tensor = self.preprocess(image).unsqueeze(0)
    
    if self.device == "cuda":
        input_tensor = input_tensor.cuda().half()
    
    with torch.no_grad():
        output = self.model(input_tensor)
    
    return normalize(output.cpu().float().squeeze().numpy()...)
```

---

### 1.3 图像缓存

#### [MODIFY] parts.py

**添加LRU缓存**:
```python
from cachetools import LRUCache

class RailwayPartsManager:
    _image_cache = LRUCache(maxsize=100)
    
    @classmethod
    def get_image_from_oss_cached(cls, image_url: str):
        if image_url in cls._image_cache:
            return cls._image_cache[image_url]
        
        img = cls.get_image_from_oss(image_url)
        cls._image_cache[image_url] = img
        return img
```

---

## Phase 2: 自动配件检测 (预计5天)

### 2.1 SAM自动分割

#### [MODIFY] segment.py

**扩展 `SegmentBiz` 类**:
```python
@classmethod
async def auto_detect_parts(cls, image_url: str):
    """自动检测图片中的所有配件"""
    image = RailwayPartsManager.get_image_from_oss(image_url)
    
    mask_generator = SamAutomaticMaskGenerator(
        cls.sam_model,
        points_per_side=32,
        pred_iou_thresh=0.86,
        stability_score_thresh=0.92,
        min_mask_region_area=100,
    )
    
    masks = mask_generator.generate(image)
    masks = sorted(masks, key=lambda x: x['area'], reverse=True)
    
    detected_parts = []
    for mask in masks[:10]:
        bbox = mask['bbox']
        x, y, w, h = bbox
        part_image = image[y:y+h, x:x+w]
        
        image_feature = await run_sync(
            MilvusManager.extract_image_tensor, part_image
        )
        
        detected_parts.append({
            'bbox': bbox,
            'confidence': mask['predicted_iou'],
            'image_feature': image_feature,
            'cropped_image': part_image
        })
    
    return detected_parts
```

---

### 2.2 混合检测方案

#### [NEW] auto_processor.py

**创建 `AutoPartProcessor` 类**:

```python
from ultralytics import YOLO
import numpy as np
import cv2
from anyio.to_thread import run_sync
from .milvus import MilvusManager
from csrcqsf.biz.segment import SegmentBiz

class AutoPartProcessor:
    """自动配件处理器 - YOLO + SAM + 特征提取"""
    
    _yolo_model = None
    
    @classmethod
    def get_yolo_model(cls):
        if cls._yolo_model is None:
            cls._yolo_model = YOLO('yolov8n.pt')
        return cls._yolo_model
    
    @classmethod
    async def process_image(cls, image_url: str, auto_index: bool = True):
        """完整自动化流程"""
        from .parts import RailwayPartsManager
        
        image = RailwayPartsManager.get_image_from_oss(image_url)
        model = cls.get_yolo_model()
        
        # YOLO粗检测
        detections = model(image, conf=0.3)
        
        all_parts = []
        for det in detections[0].boxes:
            x1, y1, x2, y2 = det.xyxy[0].cpu().numpy()
            
            # SAM精细分割
            SegmentBiz.predictor.set_image(image)
            masks, scores, _ = SegmentBiz.predictor.predict(
                box=np.array([x1, y1, x2, y2]),
                multimask_output=False
            )
            
            mask = masks[0]
            part_image = image.copy()
            part_image[~mask] = 255
            part_image = part_image[int(y1):int(y2), int(x1):int(x2)]
            
            # 特征提取
            visual_feature = await run_sync(
                MilvusManager.extract_image_tensor, part_image
            )
            
            # OCR
            ocr_result = SegmentBiz.engine(part_image)
            text_features = ocr_result.txts if ocr_result.txts else []
            
            # 形状特征
            shape_features = cls.extract_shape_features(mask)
            
            all_parts.append({
                'bbox': [float(x1), float(y1), float(x2-x1), float(y2-y1)],
                'confidence': float(det.conf[0]),
                'visual_feature': visual_feature.tolist(),
                'text_features': text_features,
                'shape_features': shape_features,
            })
        
        return all_parts
    
    @classmethod
    def extract_shape_features(cls, mask):
        """提取形状特征"""
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), 
            cv2.RETR_EXTERNAL, 
            cv2.CHAIN_APPROX_SIMPLE
        )
        
        if not contours:
            return {}
        
        cnt = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(cnt)
        perimeter = cv2.arcLength(cnt, True)
        circularity = 4 * np.pi * area / (perimeter ** 2) if perimeter > 0 else 0
        
        x, y, w, h = cv2.boundingRect(cnt)
        aspect_ratio = w / h if h > 0 else 0
        
        return {
            'area': float(area),
            'circularity': float(circularity),
            'aspect_ratio': float(aspect_ratio)
        }
```

---

## Phase 3: API接口开发 (预计2天)

### 3.1 API模型定义

#### [MODIFY] api_models.py

**新增数据模型**:
```python
class DetectedPart(BaseModel):
    bbox: list[float] = Field(description='边界框 [x, y, w, h]')
    confidence: float = Field(description='检测置信度')
    text_features: list[str] = Field(default=[], description='OCR提取的文字')
    shape_features: dict = Field(default={}, description='形状特征')

class AutoDetectReq(BaseModel):
    image_url: str = Field(description='图片URL')
    auto_index: bool = Field(default=False, description='是否自动建立索引')

class AutoDetectRes(BaseModel):
    parts_count: int = Field(description='检测到的配件数量')
    parts: list[DetectedPart] = []

class BatchAutoIndexReq(BaseModel):
    limit: int = Field(default=100, description='处理数量限制')

class BatchAutoIndexRes(BaseModel):
    success_count: int
    failed_count: int
    results: list[dict] = []
```

---

### 3.2 新增API路由

#### [MODIFY] services/parts.py

**新增接口**:
```python
from csrcqsf.biz.railwayparts.auto_processor import AutoPartProcessor

@parts_router.post('/auto_detect',
    tags=["railway"],
    summary='自动检测配件并提取特征',
    responses={200: {'model': AutoDetectRes}}
)
async def auto_detect_parts(req: AutoDetectReq):
    parts = await AutoPartProcessor.process_image(
        image_url=req.image_url,
        auto_index=req.auto_index
    )
    return AutoDetectRes(parts_count=len(parts), parts=parts)


@parts_router.post('/batch_auto_index',
    tags=["railway"],
    summary='批量自动建立索引'
)
async def batch_auto_index(req: BatchAutoIndexReq, background_tasks: BackgroundTasks):
    # 添加后台任务
    background_tasks.add_task(AutoPartProcessor.batch_process, req.limit)
    return {"message": "批量索引任务已启动"}
```

---

## Phase 4: 配置和代码质量 (预计2天)

### 4.1 配置参数化

#### [MODIFY] settings.py

**添加配置类**:
```python
class ImageSearchSettings(BaseModel):
    SEARCH_LIMIT: int = 3
    RRF_K: int = 100
    IMAGE_MAX_SIZE: int = 1920
    BATCH_SIZE: int = 32
    CACHE_SIZE: int = 100
    
    # YOLO配置
    YOLO_CONF_THRESHOLD: float = 0.3
    YOLO_MODEL_PATH: str = 'yolov8n.pt'
    
    # SAM配置
    SAM_POINTS_PER_SIDE: int = 32
    SAM_IOU_THRESH: float = 0.86
    SAM_MIN_AREA: int = 100
    
    # HNSW索引参数
    HNSW_M: int = 24
    HNSW_EF_CONSTRUCTION: int = 200

image_settings = ImageSearchSettings()
```

---

### 4.2 自定义异常

#### [NEW] exceptions.py

```python
class RailwayPartsError(Exception):
    """配件系统基础异常"""
    pass

class ImageLoadError(RailwayPartsError):
    """图片加载失败"""
    pass

class FeatureExtractionError(RailwayPartsError):
    """特征提取失败"""
    pass

class DetectionError(RailwayPartsError):
    """配件检测失败"""
    pass

class IndexError(RailwayPartsError):
    """索引操作失败"""
    pass
```

---

## 验证计划

### 自动化测试

```bash
# 运行单元测试
python -m pytest tests/ -v

# 性能基准测试
python scripts/benchmark.py --batch-size 32

# 检测准确率测试
python scripts/evaluate_detection.py --dataset test_images/
```

### 手动验证

1. **单图检测测试**: 上传配件图片，验证检测结果
2. **批量索引测试**: 触发批量处理，检查索引建立
3. **检索准确率**: 对比优化前后的检索效果
4. **性能对比**: 记录优化前后的响应时间

---

## 时间规划

| 阶段 | 任务 | 预计时间 | 优先级 |
|------|------|----------|--------|
| Phase 0 | 高精度模型升级 | 2天 | P0 |
| Phase 1.1 | 批量特征提取 | 1天 | P0 |
| Phase 1.2 | 混合精度推理 | 0.5天 | P0 |
| Phase 1.3 | 图像缓存 | 0.5天 | P1 |
| Phase 2.1 | SAM自动分割 | 1天 | P0 |
| Phase 2.2 | 混合检测方案 | 2天 | P0 |
| Phase 3 | API开发 | 1.5天 | P0 |
| Phase 4 | 配置和质量 | 1天 | P1 |
| 测试验证 | 全面测试 | 1天 | P0 |

**总计: 约 10-11 个工作日**

---

## 风险和注意事项

> [!WARNING]
> **GPU显存**: 同时加载YOLO+SAM+DINOv2可能需要较大显存，建议12GB以上

> [!IMPORTANT]
> **模型文件**: 需要预先下载YOLOv8模型文件和DINOv2模型到服务器

> [!NOTE]
> **向后兼容**: 所有修改保持现有API接口不变，新功能通过新接口暴露