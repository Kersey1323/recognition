"""自动配件处理器 - 全自动分割 + 高精度特征提取 + 建立索引

增强功能：
1. API 只需 item_id，自动从数据库获取 BASEINFO 类型图片
2. SAM 自动分割，保存分割后的图片到 MinIO
3. 数据库记录分割过程和中间产物
4. DINOv2 高精度特征提取 + Milvus 索引
"""

import os
from datetime import datetime

import cv2
import numpy as np
from anyio.to_thread import run_sync
from bfrcommon.common import date_to_str
from bfrcommon.snowflake import get_id
from pydantic import BaseModel
from segment_anything import SamAutomaticMaskGenerator

from csrcqsf.biz.railwayparts.milvus import (
    FeaturesIndex,
    ImageIndex,
    MilvusManager,
    PartsIndex,
)
from csrcqsf.biz.segment import SegmentBiz
from csrcqsf.data.minio import minio_instance
from csrcqsf.data.pg import SessionLocal
from csrcqsf.logger import CodeTimer, logger
from csrcqsf.models.item import Items, ItemsParent, ItemsVechile
from csrcqsf.models.sgo import (
    ImageSourceType,
    SegmentedImage,
    SegmentStatus,
    SgoItemImages,
)
from csrcqsf.settings import minio_bucket, temp_dir


class AutoSegmentResult(BaseModel):
    """自动分割结果"""
    item_id: str = ''
    total_baseinfo_images: int = 0   # BASEINFO 图片总数
    segmented_count: int = 0         # 成功分割数量
    indexed_count: int = 0           # 成功建立索引数量
    skipped_count: int = 0           # 跳过数量
    failed_count: int = 0            # 失败数量
    message: str = ''


