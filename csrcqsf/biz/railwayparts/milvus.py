import os
from typing import Any

import timm
import torch
from anyio.to_thread import run_sync
from bfrcommon.common import splite_list_by_n
from bfrcommon.snowflake import get_id
from PIL import Image
from pydantic import BaseModel
from pymilvus import DataType, MilvusClient
from sentence_transformers import SentenceTransformer, util
from sklearn.preprocessing import normalize
from timm.data import resolve_data_config
from timm.data.transforms_factory import create_transform

from csrcqsf.data.milvus import milvus_client
from csrcqsf.data.minio import minio_instance
from csrcqsf.logger import logger
from csrcqsf.models.item import *
from csrcqsf.models.sgo import SgoItemImages
from csrcqsf.settings import minio_bucket, temp_dir

from .api_models import ImageSearchItem


class ColletionEnum(str, Enum):
    IMAGECOLLECTION = "PARTS_IMAGE_COLLETION_NEW4"
    FEATURESCOLLECTION = 'PARTS_FEATURES_COLLECTION_NEW4'
    NEWCOLLECTION = "PARTS_INDEX"
    
    # ===== 高精度集合 (DINOv2-Large, 1024维) =====
    HP_INDEX_COLLECTION = "PARTS_HP_INDEX_V1"


class SearchResult(BaseModel):
    item_id: int
    image_id: int
    distance: float


class ImageIndex(BaseModel):
    image_id: int
    filename: str
    image_vector: Any
    image_index_created: str | None


class FeaturesIndex(BaseModel):
    feature: str
    feature_vector: Any
    feature_index_created: str | None


class PartsIndex(BaseModel):
    item_id: int = 0
    item_name: str = ''
    item_code: str = ''
    id: int = 0
    images: list[ImageIndex] = []
    features: list[FeaturesIndex] = []
    vechile_info: list[int] = []
    parent_item_info: list[int] = []
    created_at: str | None
    updated_at: str | None 


class FeatureExtractor:
    def __init__(self, modelname):
        # Load the pre-trained model
        # pretrained_cfg = timm.create_model(modelname).default_cfg
        # pretrained_cfg['file'] = "./resnet_models"
        self.model = timm.create_model(
            modelname, pretrained=True, num_classes=0, global_pool="avg", pretrained_cfg_overlay=dict(file="./models/resnet/pytorch_model.bin")
        )
        self.model.eval()

        # Get the input size required by the model
        self.input_size = self.model.default_cfg["input_size"]

        config = resolve_data_config({}, model=modelname)
        # Get the preprocessing function provided by TIMM for the model
        self.preprocess = create_transform(**config)

    def __call__(self, image):
        # Preprocess the input image
        # input_image = Image.open(imagepath).convert(
        #     "RGB")  # Convert to RGB if needed
        image = Image.fromarray(image)
        input_image = self.preprocess(image)

        # Convert the image to a PyTorch tensor and add a batch dimension
        input_tensor = input_image.unsqueeze(0)

        # Perform inference
        with torch.no_grad():
            output = self.model(input_tensor)

        # Extract the feature vector
        feature_vector = output.squeeze().numpy()

        return normalize(feature_vector.reshape(1, -1), norm="l2").flatten()


