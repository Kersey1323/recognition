from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import timm
import torch
from anyio.to_thread import run_sync
from PIL import Image
from pydantic import BaseModel
from pymilvus import DataType, MilvusClient
from sklearn.preprocessing import normalize

from csrcqsf.infra.vector_store.milvus import milvus_client
from csrcqsf.modules.railway_parts.vector_search.config.env_config import get_config
from csrcqsf.modules.railway_parts.vector_search.storage.collection_manager import (
    CollectionManager,
)
from csrcqsf.modules.railway_parts.vector_search.storage.milvus_manager import (
    MilvusManagerV2 as _BaseMilvusManagerV2,
)
from csrcqsf.modules.railway_parts.vector_search.utils.logger import setup_logger
from globals_vars import logger as legacy_logger


vector_logger = setup_logger(__name__)


class ColletionEnum(str, Enum):
    NEWCOLLECTION = "PARTS_INDEX"
    HP_INDEX_COLLECTION = "PARTS_HP_INDEX_V1"


class ImageIndex(BaseModel):
    image_id: int
    filename: str
    image_vector: Any = None
    image_index_created: str | None = None


class FeaturesIndex(BaseModel):
    feature: str
    feature_vector: Any = None
    feature_index_created: str | None = None


class PartsIndex(BaseModel):
    item_id: int = 0
    item_name: str = ""
    item_code: str = ""
    id: int = 0
    images: list[ImageIndex] = []
    features: list[FeaturesIndex] = []
    vechile_info: list[int] = []
    parent_item_info: list[int] = []
    created_at: str | None = None
    updated_at: str | None = None


class DINOv2Extractor:
    MODEL_PATH = "./dinov2_models/dinov2_vitl14_pretrain.pth"

    def __init__(self):
        from torchvision import transforms

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = self._load_local_model()
        self.model.eval()
        self.model = self.model.to(self.device)
        self.preprocess = transforms.Compose(
            [
                transforms.Resize(518, interpolation=transforms.InterpolationMode.BICUBIC),
                transforms.CenterCrop(518),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406],
                    std=[0.229, 0.224, 0.225],
                ),
            ]
        )
        legacy_logger.info(f"DINOv2-Large 模型加载成功 (设备: {self.device})")

    def _load_local_model(self):
        model_path = Path(self.MODEL_PATH)
        if not model_path.exists():
            raise FileNotFoundError(
                f"DINOv2 模型文件不存在: {self.MODEL_PATH}\n"
                "请下载模型文件:\n"
                "  wget https://dl.fbaipublicfiles.com/dinov2/dinov2_vitl14/dinov2_vitl14_pretrain.pth\n"
                "  mkdir -p ./dinov2_models && mv dinov2_vitl14_pretrain.pth ./dinov2_models/"
            )

        try:
            model = timm.create_model(
                "vit_large_patch14_dinov2.lvd142m",
                pretrained=False,
                num_classes=0,
            )
            state_dict = torch.load(self.MODEL_PATH, map_location="cpu")
            if "model" in state_dict:
                state_dict = state_dict["model"]
            model.load_state_dict(state_dict, strict=False)
            return model
        except Exception as exc:
            legacy_logger.warning(f"timm 加载失败，尝试原生方式: {exc}")
            from torch import nn

            class DINOv2ViTLarge(nn.Module):
                def __init__(self):
                    super().__init__()
                    self.vit = timm.create_model(
                        "vit_large_patch14_224",
                        pretrained=False,
                        num_classes=0,
                        img_size=518,
                    )

                def forward(self, x):
                    return self.vit(x)

            model = DINOv2ViTLarge()
            state_dict = torch.load(self.MODEL_PATH, map_location="cpu")
            if "model" in state_dict:
                state_dict = state_dict["model"]
            model.load_state_dict(state_dict, strict=False)
            return model

    def __call__(self, image):
        image = Image.fromarray(image)
        input_tensor = self.preprocess(image).unsqueeze(0).to(self.device)
        with torch.no_grad():
            features = self.model(input_tensor)
        feature_vector = features.cpu().numpy().squeeze()
        return normalize(feature_vector.reshape(1, -1), norm="l2").flatten()

    def __call_batch__(self, images: list):
        tensors = torch.stack([self.preprocess(Image.fromarray(img)) for img in images]).to(
            self.device
        )
        with torch.no_grad():
            features = self.model(tensors)
        return [
            normalize(feature.cpu().numpy().reshape(1, -1), norm="l2").flatten()
            for feature in features
        ]