class AutoPartProcessor:
    """自动配件处理器
    
    全自动流程：item_id → 获取BASEINFO图片 → SAM分割 → 上传MinIO → 数据库记录 → DINOv2特征 → Milvus索引
    """
    
    _mask_generator = None
    
    @classmethod
    def get_mask_generator(cls):
        """获取 SAM 自动分割生成器"""
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
        """从图片中分割出主要物体"""
        mask_generator = cls.get_mask_generator()
        if mask_generator is None:
            return image, {'bbox': [0, 0, image.shape[1], image.shape[0]], 'area': image.shape[0] * image.shape[1]}
        
        with CodeTimer(name='SAM自动分割'):
            masks = mask_generator.generate(image)
        
        if len(masks) == 0:
            return image, {'bbox': [0, 0, image.shape[1], image.shape[0]], 'area': image.shape[0] * image.shape[1]}
        
        # 取最大区域
        masks = sorted(masks, key=lambda x: x['area'], reverse=True)
        main_mask = masks[0]
        
        mask = main_mask['segmentation']
        bbox = main_mask['bbox']
        x, y, w, h = [int(v) for v in bbox]
        
        # 应用掩码，背景设为白色
        masked_image = image.copy()
        masked_image[~mask] = 255
        cropped = masked_image[y:y+h, x:x+w]
        
        return cropped, main_mask
    
    @classmethod
    async def _upload_segmented_image(cls, image: np.ndarray, item_id: int, source_image_id: int) -> str:
        """上传分割后的图片到 MinIO"""
        filename = f'segmented/{item_id}/{source_image_id}_{get_id()}.jpg'
        local_path = os.path.join(temp_dir, f'seg_{get_id()}.jpg')
        
        try:
            # 保存到本地临时文件
            cv2.imwrite(local_path, image)
            
            # 上传到 MinIO
            await run_sync(
                minio_instance.upload_file,
                minio_bucket, filename, local_path
            )
            
            return f'{minio_bucket}/{filename}'
        finally:
            # 清理临时文件
            if os.path.exists(local_path):
                os.remove(local_path)
    
    @classmethod
    async def auto_segment_by_item_id(cls, item_id: int, rebuild: bool = False) -> AutoSegmentResult:
        """根据配件ID自动分割并建立高精度索引
        
        Args:
            item_id: 配件ID
            rebuild: 是否重建 (删除现有分割记录重新处理)
            
        Returns:
            AutoSegmentResult: 处理结果
        """
        from csrcqsf.biz.railwayparts.parts import RailwayPartsManager
        
        result = AutoSegmentResult(item_id=str(item_id))
        
        try:
            # Step 1: 获取配件信息和 BASEINFO 图片
            async with SessionLocal() as session:
                item = await Items.get_item_by_id(session, item_id)
                if item is None:
                    result.message = f'配件不存在: {item_id}'
                    return result
                
                # 如果 rebuild，先删除现有分割记录
                if rebuild:
                    await SegmentedImage.delete_by_item_id(session, item_id)
                    await session.commit()
                
                # 获取 BASEINFO 类型的图片
                all_images = await SgoItemImages.list_item_images_by_item_id(session, item_id)
                baseinfo_images = [
                    img for img in all_images 
                    if img.image_source == ImageSourceType.BASEINFO
                ]
                
                if len(baseinfo_images) == 0:
                    result.message = f'配件 item_code:{item.item_code} ,配件名:{item.item_name} 没有找到 BASEINFO 类型的图片'
                    return result
                
                result.total_baseinfo_images = len(baseinfo_images)
                
                # 检查已有的分割记录
                existing_records = await SegmentedImage.list_by_item_id(session, item_id)
                existing_source_ids = {rec.source_image_id for rec in existing_records}
                
                # 筛选出需要处理的新图片
                new_images = [img for img in baseinfo_images if img.id not in existing_source_ids]
                
                if len(new_images) == 0:
                    result.skipped_count = len(baseinfo_images)
                    result.message = '所有图片已处理过，无需重新分割'
                    return result
                
                # 获取父配件和车型信息
                parent_list = await ItemsParent.list_parent_item_by_item_id(session, item_id)
                parent_item_ids = [p.parent_item_id for p in parent_list]
                
                vechile_list = await ItemsVechile.list_item_vechile_info_by_item_id(session, item_id)
                vechile_ids = [v.vechile_id for v in vechile_list]
            
            # Step 2: 处理每张新图片
            segmented_records = []
            successful_features = []  # (record_id, feature_vector, segmented_url)
            
            for img in new_images:
                record = SegmentedImage(
                    id=get_id(),
                    item_id=item_id,
                    source_image_id=img.id,
                    source_image_url=img.image_url,
                    status=SegmentStatus.PENDING
                )
                
                try:
                    # 加载原图
                    image = await RailwayPartsManager.get_image_from_oss(img.image_url)
                    if image is None:
                        record.status = SegmentStatus.FAILED
                        record.error_message = '图片加载失败'
                        segmented_records.append(record)
                        result.failed_count += 1
                        continue
                    
                    # SAM 分割
                    segmented_image, mask_info = await run_sync(cls._segment_main_object, image)
                    
                    bbox = mask_info.get('bbox', [0, 0, 0, 0])
                    area = mask_info.get('area', 0)
                    
                    # 上传分割后的图片到 MinIO
                    segmented_url = await cls._upload_segmented_image(segmented_image, item_id, img.id)
                    
                    # 提取 DINOv2 高精度特征
                    feature_vector = await MilvusManager.extract_hp_image_tensor(segmented_image)
                    
                    # 更新记录
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
                    
                    logger.info(f'分割成功: item={item_id}, image={img.id}, area={area}')
                    
                except Exception as e:
                    logger.error(f'分割失败: item={item_id}, image={img.id}, error={e}')
                    record.status = SegmentStatus.FAILED
                    record.error_message = str(e)
                    segmented_records.append(record)
                    result.failed_count += 1
            
            # Step 3: 保存分割记录到数据库
            async with SessionLocal() as session:
                await SegmentedImage.batch_create(session, segmented_records)
                await session.commit()
            
            # Step 4: 建立 Milvus 高精度索引
            if len(successful_features) > 0:
                try:
                    # 获取或创建索引
                    index_dict = await MilvusManager.list_hp_item_index([item_id])
                    existing_index = index_dict.get(item_id)
                    
                    if existing_index is None:
                        existing_index = PartsIndex(
                            item_id=item_id,
                            id=get_id(),
                            created_at=date_to_str(datetime.now())
                        )
                    
                    existing_index.updated_at = date_to_str(datetime.now())
                    existing_index.item_name = item.item_name
                    existing_index.item_code = item.item_code
                    existing_index.parent_item_info = parent_item_ids
                    existing_index.vechile_info = vechile_ids
                    
                    # 添加图片特征索引
                    indexed_record_ids = []
                    for record_id, feature_vector, segmented_url in successful_features:
                        image_index = ImageIndex(
                            image_id=record_id,
                            filename=segmented_url,
                            image_vector=feature_vector,
                            image_index_created=date_to_str(datetime.now())
                        )
                        existing_index.images.append(image_index)
                        indexed_record_ids.append(record_id)
                    
                    # 添加配件名称作为文字特征
                    feature_set = {f.feature for f in existing_index.features}
                    if item.item_name not in feature_set:
                        feature_vector = await MilvusManager.embedding_encode(item.item_name)
                        existing_index.features.append(FeaturesIndex(
                            feature=item.item_name,
                            feature_vector=feature_vector,
                            feature_index_created=date_to_str(datetime.now())
                        ))
                    
                    # 保存到 Milvus
                    await MilvusManager.upsert_hp_data(existing_index)
                    
                    # 更新分割记录为已索引
                    async with SessionLocal() as session:
                        await SegmentedImage.mark_indexed(session, indexed_record_ids)
                        await Items.update_items_index(
                            session, item_id,
                            image_index_num=len(existing_index.images),
                            feature_index_num=len(existing_index.features)
                        )
                        await session.commit()
                    
                    result.indexed_count = len(indexed_record_ids)
                    
                except Exception as e:
                    logger.error(f'建立索引失败: {e}')
                    result.message = f'分割成功但索引失败: {e}'
                    return result
            
            result.message = f'处理完成: 分割 {result.segmented_count}, 索引 {result.indexed_count}, 失败 {result.failed_count}'
            
        except Exception as e:
            logger.error(f'自动分割处理失败: {e}')
            result.message = f'处理失败: {str(e)}'
        
        return result
    
    @classmethod
    async def list_segmented_images(cls, item_id: int) -> list[dict]:
        """获取配件的分割记录列表"""
        async with SessionLocal() as session:
            records = await SegmentedImage.list_by_item_id(session, item_id)
            return [
                {
                    'id': str(rec.id),
                    'source_image_url': rec.source_image_url,
                    'segmented_image_url': rec.segmented_image_url,
                    'status': rec.status.value if rec.status else 'unknown',
                    'mask_area': rec.mask_area,
                    'bbox': [rec.bbox_x, rec.bbox_y, rec.bbox_w, rec.bbox_h],
                    'is_indexed': rec.is_indexed == 1,
                    'error_message': rec.error_message
                }
                for rec in records
            ]
