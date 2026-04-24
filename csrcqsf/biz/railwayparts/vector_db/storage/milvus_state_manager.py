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
        siglip_count = self.collection_manager.get_collection_entity_count(
            self.siglip_collection
        )
        dinov2_count = self.collection_manager.get_collection_entity_count(
            self.dinov2_collection
        )
        siglip_item_ids = self.collection_manager.iter_collection_item_ids(
            self.siglip_collection
        )
        dinov2_item_ids = self.collection_manager.iter_collection_item_ids(
            self.dinov2_collection
        )
        return {
            "siglip_count": siglip_count,
            "dinov2_count": dinov2_count,
            "siglip_item_ids": siglip_item_ids,
            "dinov2_item_ids": dinov2_item_ids,
        }

    def get_item_index_state_snapshot(self) -> dict[int, dict[str, int]]:
        """按 item_id 聚合当前 V2 索引状态。"""
        siglip_counts = self.collection_manager.get_collection_item_counts(
            self.siglip_collection
        )
        dinov2_item_ids = self.collection_manager.iter_collection_item_ids(
            self.dinov2_collection
        )

        snapshot: dict[int, dict[str, int]] = {}
        for item_id, image_count in siglip_counts.items():
            snapshot[item_id] = {
                "has_v2_index": 1 if item_id in dinov2_item_ids else 0,
                "v2_indexed_image_num": image_count if item_id in dinov2_item_ids else 0,
            }

        for item_id in dinov2_item_ids:
            snapshot.setdefault(
                item_id,
                {
                    "has_v2_index": 0,
                    "v2_indexed_image_num": 0,
                },
            )

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
