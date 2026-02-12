"""Mask 预处理器 - 使用 SAM 对重建图片做前景分割

在 3D 重建前，对每张图片使用 SAM 自动分割，
将背景像素设为白色，只保留目标物体。
配合 `--white_background` 参数，使 3DGS/2DGS 只重建前景物体。

注意: SAM 模型在主服务中已加载，此模块复用其逻辑。
"""

import os
import shutil

import cv2

from csrcqsf.logger import CodeTimer, logger


class MaskPreprocessor:
    """使用 SAM 对重建图片做前景提取 (背景→白色)"""
    
    @classmethod
    def preprocess_images(
        cls,
        input_dir: str,
        output_dir: str,
        min_mask_ratio: float = 0.05,
    ) -> dict:
        """对目录中的所有图片做前景分割
        
        Args:
            input_dir: 原始图片目录
            output_dir: 输出目录 (背景变白的图片)
            min_mask_ratio: 最小 mask 面积占比，低于此值认为分割失败，使用原图
            
        Returns:
            dict: {'success': bool, 'total': int, 'masked': int, 'skipped': int}
        """
        result = {'success': False, 'total': 0, 'masked': 0, 'skipped': 0}
        
        os.makedirs(output_dir, exist_ok=True)
        
        # 获取所有图片
        image_files = []
        for f in sorted(os.listdir(input_dir)):
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp')):
                image_files.append(f)
        
        if not image_files:
            result['message'] = f'目录中没有图片: {input_dir}'
            return result
        
        result['total'] = len(image_files)
        
        # 加载 SAM
        mask_generator = cls._get_mask_generator()
        if mask_generator is None:
            # SAM 不可用，复制原图
            logger.warning("SAM 不可用，跳过 mask 预处理，使用原图")
            for f in image_files:
                shutil.copy2(os.path.join(input_dir, f), os.path.join(output_dir, f))
            result['success'] = True
            result['skipped'] = len(image_files)
            return result
        
        with CodeTimer(name=f'SAM批量分割 ({len(image_files)}张)'):
            for f in image_files:
                src_path = os.path.join(input_dir, f)
                dst_path = os.path.join(output_dir, f)
                
                try:
                    image = cv2.imread(src_path)
                    if image is None:
                        logger.warning(f"无法读取图片: {f}")
                        result['skipped'] += 1
                        continue
                    
                    # RGB 转换 (SAM 需要 RGB)
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    
                    # SAM 自动分割
                    masks = mask_generator.generate(image_rgb)
                    
                    if len(masks) == 0:
                        # 分割失败，使用原图
                        shutil.copy2(src_path, dst_path)
                        result['skipped'] += 1
                        logger.warning(f"分割无结果: {f}")
                        continue
                    
                    # 取最大区域作为前景
                    masks = sorted(masks, key=lambda x: x['area'], reverse=True)
                    main_mask = masks[0]['segmentation']
                    
                    # 检查 mask 面积比
                    mask_ratio = main_mask.sum() / (image.shape[0] * image.shape[1])
                    if mask_ratio < min_mask_ratio:
                        shutil.copy2(src_path, dst_path)
                        result['skipped'] += 1
                        logger.warning(f"mask 太小 ({mask_ratio:.2%}): {f}")
                        continue
                    
                    # 可以合并多个较大区域 (避免只取了一部分)
                    # 将面积超过最大区域 20% 的 mask 也合并进来
                    combined_mask = main_mask.copy()
                    max_area = masks[0]['area']
                    for m in masks[1:]:
                        if m['area'] > max_area * 0.2:
                            combined_mask = combined_mask | m['segmentation']
                    
                    # 应用 mask: 背景变白
                    masked_image = image.copy()
                    masked_image[~combined_mask] = 255  # BGR 白色
                    
                    cv2.imwrite(dst_path, masked_image)
                    result['masked'] += 1
                    
                except Exception as e:
                    logger.warning(f"分割失败 [{f}]: {e}")
                    shutil.copy2(src_path, dst_path)
                    result['skipped'] += 1
        
        logger.info(f"Mask 预处理完成: {result['masked']}/{result['total']} 张分割成功")
        result['success'] = True
        return result
    
    @classmethod
    def _get_mask_generator(cls):
        """获取 SAM 自动分割生成器"""
        try:
            import torch
            from segment_anything import SamAutomaticMaskGenerator, sam_model_registry

            from csrcqsf.settings import SAM_MODEL
            
            if not os.path.exists(SAM_MODEL):
                logger.warning(f"SAM 模型不存在: {SAM_MODEL}")
                return None
            
            device = "cuda" if torch.cuda.is_available() else "cpu"
            sam = sam_model_registry["vit_h"](checkpoint=SAM_MODEL)
            sam.to(device)
            
            generator = SamAutomaticMaskGenerator(
                sam,
                points_per_side=32,
                pred_iou_thresh=0.86,
                stability_score_thresh=0.92,
                min_mask_region_area=1000,
            )
            
            return generator
            
        except Exception as e:
            logger.warning(f"SAM 加载失败: {e}")
            return None