class MilvusManager:
    _hp_extractor = None

    @classmethod
    def get_hp_extractor(cls):
        if cls._hp_extractor is None:
            cls._hp_extractor = DINOv2Extractor()
        return cls._hp_extractor

    @classmethod
    async def extract_hp_image_tensor(cls, image):
        return await run_sync(lambda: cls.get_hp_extractor()(image))

    @classmethod
    async def extract_hp_image_tensor_batch(cls, images: list):
        return await run_sync(lambda: cls.get_hp_extractor().__call_batch__(images))

    @classmethod
    async def extract_image_tensor(cls, image):
        return await cls.extract_hp_image_tensor(image)

    @classmethod
    async def embedding_encode(cls, text: str):
        return [text]

    @classmethod
    async def insert_part_index(cls, part_index: PartsIndex):
        await run_sync(
            lambda: milvus_client.insert(
                ColletionEnum.NEWCOLLECTION.value,
                part_index.dict(),
            )
        )

    @classmethod
    async def upsert_data(cls, data: PartsIndex):
        await run_sync(
            lambda: milvus_client.upsert(
                collection_name=ColletionEnum.NEWCOLLECTION.value,
                data=data.dict(),
            )
        )

    @classmethod
    async def upsert_hp_data(cls, data: PartsIndex):
        await run_sync(
            lambda: milvus_client.upsert(
                collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                data=data.dict(),
            )
        )

    @classmethod
    async def delete_hp_part_index(cls, item_id: int):
        await run_sync(
            lambda: milvus_client.delete(
                collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                filter=f" item_id == {item_id} ",
            )
        )

    @classmethod
    async def list_hp_item_index(cls, item_id_list: list[int] | None = None, limit: int = 1000):
        def _query():
            data: dict[int, PartsIndex] = {}
            try:
                if item_id_list:
                    query_filter = f" item_id IN [{','.join(str(item_id) for item_id in item_id_list)}] "
                    rows = milvus_client.query(
                        collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                        filter=query_filter,
                        output_fields=["images", "features", "item_id", "id", "created_at"],
                        limit=limit,
                    )
                else:
                    rows = milvus_client.query(
                        collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                        output_fields=["images", "features", "item_id", "id", "created_at"],
                        limit=limit,
                    )
                for row in rows:
                    index = PartsIndex.parse_obj(row)
                    data[index.item_id] = index
            except Exception:
                return data
            return data

        return await run_sync(_query)

    @classmethod
    async def delete_part_index(cls, item_id: int):
        await run_sync(
            lambda: milvus_client.delete(
                collection_name=ColletionEnum.NEWCOLLECTION.value,
                filter=f" item_id == {item_id} ",
            )
        )

    @classmethod
    async def list_item_index(cls, item_id_list: list[int] | None = None, limit: int = 1000):
        def _query():
            data: dict[int, PartsIndex] = {}
            try:
                if item_id_list:
                    query_filter = f" item_id IN [{','.join(str(item_id) for item_id in item_id_list)}] "
                    rows = milvus_client.query(
                        collection_name=ColletionEnum.NEWCOLLECTION.value,
                        filter=query_filter,
                        output_fields=["images", "features", "item_id", "id", "created_at"],
                        limit=limit,
                    )
                else:
                    rows = milvus_client.query(
                        collection_name=ColletionEnum.NEWCOLLECTION.value,
                        output_fields=["images", "features", "item_id", "id", "created_at"],
                        limit=limit,
                    )
                for row in rows:
                    index = PartsIndex.parse_obj(row)
                    data[index.item_id] = index
            except Exception:
                return data
            return data

        return await run_sync(_query)

    @classmethod
    async def get_all_indexed_item_id_list(
        cls,
        page: int = 1,
        per_page: int = 20,
        limit: int = 1000,
    ):
        def _query():
            item_id_list: list[int] = []
            rows = milvus_client.query(
                ColletionEnum.NEWCOLLECTION.value,
                output_fields=["item_id"],
                offset=(page - 1) * per_page,
                limit=limit,
            )
            for row in rows:
                item_id_list.append(row["item_id"])
            return item_id_list

        return await run_sync(_query)

    @classmethod
    async def __init_hp_collection(cls):
        if milvus_client.has_collection(collection_name=ColletionEnum.HP_INDEX_COLLECTION.value):
            index_names = milvus_client.list_indexes(ColletionEnum.HP_INDEX_COLLECTION.value)
            existing_indexes = set()
            for idx_name in index_names:
                try:
                    info = milvus_client.describe_index(
                        collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                        index_name=idx_name,
                    )
                    field = info.get("field_name") if isinstance(info, dict) else getattr(info, "field_name", None)
                    if field:
                        existing_indexes.add(field)
                except Exception:
                    pass

            if "images[image_vector]" not in existing_indexes:
                idx_params = milvus_client.prepare_index_params()
                idx_params.add_index(
                    field_name="images[image_vector]",
                    index_type="AUTOINDEX",
                    metric_type="MAX_SIM_L2",
                )
                milvus_client.create_index(
                    collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                    index_params=idx_params,
                )

            if "features[feature_vector]" not in existing_indexes:
                idx_params = milvus_client.prepare_index_params()
                idx_params.add_index(
                    field_name="features[feature_vector]",
                    index_type="AUTOINDEX",
                    metric_type="MAX_SIM_IP",
                )
                milvus_client.create_index(
                    collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
                    index_params=idx_params,
                )

            milvus_client.load_collection(ColletionEnum.HP_INDEX_COLLECTION.value)
            return

        schema = MilvusClient.create_schema(enable_dynamic_field=True, auto_id=False)
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="item_id", datatype=DataType.INT64)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="item_code", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(
            field_name="parent_item_info",
            datatype=DataType.ARRAY,
            element_type=DataType.INT64,
            max_capacity=1000,
        )
        schema.add_field(
            field_name="vechile_info",
            datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR,
            max_capacity=1000,
            max_length=2000,
        )
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="updated_at", datatype=DataType.VARCHAR, max_length=2000)

        image_struct_schema = MilvusClient.create_struct_field_schema()
        image_struct_schema.add_field(field_name="image_id", datatype=DataType.INT64)
        image_struct_schema.add_field(
            field_name="image_vector",
            datatype=DataType.FLOAT_VECTOR,
            dim=1024,
            mmap_enabled=True,
        )
        image_struct_schema.add_field(field_name="filename", datatype=DataType.VARCHAR, max_length=20000)
        image_struct_schema.add_field(
            field_name="image_index_created",
            datatype=DataType.VARCHAR,
            max_length=20000,
        )
        schema.add_field(
            "images",
            datatype=DataType.ARRAY,
            element_type=DataType.STRUCT,
            struct_schema=image_struct_schema,
            max_capacity=1000,
        )

        feature_struct_schema = MilvusClient.create_struct_field_schema()
        feature_struct_schema.add_field("feature", DataType.VARCHAR, max_length=65535)
        feature_struct_schema.add_field(
            "feature_vector",
            DataType.FLOAT_VECTOR,
            mmap_enabled=True,
            dim=512,
        )
        feature_struct_schema.add_field(
            field_name="feature_index_created",
            datatype=DataType.VARCHAR,
            max_length=20000,
        )
        schema.add_field(
            "features",
            datatype=DataType.ARRAY,
            element_type=DataType.STRUCT,
            struct_schema=feature_struct_schema,
            max_capacity=1000,
        )

        milvus_client.create_collection(
            collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
            schema=schema,
        )

        idx_params_img = milvus_client.prepare_index_params()
        idx_params_img.add_index(
            field_name="images[image_vector]",
            index_type="AUTOINDEX",
            metric_type="MAX_SIM_L2",
        )
        milvus_client.create_index(
            collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
            index_params=idx_params_img,
        )

        idx_params_feat = milvus_client.prepare_index_params()
        idx_params_feat.add_index(
            field_name="features[feature_vector]",
            index_type="AUTOINDEX",
            metric_type="MAX_SIM_IP",
        )
        milvus_client.create_index(
            collection_name=ColletionEnum.HP_INDEX_COLLECTION.value,
            index_params=idx_params_feat,
        )
        milvus_client.load_collection(ColletionEnum.HP_INDEX_COLLECTION.value)

    @classmethod
    async def init_collection(cls):
        if not milvus_client.has_collection(collection_name=ColletionEnum.NEWCOLLECTION.value):
            schema = MilvusClient.create_schema(enable_dynamic_field=True, auto_id=False)
            schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
            schema.add_field(field_name="item_id", datatype=DataType.INT64, is_primary=False)
            schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=2000)
            schema.add_field(field_name="item_code", datatype=DataType.VARCHAR, max_length=2000)
            schema.add_field(
                field_name="parent_item_info",
                datatype=DataType.ARRAY,
                element_type=DataType.INT64,
                max_capacity=1000,
            )
            schema.add_field(
                field_name="vechile_info",
                datatype=DataType.ARRAY,
                element_type=DataType.VARCHAR,
                max_capacity=1000,
                max_length=2000,
            )
            schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=2000)
            schema.add_field(field_name="updated_at", datatype=DataType.VARCHAR, max_length=2000)

            image_struct_schema = MilvusClient.create_struct_field_schema()
            image_struct_schema.add_field(field_name="image_id", datatype=DataType.INT64, is_primary=False)
            image_struct_schema.add_field(
                field_name="image_vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=512,
                mmap_enabled=True,
            )
            image_struct_schema.add_field(field_name="filename", datatype=DataType.VARCHAR, max_length=20000)
            image_struct_schema.add_field(
                field_name="image_index_created",
                datatype=DataType.VARCHAR,
                max_length=20000,
            )
            schema.add_field(
                "images",
                datatype=DataType.ARRAY,
                element_type=DataType.STRUCT,
                struct_schema=image_struct_schema,
                max_capacity=1000,
            )

            struct_schema = MilvusClient.create_struct_field_schema()
            struct_schema.add_field("feature", DataType.VARCHAR, max_length=65535)
            struct_schema.add_field(
                "feature_vector",
                DataType.FLOAT_VECTOR,
                mmap_enabled=True,
                dim=512,
            )
            struct_schema.add_field(
                field_name="feature_index_created",
                datatype=DataType.VARCHAR,
                max_length=20000,
            )
            schema.add_field(
                "features",
                datatype=DataType.ARRAY,
                element_type=DataType.STRUCT,
                struct_schema=struct_schema,
                max_capacity=1000,
            )

            index_params = milvus_client.prepare_index_params()
            index_params.add_index(field_name="item_id", index_type="AUTOINDEX")
            index_params.add_index(
                field_name="images[image_vector]",
                index_type="AUTOINDEX",
                metric_type="MAX_SIM_L2",
            )
            index_params.add_index(
                field_name="parent_item_info",
                index_type="AUTOINDEX",
                index_name="parent_item_info_index",
            )
            index_params.add_index(
                field_name="vechile_info",
                index_type="AUTOINDEX",
                index_name="vechile_info_index",
            )
            index_params.add_index(
                field_name="features[feature_vector]",
                index_type="AUTOINDEX",
                metric_type="MAX_SIM_IP",
            )
            milvus_client.create_collection(
                collection_name=ColletionEnum.NEWCOLLECTION.value,
                schema=schema,
                index_params=index_params,
            )

        milvus_client.load_collection(ColletionEnum.NEWCOLLECTION.value)
        await cls.__init_hp_collection()


