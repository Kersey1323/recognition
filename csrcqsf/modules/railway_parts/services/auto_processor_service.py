"""自动配件处理器 - 全自动分割 + 高精度特征提取 + 建立索引。"""

from __future__ import annotations

import os
from datetime import datetime

import cv2
import numpy as np
from anyio.to_thread import run_sync
from bfrcommon.common import date_to_str
from bfrcommon.snowflake import get_id
from pydantic import BaseModel
from segment_anything import SamAutomaticMaskGenerator

from csrcqsf.core.logger import CodeTimer
from csrcqsf.core.settings import minio_bucket, temp_dir
from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.infra.storage.minio import minio_instance
from csrcqsf.models.orm.item import Items, ItemsParent, ItemsVechile
from csrcqsf.models.orm.sgo import (
    ImageSourceType,
    SegmentedImage,
    SegmentStatus,
    SgoItemImages,
)
from csrcqsf.modules.image.services import SegmentBiz
from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import (
    FeaturesIndex,
    ImageIndex,
    MilvusManager,
    PartsIndex,
)
from globals_vars import logger


class AutoSegmentResult(BaseModel):
    item_id: str = ""
    total_baseinfo_images: int = 0
    segmented_count: int = 0
    indexed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    message: str = ""


class AutoPartProcessor:
    _mask_generator = None

    @classmethod
    def get_mask_generator(cls):
        if cls._mask_generator is None and SegmentBiz.sam_model is not None:
            cls._mask_generator = SamAutomaticMaskGenerator(
                SegmentBiz.sam_model,
                points_per_side=32,
                pred_iou_thresh=0.88,
                stability_score_thresh=0.95,
                min_mask_region_area=500,
            )
        return cls._mask_generator

    @classmethod
    def _segment_main_object(cls, image: np.ndarray) -> tuple[np.ndarray, dict]:
        mask_generator = cls.get_mask_generator()
        if mask_generator is None:
            return image, {
                "bbox": [0, 0, image.shape[1], image.shape[0]],
                "area": image.shape[0] * image.shape[1],
            }

        with CodeTimer(name="SAM自动分割"):
            masks = mask_generator.generate(image)

        if len(masks) == 0:
            return image, {
                "bbox": [0, 0, image.shape[1], image.shape[0]],
                "area": image.shape[0] * image.shape[1],
            }

        masks = sorted(masks, key=lambda item: item["area"], reverse=True)
        main_mask = masks[0]
        mask = main_mask["segmentation"]
        x, y, w, h = [int(value) for value in main_mask["bbox"]]

        masked_image = image.copy()
        masked_image[~mask] = 255
        cropped = masked_image[y : y + h, x : x + w]
        return cropped, main_mask

    @classmethod
    async def _upload_segmented_image(cls, image: np.ndarray, item_id: int, source_image_id: int) -> str:
        filename = f"segmented/{item_id}/{source_image_id}_{get_id()}.jpg"
        local_path = os.path.join(temp_dir, f"seg_{get_id()}.jpg")
        try:
            cv2.imwrite(local_path, image)
            await run_sync(minio_instance.upload_file, minio_bucket, filename, local_path)
            return f"{minio_bucket}/{filename}"
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

    @classmethod
    async def auto_segment_by_item_id(cls, item_id: int, rebuild: bool = False) -> AutoSegmentResult:
        from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager

        result = AutoSegmentResult(item_id=str(item_id))
        try:
            async with SessionLocal() as session:
                item = await Items.get_item_by_id(session, item_id)
                if item is None:
                    result.message = f"配件不存在: {item_id}"
                    return result

                if rebuild:
                    await SegmentedImage.delete_by_item_id(session, item_id)
                    await session.commit()

                all_images = await SgoItemImages.list_item_images_by_item_id(session, item_id)
                baseinfo_images = [
                    image for image in all_images if image.image_source == ImageSourceType.BASEINFO
                ]
                if len(baseinfo_images) == 0:
                    result.message = (
                        f"配件 item_code:{item.item_code} ,配件名:{item.item_name} 没有找到 BASEINFO 类型的图片"
                    )
                    return result

                result.total_baseinfo_images = len(baseinfo_images)
                existing_records = await SegmentedImage.list_by_item_id(session, item_id)
                existing_source_ids = {record.source_image_id for record in existing_records}
                new_images = [image for image in baseinfo_images if image.id not in existing_source_ids]
                if len(new_images) == 0:
                    result.skipped_count = len(baseinfo_images)
                    result.message = "所有图片已处理过，无需重新分割"
                    return result

                parent_list = await ItemsParent.list_parent_item_by_item_id(session, item_id)
                parent_item_ids = [parent.parent_item_id for parent in parent_list]
                vechile_list = await ItemsVechile.list_item_vechile_info_by_item_id(session, item_id)
                vechile_ids = [vechile.vechile_id for vechile in vechile_list]

            segmented_records = []
            successful_features = []
            for image_record in new_images:
                record = SegmentedImage(
                    id=get_id(),
                    item_id=item_id,
                    source_image_id=image_record.id,
                    source_image_url=image_record.image_url,
                    status=SegmentStatus.PENDING,
                )
                try:
                    image = await RailwayPartsManager.get_image_from_oss(image_record.image_url)
                    if image is None:
                        record.status = SegmentStatus.FAILED
                        record.error_message = "图片加载失败"
                        segmented_records.append(record)
                        result.failed_count += 1
                        continue

                    segmented_image, mask_info = await run_sync(cls._segment_main_object, image)
                    bbox = mask_info.get("bbox", [0, 0, 0, 0])
                    area = mask_info.get("area", 0)
                    segmented_url = await cls._upload_segmented_image(
                        segmented_image,
                        item_id,
                        image_record.id,
                    )
                    feature_vector = await MilvusManager.extract_hp_image_tensor(segmented_image)

                    record.segmented_image_url = segmented_url
                    record.status = SegmentStatus.SUCCESS
                    record.mask_area = int(area)
                    record.bbox_x = int(bbox[0])
                    record.bbox_y = int(bbox[1])
                    record.bbox_w = int(bbox[2])
                    record.bbox_h = int(bbox[3])
                    segmented_records.append(record)
                    successful_features.append((record.id, feature_vector, segmented_url))
                    result.segmented_count += 1
                    logger.info(f"分割成功: item={item_id}, image={image_record.id}, area={area}")
                except Exception as exc:
                    logger.error(f"分割失败: item={item_id}, image={image_record.id}, error={exc}")
                    record.status = SegmentStatus.FAILED
                    record.error_message = str(exc)
                    segmented_records.append(record)
                    result.failed_count += 1

            async with SessionLocal() as session:
                await SegmentedImage.batch_create(session, segmented_records)
                await session.commit()

            if len(successful_features) > 0:
                try:
                    index_dict = await MilvusManager.list_hp_item_index([item_id])
                    existing_index = index_dict.get(item_id)
                    if existing_index is None:
                        existing_index = PartsIndex(
                            item_id=item_id,
                            id=get_id(),
                            created_at=date_to_str(datetime.now()),
                        )

                    existing_index.updated_at = date_to_str(datetime.now())
                    existing_index.item_name = item.item_name
                    existing_index.item_code = item.item_code
                    existing_index.parent_item_info = parent_item_ids
                    existing_index.vechile_info = vechile_ids

                    indexed_record_ids = []
                    for record_id, feature_vector, segmented_url in successful_features:
                        image_index = ImageIndex(
                            image_id=record_id,
                            filename=segmented_url,
                            image_vector=feature_vector,
                            image_index_created=date_to_str(datetime.now()),
                        )
                        existing_index.images.append(image_index)
                        indexed_record_ids.append(record_id)

                    await MilvusManager.upsert_hp_data(existing_index)
                    async with SessionLocal() as session:
                        await SegmentedImage.mark_indexed(session, indexed_record_ids)
                        await Items.update_items_index(
                            session,
                            item_id,
                            image_index_num=len(existing_index.images),
                            feature_index_num=len(existing_index.features),
                        )
                        await session.commit()
                    result.indexed_count = len(indexed_record_ids)
                except Exception as exc:
                    logger.error(f"建立索引失败: {exc}")
                    result.message = f"分割成功但索引失败: {exc}"
                    return result

            result.message = (
                f"处理完成: 分割 {result.segmented_count}, 索引 {result.indexed_count}, 失败 {result.failed_count}"
            )
        except Exception as exc:
            logger.error(f"自动分割处理失败: {exc}")
            result.message = f"处理失败: {exc}"
        return result

    @classmethod
    async def list_segmented_images(cls, item_id: int) -> list[dict]:
        async with SessionLocal() as session:
            records = await SegmentedImage.list_by_item_id(session, item_id)
            return [
                {
                    "id": str(record.id),
                    "source_image_url": record.source_image_url,
                    "segmented_image_url": record.segmented_image_url,
                    "status": record.status.value if record.status else "unknown",
                    "mask_area": record.mask_area,
                    "bbox": [record.bbox_x, record.bbox_y, record.bbox_w, record.bbox_h],
                    "is_indexed": record.is_indexed == 1,
                    "error_message": record.error_message,
                }
                for record in records
            ]
