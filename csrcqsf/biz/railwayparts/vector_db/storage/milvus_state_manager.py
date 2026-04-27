"""
V2 Milvus 轻量状态管理器
只负责 collection 状态与管理操作，不加载模型。
"""

from csrcqsf.biz.railwayparts.vector_db.config.env_config import get_config
from csrcqsf.biz.railwayparts.vector_db.storage.collection_manager import (
    CollectionManager,
)
from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


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
