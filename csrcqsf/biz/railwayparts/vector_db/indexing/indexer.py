"""
向量入库器
"""
import os
from datetime import datetime
from typing import Dict, List, Optional

from csrcqsf.biz.railwayparts.vector_db.models.siglip_extractor import SigLIPExtractor
from csrcqsf.biz.railwayparts.vector_db.models.dinov2_extractor import DINOv2VectorExtractor
from csrcqsf.biz.railwayparts.vector_db.storage.collection_manager import CollectionManager
from csrcqsf.biz.railwayparts.vector_db.data.image_loader import ImageLoader
from csrcqsf.biz.railwayparts.vector_db.preprocessing.sam3_preprocessor import SAM3Preprocessor
from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class VectorIndexer:
    """向量入库核心逻辑"""

    def __init__(
        self,
        siglip_extractor: SigLIPExtractor,
        dinov2_extractor: DINOv2VectorExtractor,
        collection_manager: CollectionManager,
        image_loader: ImageLoader,
        siglip_collection_name: str,
        dinov2_collection_name: str,
        patch_tokens_dir: str,
        sam3_preprocessor: Optional[SAM3Preprocessor] = None
    ):
        """
        初始化向量入库器

        Args:
            siglip_extractor: SigLIP 特征提取器
            dinov2_extractor: DINOv2 特征提取器
            collection_manager: Collection 管理器
            image_loader: 图像加载器
            siglip_collection_name: SigLIP Collection 名称
            dinov2_collection_name: DINOv2 Collection 名称
            patch_tokens_dir: Patch Tokens 存储目录
            sam3_preprocessor: SAM3 预处理器（可选）
        """
        self.siglip_extractor = siglip_extractor
        self.dinov2_extractor = dinov2_extractor
        self.collection_manager = collection_manager
        self.image_loader = image_loader
        self.siglip_collection_name = siglip_collection_name
        self.dinov2_collection_name = dinov2_collection_name
        self.patch_tokens_dir = patch_tokens_dir
        self.sam3_preprocessor = sam3_preprocessor

        # 创建 patch tokens 目录
        os.makedirs(patch_tokens_dir, exist_ok=True)

    def index_item(
        self,
        item_id: int,
        item_name: str,
        item_code: str,
        description: str,
        images: List[Dict]
    ) -> Dict:
        """
        为单个零件的所有图像建立索引

        Args:
            item_id: 零件 ID
            item_name: 零件名称
            item_code: 零件编码
            description: 零件描述
            images: 图像列表 [{'image_id': ..., 'image_url': ...}, ...]

        Returns:
            {
                'item_id': 12345,
                'siglip_ids': [1, 2, 3],
                'dinov2_ids': [4, 5, 6],
                'indexed_image_ids': [67890, 67891],
                'failed_image_ids': []
            }
        """
        logger.info(f"Indexing item {item_id} ({item_name}) with {len(images)} images")

        siglip_records = []
        dinov2_records = []
        indexed_image_ids = []
        failed_image_ids = []

        # 提取文本特征（每个零件只提取一次）
        text_vector = self.siglip_extractor.extract_text_features(description)

        # 处理每张图像
        for img_info in images:
            image_id = img_info['image_id']
            image_url = img_info['image_url']

            try:
                # 加载图像
                image = self.image_loader.load_image(image_url)
                if image is None:
                    logger.warning(f"Failed to load image {image_id}: {image_url}")
                    failed_image_ids.append(image_id)
                    continue

                # SAM3 预处理
                if self.sam3_preprocessor is not None:
                    processed_image = self.sam3_preprocessor.preprocess_image(image, item_name, image_id)
                    if processed_image is not None:
                        image = processed_image
                        logger.debug(f"SAM3 preprocessing applied for image {image_id}")
                    else:
                        logger.warning(f"SAM3 preprocessing failed for {image_id}, using original image")

                # 提取 SigLIP 图像特征
                image_vector = self.siglip_extractor.extract_image_features(image)

                # 提取 DINOv2 特征
                patch_tokens_path = os.path.join(
                    self.patch_tokens_dir,
                    f"item_{item_id}_img_{image_id}.npy"
                )
                global_vector, patch_mean, _ = self.dinov2_extractor.extract_all_features(
                    image,
                    patch_tokens_path
                )

                # 准备 SigLIP 记录
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                siglip_record = {
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_code": item_code,
                    "image_id": image_id,
                    "image_url": image_url,
                    "description": description,
                    "image_vector": image_vector.tolist() if hasattr(image_vector, 'tolist') else list(image_vector),
                    "text_vector": text_vector.tolist() if hasattr(text_vector, 'tolist') else list(text_vector),
                    "created_at": created_at
                }
                siglip_records.append(siglip_record)

                # 准备 DINOv2 记录
                dinov2_record = {
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_code": item_code,
                    "image_id": image_id,
                    "image_url": image_url,
                    "global_vector": global_vector.tolist() if hasattr(global_vector, 'tolist') else list(global_vector),
                    "patch_tokens": patch_mean.tolist() if hasattr(patch_mean, 'tolist') else list(patch_mean),
                    "patch_tokens_path": patch_tokens_path,
                    "created_at": created_at
                }
                dinov2_records.append(dinov2_record)

                indexed_image_ids.append(image_id)
                logger.debug(f"Processed image {image_id}")

            except Exception as e:
                logger.error(f"Failed to process image {image_id}: {e}")
                failed_image_ids.append(image_id)

        # 批量插入 Milvus
        siglip_ids = []
        dinov2_ids = []

        if siglip_records:
            siglip_ids = self.collection_manager.insert_siglip_records(
                self.siglip_collection_name,
                siglip_records
            )
            logger.info(f"Inserted {len(siglip_ids)} SigLIP records")

        if dinov2_records:
            dinov2_ids = self.collection_manager.insert_dinov2_records(
                self.dinov2_collection_name,
                dinov2_records
            )
            logger.info(f"Inserted {len(dinov2_ids)} DINOv2 records")

        return {
            'item_id': item_id,
            'siglip_ids': siglip_ids,
            'dinov2_ids': dinov2_ids,
            'indexed_image_ids': indexed_image_ids,
            'failed_image_ids': failed_image_ids
        }
