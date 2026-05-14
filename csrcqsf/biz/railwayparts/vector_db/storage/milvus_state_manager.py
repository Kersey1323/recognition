"""
V2 Milvus 轻量状态管理器
只负责 collection 状态与管理操作，不加载模型。
"""

from dataclasses import dataclass, field
from typing import Any

from csrcqsf.biz.railwayparts.vector_db.config.env_config import get_config
from csrcqsf.biz.railwayparts.vector_db.storage.collection_manager import (
    CollectionManager,
)
from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


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
    """只负责 V2 collection 状态和管理操作的轻量 manager。"""

    def __init__(self):
        env_config = get_config()
        self.siglip_collection = env_config.siglip_collection_name
        self.dinov2_collection = env_config.dinov2_collection_name
        self.collection_manager = CollectionManager(
            host=env_config.milvus_host,
            port=env_config.milvus_port,
        )

    def get_statistics_snapshot(self) -> dict[str, object]:
        """获取 V2 collection 的统计快照。"""
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
        """按 item_id 聚合当前 V2 索引状态。"""
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
                "has_v2_index": 1 if len(indexed_images) > 0 else 0,
                "v2_indexed_image_num": len(indexed_images),
            }

        return snapshot

    def list_item_index(
        self,
        item_id_list: list[int] | None = None,
        limit: int = 1000,
    ) -> dict[int, CompatPartsIndex]:
        """
        提供给旧业务读取侧的兼容聚合视图。

        基于 V2 collection 按 item_id 聚合，不加载旧 V1 collection。
        """
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
        """返回当前已具备完整 V2 索引的 item_id 列表。"""
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
        """删除指定 item_id 在 V2 collections 中的所有向量记录。"""
        return {
            "siglip_deleted": self.collection_manager.delete_by_item_id(
                self.siglip_collection, item_id
            ),
            "dinov2_deleted": self.collection_manager.delete_by_item_id(
                self.dinov2_collection, item_id
            ),
        }

    def get_indexed_images_by_item_id(self, item_id: int) -> dict[int, str]:
        """
        获取指定 item_id 当前完成 V2 索引的图片集合。

        只有同时存在于 SigLIP 和 DINOv2 两个 collection 的图片，
        才视为完成 V2 索引。
        """
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
        """创建所有 V2 collections。"""
        logger.info("Creating collections via lightweight state manager...")
        self.collection_manager.create_siglip_collection(self.siglip_collection)
        self.collection_manager.create_dinov2_collection(self.dinov2_collection)

    def drop_collections(self):
        """删除所有 V2 collections。"""
        logger.warning("Dropping collections via lightweight state manager...")
        if self.collection_manager.collection_exists(self.siglip_collection):
            self.collection_manager.drop_collection(self.siglip_collection)
        if self.collection_manager.collection_exists(self.dinov2_collection):
            self.collection_manager.drop_collection(self.dinov2_collection)
