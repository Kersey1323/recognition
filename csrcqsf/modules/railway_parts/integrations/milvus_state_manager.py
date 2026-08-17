from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from anyio.to_thread import run_sync
from pydantic import BaseModel

from csrcqsf.infra.vector_store.milvus import milvus_client
from csrcqsf.modules.railway_parts.vector_search.config.env_config import get_config
from csrcqsf.modules.railway_parts.vector_search.storage.collection_manager import (
    CollectionManager,
)
from csrcqsf.modules.railway_parts.vector_search.storage.milvus_manager import (
    MilvusManagerV2 as _BaseMilvusManagerV2,
)
from csrcqsf.modules.railway_parts.vector_search.utils.logger import setup_logger


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


class MilvusManager:
    _hp_extractor = None

    @classmethod
    async def extract_hp_image_tensor(cls, image):
        raise RuntimeError("主业务已移除本地 DINOv2 特征提取，请使用独立模型服务")

    @classmethod
    async def extract_hp_image_tensor_batch(cls, images: list):
        raise RuntimeError("主业务已移除本地 DINOv2 特征提取，请使用独立模型服务")

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
                    query_filter = (
                        f" item_id IN [{','.join(str(item_id) for item_id in item_id_list)}] "
                    )
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
                    query_filter = (
                        f" item_id IN [{','.join(str(item_id) for item_id in item_id_list)}] "
                    )
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


class MilvusManagerV2(_BaseMilvusManagerV2):
    _instance: Optional["MilvusManagerV2"] = None

    @classmethod
    def get_instance(
        cls,
        config_path: str | None = None,
        db_config_path: str | None = None,
    ) -> "MilvusManagerV2":
        if cls._instance is None:
            cls._instance = cls(
                config_path=config_path,
                db_config_path=db_config_path,
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

    def delete_item_image_index(self, item_id: int, image_id: int) -> dict[str, int]:
        siglip_deleted = self.collection_manager.delete_by_item_image_id(
            self.siglip_collection,
            item_id,
            image_id,
        )
        dinov2_deleted = self.collection_manager.delete_by_item_image_id(
            self.dinov2_collection,
            item_id,
            image_id,
        )
        return {
            "siglip_deleted": siglip_deleted,
            "dinov2_deleted": dinov2_deleted,
            "total_deleted": siglip_deleted + dinov2_deleted,
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
