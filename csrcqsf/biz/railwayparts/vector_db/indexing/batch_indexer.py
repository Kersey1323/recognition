"""
批量入库协调器
"""
import json
import os
from typing import List, Optional, Dict
from tqdm import tqdm

from csrcqsf.biz.railwayparts.vector_db.indexing.indexer import VectorIndexer
from csrcqsf.biz.railwayparts.vector_db.data.db_connector import DatabaseConnector
from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class BatchIndexer:
    """批量入库协调器"""

    def __init__(
        self,
        indexer: VectorIndexer,
        db_connector: DatabaseConnector,
        checkpoint_file: str = "vector_db/checkpoint.json"
    ):
        """
        初始化批量入库协调器

        Args:
            indexer: 向量入库器
            db_connector: 数据库连接器
            checkpoint_file: 检查点文件路径
        """
        self.indexer = indexer
        self.db_connector = db_connector
        self.checkpoint_file = checkpoint_file

    def build_index(
        self,
        item_ids: Optional[List[int]] = None,
        limit: Optional[int] = None,
        resume: bool = False
    ) -> Dict:
        """
        批量构建索引

        Args:
            item_ids: 指定零件 ID 列表（可选）
            limit: 限制处理数量（可选）
            resume: 是否从检查点恢复

        Returns:
            统计信息字典
        """
        logger.info("Starting batch indexing")

        # 加载检查点
        processed_item_ids = set()
        if resume and os.path.exists(self.checkpoint_file):
            processed_item_ids = self._load_checkpoint()
            logger.info(f"Resuming from checkpoint: {len(processed_item_ids)} items already processed")

        # 读取零件数据
        logger.info("Fetching items from database")
        items = self.db_connector.fetch_items_with_images(item_ids, limit)
        logger.info(f"Fetched {len(items)} items")

        # 过滤已处理的零件
        if resume:
            items = [item for item in items if item['item_id'] not in processed_item_ids]
            logger.info(f"Remaining items to process: {len(items)}")

        # 统计信息
        stats = {
            'total_items': len(items),
            'success_items': 0,
            'failed_items': 0,
            'total_images': 0,
            'success_images': 0,
            'failed_images': 0,
            'failed_item_ids': []
        }

        # 批量处理
        for item in tqdm(items, desc="Indexing items"):
            try:
                result = self.indexer.index_item(
                    item_id=item['item_id'],
                    item_name=item['item_name'],
                    item_code=item['item_code'],
                    description=item['description'],
                    images=item['images']
                )

                # 更新统计
                stats['total_images'] += len(item['images'])
                stats['success_images'] += len(result['indexed_image_ids'])
                stats['failed_images'] += len(result['failed_image_ids'])

                if result['indexed_image_ids']:
                    stats['success_items'] += 1
                else:
                    stats['failed_items'] += 1
                    stats['failed_item_ids'].append(item['item_id'])

                # 保存检查点
                processed_item_ids.add(item['item_id'])
                self._save_checkpoint(processed_item_ids)

            except Exception as e:
                logger.error(f"Failed to index item {item['item_id']}: {e}")
                stats['failed_items'] += 1
                stats['failed_item_ids'].append(item['item_id'])

        # 输出统计信息
        logger.info("=" * 60)
        logger.info("Batch indexing completed")
        logger.info(f"Total items: {stats['total_items']}")
        logger.info(f"Success items: {stats['success_items']}")
        logger.info(f"Failed items: {stats['failed_items']}")
        logger.info(f"Total images: {stats['total_images']}")
        logger.info(f"Success images: {stats['success_images']}")
        logger.info(f"Failed images: {stats['failed_images']}")
        if stats['failed_item_ids']:
            logger.info(f"Failed item IDs: {stats['failed_item_ids']}")
        logger.info("=" * 60)

        return stats

    def _load_checkpoint(self) -> set:
        """
        加载检查点

        Returns:
            已处理的零件 ID 集合
        """
        try:
            with open(self.checkpoint_file, 'r') as f:
                data = json.load(f)
                return set(data.get('processed_item_ids', []))
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return set()

    def _save_checkpoint(self, processed_item_ids: set):
        """
        保存检查点

        Args:
            processed_item_ids: 已处理的零件 ID 集合
        """
        try:
            os.makedirs(os.path.dirname(self.checkpoint_file), exist_ok=True)
            with open(self.checkpoint_file, 'w') as f:
                json.dump({
                    'processed_item_ids': list(processed_item_ids)
                }, f)
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")

    def clear_checkpoint(self):
        """清除检查点文件"""
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)
            logger.info("Checkpoint cleared")