class MilvusManagerV2(_BaseMilvusManagerV2):
    _instance: Optional["MilvusManagerV2"] = None

    @classmethod
    def get_instance(
        cls,
        config_path: str | None = None,
        db_config_path: str | None = None,
        enable_sam3: bool = True,
    ) -> "MilvusManagerV2":
        if cls._instance is None:
            cls._instance = cls(
                config_path=config_path,
                db_config_path=db_config_path,
                enable_sam3=enable_sam3,
            )
        return cls._instance

    async def _ensure_initialized(self):
        return self

    async def create_collections(self):
        return await run_sync(super().create_collections)

    async def drop_collections(self):
        return await run_sync(super().drop_collections)

    async def search_by_text(self, query_text: str, top_k: int = 5):
        return await super().search_by_text(query_text, top_k=top_k)


@dataclass
class CompatImageIndex:
    image_id: int
    filename: str
    image_vector: Any = None
    image_index_created: str | None = None


@dataclass
class CompatFeaturesIndex:
    feature: str
    feature_vector: Any = None
    feature_index_created: str | None = None


@dataclass
class CompatPartsIndex:
    item_id: int = 0
    item_name: str = ""
    item_code: str = ""
    id: int = 0
    images: list[CompatImageIndex] = field(default_factory=list)
    features: list[CompatFeaturesIndex] = field(default_factory=list)
    vechile_info: list[int] = field(default_factory=list)
    parent_item_info: list[int] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class MilvusStateManagerV2:
    def __init__(self):
        env_config = get_config()
        self.siglip_collection = env_config.siglip_collection_name
        self.dinov2_collection = env_config.dinov2_collection_name
        self.collection_manager = CollectionManager(
            host=env_config.milvus_host,
            port=env_config.milvus_port,
        )

    def get_statistics_snapshot(self) -> dict[str, object]:
        siglip_item_images = self.collection_manager.get_collection_item_image_ids(
            self.siglip_collection
        )
        dinov2_item_images = self.collection_manager.get_collection_item_image_ids(
            self.dinov2_collection
        )
        return {
            "siglip_count": sum(len(image_ids) for image_ids in siglip_item_images.values()),
            "dinov2_count": sum(len(image_ids) for image_ids in dinov2_item_images.values()),
            "siglip_item_ids": set(siglip_item_images.keys()),
            "dinov2_item_ids": set(dinov2_item_images.keys()),
        }

    def get_item_index_state_snapshot(self) -> dict[int, dict[str, int]]:
        siglip_item_images = self.collection_manager.get_collection_item_image_ids(
            self.siglip_collection
        )
        dinov2_item_images = self.collection_manager.get_collection_item_image_ids(
            self.dinov2_collection
        )

        snapshot: dict[int, dict[str, int]] = {}
        item_ids = set(siglip_item_images.keys()) | set(dinov2_item_images.keys())
        for item_id in item_ids:
            indexed_images = siglip_item_images.get(item_id, set()) & dinov2_item_images.get(
                item_id,
                set(),
            )
            snapshot[item_id] = {
                "has_v2_index": 1 if indexed_images else 0,
                "v2_indexed_image_num": len(indexed_images),
            }
        return snapshot

    def list_item_index(
        self,
        item_id_list: list[int] | None = None,
        limit: int = 1000,
    ) -> dict[int, CompatPartsIndex]:
        data: dict[int, CompatPartsIndex] = {}
        try:
            candidate_item_ids = item_id_list or []
            if not candidate_item_ids:
                state_snapshot = self.get_item_index_state_snapshot()
                candidate_item_ids = sorted(state_snapshot.keys())[:limit]

            for item_id in candidate_item_ids[:limit]:
                indexed_images = self.get_indexed_images_by_item_id(int(item_id))
                if not indexed_images:
                    continue

                metadata_rows = self.collection_manager.client.query(
                    collection_name=self.siglip_collection,
                    filter=f"item_id == {int(item_id)}",
                    output_fields=["item_id", "item_name", "item_code", "description"],
                    limit=1,
                )
                metadata = metadata_rows[0] if metadata_rows else {}

                features: list[CompatFeaturesIndex] = []
                description = metadata.get("description")
                if description:
                    features.append(CompatFeaturesIndex(feature=str(description)))

                data[int(item_id)] = CompatPartsIndex(
                    item_id=int(item_id),
                    item_name=str(metadata.get("item_name") or ""),
                    item_code=str(metadata.get("item_code") or ""),
                    images=[
                        CompatImageIndex(image_id=image_id, filename=image_url)
                        for image_id, image_url in sorted(indexed_images.items())
                    ],
                    features=features,
                )
        except Exception:
            return data
        return data

    def get_all_indexed_item_id_list(
        self,
        page: int = 1,
        per_page: int = 20,
        limit: int = 1000,
    ) -> list[int]:
        snapshot = self.get_item_index_state_snapshot()
        item_ids = sorted(
            item_id
            for item_id, state in snapshot.items()
            if int(state.get("has_v2_index", 0) or 0) == 1
        )
        start = max(page - 1, 0) * per_page
        end = min(start + per_page, limit)
        return item_ids[start:end]

    def delete_item_index(self, item_id: int) -> dict[str, int]:
        return {
            "siglip_deleted": self.collection_manager.delete_by_item_id(
                self.siglip_collection,
                item_id,
            ),
            "dinov2_deleted": self.collection_manager.delete_by_item_id(
                self.dinov2_collection,
                item_id,
            ),
        }

    def get_indexed_images_by_item_id(self, item_id: int) -> dict[int, str]:
        siglip_images = self.collection_manager.get_collection_image_records(
            self.siglip_collection,
            item_id,
        )
        dinov2_images = self.collection_manager.get_collection_image_records(
            self.dinov2_collection,
            item_id,
        )
        indexed_image_ids = set(siglip_images.keys()) & set(dinov2_images.keys())
        return {
            image_id: siglip_images.get(image_id) or dinov2_images.get(image_id, "")
            for image_id in indexed_image_ids
        }

    def create_collections(self):
        vector_logger.info("Creating collections via lightweight state manager...")
        self.collection_manager.create_siglip_collection(self.siglip_collection)
        self.collection_manager.create_dinov2_collection(self.dinov2_collection)

    def drop_collections(self):
        vector_logger.warning("Dropping collections via lightweight state manager...")
        if self.collection_manager.collection_exists(self.siglip_collection):
            self.collection_manager.drop_collection(self.siglip_collection)
        if self.collection_manager.collection_exists(self.dinov2_collection):
            self.collection_manager.drop_collection(self.dinov2_collection)
