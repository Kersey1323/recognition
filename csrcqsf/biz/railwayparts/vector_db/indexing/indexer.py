"""
向量入库器
"""
import os
from datetime import datetime
from typing import Dict, List, Optional

from csrcqsf.biz.railwayparts.vector_db.storage.collection_manager import CollectionManager
from csrcqsf.biz.railwayparts.vector_db.data.image_loader import ImageLoader
from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger
from csrcqsf.biz.model_client import get_model_client, ModelServiceClient

logger = setup_logger(__name__)


class VectorIndexer:
    """向量入库核心逻辑"""

    def __init__(
        self,
        collection_manager: CollectionManager,
        image_loader: ImageLoader,
        siglip_collection_name: str,
        dinov2_collection_name: str,
        patch_tokens_dir: str,
        enable_sam3: bool = True,
        model_client: Optional[ModelServiceClient] = None,
    ):
        self.model_client = model_client or get_model_client()
        self.collection_manager = collection_manager
        self.image_loader = image_loader
        self.siglip_collection_name = siglip_collection_name
        self.dinov2_collection_name = dinov2_collection_name
        self.patch_tokens_dir = patch_tokens_dir
        self.enable_sam3 = enable_sam3

        os.makedirs(patch_tokens_dir, exist_ok=True)

    async def index_item(
        self,
        item_id: int,
        item_name: str,
        item_code: str,
        description: str,
        images: List[Dict]
    ) -> Dict:
        logger.info(f"Indexing item {item_id} ({item_name}) with {len(images)} images")

        siglip_records = []
        dinov2_records = []
        indexed_image_ids = []
        failed_image_ids = []

        text_vector = await self.model_client.siglip_text_features(description)

        for img_info in images:
            image_id = img_info['image_id']
            image_url = img_info['image_url']

            try:
                image = self.image_loader.load_image(image_url)
                if image is None:
                    logger.warning(f"Failed to load image {image_id}: {image_url}")
                    failed_image_ids.append(image_id)
                    continue

                if self.enable_sam3:
                    processed_image = await self.model_client.sam3_preprocess(image, item_name)
                    if processed_image is not None:
                        image = processed_image
                        logger.debug(f"SAM3 preprocessing applied for image {image_id}")
                    else:
                        logger.warning(f"SAM3 preprocessing failed for {image_id}, using original image")

                image_vector = await self.model_client.siglip_image_features(image)

                global_vector = await self.model_client.dinov2_global_vector(image)
                patch_tokens = await self.model_client.dinov2_patch_tokens(image)
                patch_mean = patch_tokens.mean(axis=0)

                patch_tokens_path = os.path.join(
                    self.patch_tokens_dir,
                    f"item_{item_id}_img_{image_id}.npy"
                )
                os.makedirs(os.path.dirname(patch_tokens_path), exist_ok=True)
                import numpy as np
                np.save(patch_tokens_path, patch_tokens)

                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                siglip_records.append({
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_code": item_code,
                    "image_id": image_id,
                    "image_url": image_url,
                    "description": description,
                    "image_vector": image_vector.tolist(),
                    "text_vector": text_vector.tolist(),
                    "created_at": created_at,
                })

                dinov2_records.append({
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_code": item_code,
                    "image_id": image_id,
                    "image_url": image_url,
                    "global_vector": global_vector.tolist(),
                    "patch_tokens": patch_mean.tolist(),
                    "patch_tokens_path": patch_tokens_path,
                    "created_at": created_at,
                })

                indexed_image_ids.append(image_id)
                logger.debug(f"Processed image {image_id}")

            except Exception as e:
                logger.error(f"Failed to process image {image_id}: {e}")
                failed_image_ids.append(image_id)

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