class DINOv2Extractor:
    """高精度特征提取器 - DINOv2-Large (1024维向量)
    
    DINOv2 是 Meta 的自监督视觉模型，在图像特征表示上有更强的泛化能力，
    适合需要高精度识别的场景。
    
    模型文件需要预先下载到本地:
    - 下载地址: https://dl.fbaipublicfiles.com/dinov2/dinov2_vitl14/dinov2_vitl14_pretrain.pth
    - 放置位置: ./dinov2_models/dinov2_vitl14_pretrain.pth
    """
    
    # 本地模型路径
    MODEL_PATH = './dinov2_models/dinov2_vitl14_pretrain.pth'
    
    def __init__(self):
        from torchvision import transforms
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 从本地加载 DINOv2-Large 模型
        self.model = self._load_local_model()
        self.model.eval()
        self.model = self.model.to(self.device)
        
        # DINOv2 官方预处理配置
        self.preprocess = transforms.Compose([
            transforms.Resize(518, interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.CenterCrop(518),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        
        logger.info(f"DINOv2-Large 模型加载成功 (设备: {self.device})")
    
    def _load_local_model(self):
        """从本地加载 DINOv2 模型"""
        import os
        
        if not os.path.exists(self.MODEL_PATH):
            raise FileNotFoundError(
                f"DINOv2 模型文件不存在: {self.MODEL_PATH}\n"
                f"请下载模型文件:\n"
                f"  wget https://dl.fbaipublicfiles.com/dinov2/dinov2_vitl14/dinov2_vitl14_pretrain.pth\n"
                f"  mkdir -p ./dinov2_models && mv dinov2_vitl14_pretrain.pth ./dinov2_models/"
            )
        
        # 使用 timm 加载 ViT-Large 架构
        try:
            # 方式1: 使用 timm 创建 ViT-Large 结构
            model = timm.create_model(
                'vit_large_patch14_dinov2.lvd142m',
                pretrained=False,
                num_classes=0,  # 移除分类头，只输出特征
            )
            
            # 加载本地权重
            state_dict = torch.load(self.MODEL_PATH, map_location='cpu')
            
            # 处理可能的 key 前缀差异
            if 'model' in state_dict:
                state_dict = state_dict['model']
            
            # 尝试加载权重 (允许部分不匹配)
            model.load_state_dict(state_dict, strict=False)
            
            return model
            
        except Exception as e:
            logger.warning(f"timm 加载失败，尝试原生方式: {e}")
            
            # 方式2: 使用原生 Vision Transformer
            from torch import nn
            
            class DINOv2ViTLarge(nn.Module):
                """DINOv2 ViT-Large 模型结构"""
                def __init__(self):
                    super().__init__()
                    self.vit = timm.create_model(
                        'vit_large_patch14_224',
                        pretrained=False,
                        num_classes=0,
                        img_size=518,
                    )
                
                def forward(self, x):
                    return self.vit(x)
            
            model = DINOv2ViTLarge()
            state_dict = torch.load(self.MODEL_PATH, map_location='cpu')
            
            if 'model' in state_dict:
                state_dict = state_dict['model']
            
            model.load_state_dict(state_dict, strict=False)
            return model
    
    def __call__(self, image):
        """单张图片特征提取"""
        image = Image.fromarray(image)
        input_tensor = self.preprocess(image).unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            features = self.model(input_tensor)
        
        feature_vector = features.cpu().numpy().squeeze()
        return normalize(feature_vector.reshape(1, -1), norm="l2").flatten()
    
    def __call_batch__(self, images: list):
        """批量提取特征"""
        tensors = torch.stack([
            self.preprocess(Image.fromarray(img)) for img in images
        ]).to(self.device)
        
        with torch.no_grad():
            features = self.model(tensors)
        
        return [normalize(f.cpu().numpy().reshape(1, -1), norm="l2").flatten() 
                for f in features]



class MilvusManager:
    # 标准模式: ResNet34 (512维)
    extractor = FeatureExtractor("resnet34")
    _embedding_model = SentenceTransformer('./models/embedding/bge-small-zh-v1.5')
    
    # 高精度模式: DINOv2-Large (1024维) - 延迟加载
    _hp_extractor = None
    
    @classmethod
    def get_hp_extractor(cls):
        """延迟加载高精度模型，避免启动时占用资源"""
        if cls._hp_extractor is None:
            cls._hp_extractor = DINOv2Extractor()
        return cls._hp_extractor
    
    @classmethod
    async def extract_hp_image_tensor(cls, image):
        """高精度特征提取 (DINOv2, 1024维)"""
        def _():
            return cls.get_hp_extractor()(image)
        return await run_sync(_)
    
    @classmethod
    async def extract_hp_image_tensor_batch(cls, images: list):
        """高精度批量特征提取"""
        def _():
            return cls.get_hp_extractor().__call_batch__(images)
        return await run_sync(_)


    # @classmethod
    # async def insert_pic(cls, images):
    #     await run_sync(cls._insert_pic, images)

    @classmethod
    async def embedding_encode(cls, data: str):
        def _():
            embeddings = cls._embedding_model.encode(
                data, prompt='中文特征字符串,用于检索', normalize_embeddings=True, batch_size=32)
            return embeddings
        return await run_sync(_)

    @classmethod
    async def extract_image_tensor(cls, image):
        def _():
            return cls.extractor(image)
        return await run_sync(_)

    @classmethod
    async def insert_part_index(cls, part_index: PartsIndex):
        def _():
            milvus_client.insert(
                ColletionEnum.NEWCOLLECTION.value,
                part_index.dict()
            )
        await run_sync(_)

    @classmethod
    async def upsert_data(cls, data: PartsIndex):
        def _():
            milvus_client.upsert(
                collection_name=ColletionEnum.NEWCOLLECTION.value, data=data.dict())
        await run_sync(_)

    @classmethod
    async def upsert_hp_data(cls, data: PartsIndex):
        """高精度集合数据更新/插入"""
        def _():
            milvus_client.upsert(
                collection_name=ColletionEnum.HP_INDEX_COLLECTION.value, data=data.dict())
        await run_sync(_)
    
    @classmethod
    async def delete_hp_part_index(cls, item_id: int):
        """删除高精度集合中的配件索引"""
        def _():
            filter = f""" item_id == {item_id} """
            milvus_client.delete(
                collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                filter=filter
            )
        await run_sync(_)

    @classmethod
    async def list_hp_item_index(cls, item_id_list: list[int] = None, limit=1000):
        """查询高精度集合索引"""
        def _():
            data: dict[int, PartsIndex] = {}
            try:
                if item_id_list is not None and len(item_id_list) > 0:
                    filter = f""" item_id IN [{",".join([str(item_id) for item_id in item_id_list])}] """
                    res = milvus_client.query(
                        collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                        filter=filter,
                        output_fields=["images", "features", "item_id", "id", "created_at"],
                        limit=limit
                    )
                else:
                    res = milvus_client.query(
                        collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                        limit=limit,
                        output_fields=["images", "features", "item_id", "id", "created_at"],
                    )
                for result in res:
                    index = PartsIndex.parse_obj(result)
                    data[index.item_id] = index
                return data
            except Exception as e:
                return data
        return await run_sync(_)

    @classmethod
    async def delete_part_index(cls, item_id: int):
        def _():
            filter = f""" item_id == {item_id} """
            milvus_client.delete(
                collection_name=ColletionEnum.NEWCOLLECTION.value,
                filter=filter
            )

        await run_sync(_)

    # @classmethod
    # def get_image_index(cls, image_id: int):
    #     filter = f""" image_id == {image_id} """

    #     res = milvus_client.query(ColletionEnum.NEWCOLLECTION.value, filter=filter,
    #                               output_fields=["filename", "image_id", "item_id", "id"])

    #     data = []
    #     for result in res:
    #         for hit in result:
    #             if 'entity' not in hit:
    #                 continue
    #             res.append(
    #                 {
    #                     "filename": hit['entity']['filename'],
    #                     "id": hit['entity']['id'],
    #                     "item_id": hit['entity']['item_id'],
    #                     "image_id": image_id,
    #                 }
    #             )
    #     return data

    @classmethod
    async def list_item_index(cls, item_id_list: list[int] = None, limit=1000):
        def _ ():
            data: dict[int, PartsIndex] = {}
            try:

                if item_id_list is not None and len(item_id_list) > 0:
                    filter = f""" item_id IN [{",".join([str(item_id) for item_id in item_id_list])}] """
                    res = milvus_client.query(
                        collection_name=ColletionEnum.NEWCOLLECTION.value,
                        filter=filter,
                        output_fields=["images", "features",
                                       "item_id", "id", "created_at"],
                        limit=limit
                    )
                else:
                    res = milvus_client.query(
                        collection_name=ColletionEnum.NEWCOLLECTION.value,
                        limit=limit,
                        output_fields=["images", "features",
                                       "item_id", "id", "created_at"],
                    )

                for result in res:
                    index = PartsIndex.parse_obj(result)
                    data[index.item_id] = index
                return data
            except Exception as e:
                return data
        return await run_sync(_)

    # @classmethod
    # def insert_parts_feature(cls, feature_list: list[dict]):
    #     if len(feature_list) == 0:
    #         return
    #     milvus_client.insert(
    #         ColletionEnum.FEATURESCOLLECTION.value,
    #         feature_list
    #     )

    # @classmethod
    # def get_parts_features(cls, item_id: int):
    #     filter = f'item_id == {item_id}'
    #     res = milvus_client.query(
    #         collection_name=ColletionEnum.FEATURESCOLLECTION.value,
    #         filter=filter,
    #         output_fields=["feature"],
    #     )
    #     feature_set = set()
    #     for result in res:
    #         feature_set.add(result['feature'])

    #     return feature_set

    # @classmethod
    # def delete_parts_feature(cls, item_id: int, features: list[str]):

    #     if len(features) == 0:
    #         return
    #     quoted_features = "','".join(features)
    #     filter = f'item_id == {item_id} AND features[feature] IN [{quoted_features}]'
    #     milvus_client.delete(ColletionEnum.FEATURESCOLLECTION.value,
    #                          filter=filter)

    # @classmethod
    # async def update_parts_feature(cls, item_id: int, old_feature: str, new_feature: str):
    #     res = milvus_client.query(
    #         collection_name=ColletionEnum.FEATURESCOLLECTION.value,
    #         filter=f""" item_id == {item_id} AND feature == {old_feature}""",
    #         output_fields=["feature", "image_id"],
    #     )
    #     image_id = 0
    #     for result in res:
    #         image_id = result['image_id']
    #     cls.delete_parts_feature(item_id, [old_feature])

    #     cls.insert_parts_feature(
    #         [
    #             {
    #                 "id": get_id(),
    #                 "item_id": item_id,
    #                 "image_id": image_id,
    #                 "feature": new_feature,
    #                 "feature_vector": await cls.embedding_encode(new_feature)
    #             }
    #         ]
    #     )

    @classmethod
    async def get_all_indexed_item_id_list(cls, page: int = 1, per_page: int = 20, limit=1000):
        def _():
            item_id_list: list[int] = []
            res = milvus_client.query(
                ColletionEnum.NEWCOLLECTION.value,
                output_fields=["item_id"],
                offset=(page - 1) * per_page,  # 计算偏移量
                limit=limit)  # 每页数量
            for r in res:
                item_id_list.append(r["item_id"])
            return item_id_list
        return await run_sync(_)

    @classmethod
    async def get_parts_feature_set(cls, item_id: int):

        index_dict = await cls.list_item_index([item_id])
        if item_id not in index_dict:
            return set()

        data = set()
        for f in index_dict[item_id].features:
            data.add(f.feature)
        return data

    @classmethod
    async def feature_text_match_search(cls, query_text, category_filter=None, limit=3):
        """
        执行文本匹配搜索[1](@ref)

        Args:
            query_text: 查询文本
            category_filter: 类别过滤条件
            limit: 返回结果数量
        """

        # 构建过滤条件[1,9](@ref)
        filter_condition = ""
        if category_filter:
            filter_condition = f"category == '{category_filter}'"

        # 方法1: 使用 TEXT_MATCH 进行文本匹配（Milvus 2.5+）[1](@ref)
        try:
            if filter_condition:
                filter_expr = f"TEXT_MATCH(text, '{query_text}') and {filter_condition}"
            else:
                filter_expr = f"TEXT_MATCH(text, '{query_text}')"

            results = await milvus_client.search(
                collection_name=ColletionEnum.FEATURESCOLLECTION.value,
                data=[await cls.embedding_encode(query_text)],
                anns_field="feature_vector",
                filter=filter_expr,
                limit=limit,
                output_fields=["id", "item_id", "image_id", "feature"],
                search_params={"params": {"nprobe": 10}}  # 搜索参数[2](@ref)
            )

        except Exception as e:
            print(f"TEXT_MATCH 搜索失败: {e}")
            # 回退到传统方法
            return await cls.feature_fallback_text_search(query_text, category_filter, limit)

        return results

    @classmethod
    async def feature_fallback_text_search(cls, query_text, category_filter=None, limit=3):
        """传统的向量相似度搜索回退方法[2](@ref)"""

        # 生成查询向量
        query_vector = await cls.embedding_encode(query_text)

        # 构建过滤条件[9](@ref)
        filter_condition = ""
        if category_filter:
            filter_condition = f"category == '{category_filter}'"

        # 执行向量相似度搜索[2,9](@ref)
        results = await milvus_client.search(
            collection_name=ColletionEnum.FEATURESCOLLECTION.value,
            data=[query_vector],
            anns_field="feature_vector",
            filter=filter_condition,
            limit=limit,
            output_fields=["id", "item_id", "image_id", "feature"],
            search_params={"params": {"nprobe": 10}}
        )

        return results

    @classmethod
    async def hybrid_search(cls, query_text, text_weight=0.5, vector_weight=0.5, limit=3):
        """
        混合搜索（文本匹配 + 向量相似度）[5](@ref)

        Args:
            query_text: 查询文本
            text_weight: 文本匹配权重
            vector_weight: 向量相似度权重
            limit: 返回结果数量
        """

        try:
            # 生成查询向量
            query_vector = await cls.embedding_encode(query_text)

            # 执行混合搜索[5](@ref)
            results = milvus_client.search(
                collection_name=ColletionEnum.FEATURESCOLLECTION.value,
                data=[query_vector],
                anns_field="feature_vector",
                filter=f"TEXT_MATCH(text, '{query_text}')",
                limit=limit,
                output_fields=["id", "item_id", "image_id", "feature"],
                search_params={"params": {"nprobe": 10}}
            )

            return results

        except Exception as e:
            print(f"混合搜索失败: {e}")
            return await cls.feature_text_match_search(query_text, limit=limit)

    @classmethod
    async def __init_hp_collection(cls):
        """初始化高精度特征集合 (DINOv2, 1024维)"""
        if milvus_client.has_collection(collection_name=ColletionEnum.HP_INDEX_COLLECTION.value):
            # 检查向量索引是否已存在，若缺失则先补建再加载
            # list_indexes 返回索引名字符串列表，需逐个 describe_index 获取 field_name
            index_names = milvus_client.list_indexes(ColletionEnum.HP_INDEX_COLLECTION.value)
            existing_indexes = set()
            for idx_name in index_names:
                try:
                    info = milvus_client.describe_index(
                        collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                        index_name=idx_name
                    )
                    field = info.get("field_name") if isinstance(info, dict) else getattr(info, "field_name", None)
                    if field:
                        existing_indexes.add(field)
                except Exception:
                    pass
            logger.info(f"HP集合已存在，当前索引字段: {existing_indexes}")
            
            if "images[image_vector]" not in existing_indexes:
                logger.info("补建缺失索引: images[image_vector]")
                idx_params1 = milvus_client.prepare_index_params()
                idx_params1.add_index(
                    field_name="images[image_vector]",
                    index_type="AUTOINDEX",
                    metric_type="MAX_SIM_L2"
                )
                milvus_client.create_index(
                    collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                    index_params=idx_params1
                )
            
            if "features[feature_vector]" not in existing_indexes:
                logger.info("补建缺失索引: features[feature_vector]")
                idx_params2 = milvus_client.prepare_index_params()
                idx_params2.add_index(
                    field_name="features[feature_vector]",
                    index_type="AUTOINDEX",
                    metric_type="MAX_SIM_IP"
                )
                milvus_client.create_index(
                    collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                    index_params=idx_params2
                )
            
            milvus_client.load_collection(ColletionEnum.HP_INDEX_COLLECTION.value)
            return
        
        schema = MilvusClient.create_schema(
            enable_dynamic_field=True,
            auto_id=False
        )
        
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="item_id", datatype=DataType.INT64)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="item_code", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="parent_item_info",
                         datatype=DataType.ARRAY, element_type=DataType.INT64, max_capacity=1000)
        schema.add_field(field_name="vechile_info",
                         datatype=DataType.ARRAY, element_type=DataType.VARCHAR, 
                         max_capacity=1000, max_length=2000)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="updated_at", datatype=DataType.VARCHAR, max_length=2000)
        
        # ===== 高精度图像特征: 1024维 (DINOv2-Large) =====
        image_struct_schema = MilvusClient.create_struct_field_schema()
        image_struct_schema.add_field(field_name="image_id", datatype=DataType.INT64)
        image_struct_schema.add_field(field_name="image_vector",
                                      datatype=DataType.FLOAT_VECTOR, dim=1024, mmap_enabled=True)
        image_struct_schema.add_field(field_name='filename',
                                      datatype=DataType.VARCHAR, max_length=20000)
        image_struct_schema.add_field(field_name='image_index_created',
                                      datatype=DataType.VARCHAR, max_length=20000)
        
        schema.add_field("images", datatype=DataType.ARRAY, element_type=DataType.STRUCT,
                         struct_schema=image_struct_schema, max_capacity=1000)
        
        # 文本特征: 保持512维 (SentenceTransformer)
        feature_struct_schema = MilvusClient.create_struct_field_schema()
        feature_struct_schema.add_field("feature", DataType.VARCHAR, max_length=65535)
        feature_struct_schema.add_field("feature_vector", DataType.FLOAT_VECTOR, mmap_enabled=True, dim=512)
        feature_struct_schema.add_field(field_name='feature_index_created',
                                        datatype=DataType.VARCHAR, max_length=20000)
        
        schema.add_field("features", datatype=DataType.ARRAY, element_type=DataType.STRUCT,
                         struct_schema=feature_struct_schema, max_capacity=1000)
        
        # HNSW 索引配置 (比 AUTOINDEX 更精确)
        index_params = milvus_client.prepare_index_params()
        
        index_params.add_index(field_name="item_id", index_type="AUTOINDEX")
        
        index_params.add_index(
            field_name="images[image_vector]",
            index_type="AUTOINDEX",
            metric_type="MAX_SIM_L2"
        )
        
        index_params.add_index(field_name="parent_item_info", index_type="AUTOINDEX")
        index_params.add_index(field_name="vechile_info", index_type="AUTOINDEX")
        
        index_params.add_index(
            field_name="features[feature_vector]",
            index_type="AUTOINDEX",
            metric_type="MAX_SIM_IP"
        )
        
        # milvus_client.create_collection(
        #     collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
        #     schema=schema,
        #     index_params=index_params
        # )
                # 1. 纯净建表
        milvus_client.create_collection(
            collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
            schema=schema
        )
        
        # 2. 强行针对复杂的 Struct 字段挂载索引 (通过 prepare_index_params 构建)
        idx_params_img = milvus_client.prepare_index_params()
        idx_params_img.add_index(
            field_name="images[image_vector]",
            index_type="AUTOINDEX",
            metric_type="MAX_SIM_L2"
        )
        milvus_client.create_index(
            collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
            index_params=idx_params_img
        )
        
        idx_params_feat = milvus_client.prepare_index_params()
        idx_params_feat.add_index(
            field_name="features[feature_vector]",
            index_type="AUTOINDEX",
            metric_type="MAX_SIM_IP"
        )
        milvus_client.create_index(
            collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
            index_params=idx_params_feat
        )
        
        # 3. 最后再加载进内存
        milvus_client.load_collection(ColletionEnum.HP_INDEX_COLLECTION.value)

        # milvus_client.load_collection(ColletionEnum.HP_INDEX_COLLECTION.value)

    @classmethod
    async def init_collection(cls):
        # 初始化标准集合 (ResNet34, 512维)
        if milvus_client.has_collection(collection_name=ColletionEnum.NEWCOLLECTION.value) is False:
            schema = MilvusClient.create_schema(
                enable_dynamic_field=True,
                auto_id=False
            )
            schema.add_field(
                field_name="id", datatype=DataType.INT64, is_primary=True)

            schema.add_field(field_name="item_id",
                             datatype=DataType.INT64,  is_primary=False)

            schema.add_field(field_name="item_name",
                             datatype=DataType.VARCHAR, max_length=2000)

            schema.add_field(field_name="item_code",
                             datatype=DataType.VARCHAR, max_length=2000)

            schema.add_field(field_name="parent_item_info",
                             datatype=DataType.ARRAY, element_type=DataType.INT64, max_capacity=1000)

            schema.add_field(field_name="vechile_info",
                             datatype=DataType.ARRAY, element_type=DataType.VARCHAR, max_capacity=1000, max_length=2000)

            schema.add_field(field_name="created_at",
                             datatype=DataType.VARCHAR, max_length=2000)

            schema.add_field(field_name="updated_at",
                             datatype=DataType.VARCHAR, max_length=2000)

            image_struct_schema = MilvusClient.create_struct_field_schema()
            image_struct_schema.add_field(field_name="image_id",
                                          datatype=DataType.INT64, is_primary=False)
            image_struct_schema.add_field(field_name="image_vector",
                                          datatype=DataType.FLOAT_VECTOR, dim=512, mmap_enabled=True)
            image_struct_schema.add_field(field_name='filename',
                                          datatype=DataType.VARCHAR, max_length=20000)
            image_struct_schema.add_field(field_name='image_index_created',
                                          datatype=DataType.VARCHAR, max_length=20000)

            schema.add_field("images", datatype=DataType.ARRAY, element_type=DataType.STRUCT,
                             struct_schema=image_struct_schema, max_capacity=1000)

            struct_schema = MilvusClient.create_struct_field_schema()
            struct_schema.add_field(
                "feature", DataType.VARCHAR, max_length=65535)
            struct_schema.add_field(
                "feature_vector", DataType.FLOAT_VECTOR, mmap_enabled=True, dim=512)
            struct_schema.add_field(field_name='feature_index_created',
                                    datatype=DataType.VARCHAR, max_length=20000)

            schema.add_field("features", datatype=DataType.ARRAY, element_type=DataType.STRUCT,
                             struct_schema=struct_schema, max_capacity=1000)

            index_params = milvus_client.prepare_index_params()

            index_params.add_index(
                field_name="item_id",
                index_type="AUTOINDEX"
            )

            index_params.add_index(
                field_name="images[image_vector]",
                index_type="AUTOINDEX",
                metric_type="MAX_SIM_L2",
            )

            index_params.add_index(
                field_name="parent_item_info",
                index_type="AUTOINDEX",
                index_name="parent_item_info_index"
            )
            index_params.add_index(
                field_name="vechile_info",
                index_type="AUTOINDEX",
                index_name="vechile_info_index"
            )

            index_params.add_index(
                field_name="features[feature_vector]",
                index_type="AUTOINDEX",
                metric_type="MAX_SIM_IP",
            )

            milvus_client.create_collection(
                collection_name=ColletionEnum.NEWCOLLECTION.value,
                schema=schema,
                index_params=index_params
            )
        milvus_client.load_collection(ColletionEnum.NEWCOLLECTION.value)
        
        # 初始化高精度集合 (DINOv2, 1024维)
        await cls.__init_hp_collection()

