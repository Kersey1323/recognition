"""Mask 预处理器 - 使用 SAM 对重建图片做前景分割

在 3D 重建前，对每张图片使用 SAM (SamPredictor + 中心点提示) 分割，
将背景像素设为透明 (alpha=0)，只保留目标物体。
输出格式为 PNG (支持透明通道)。

核心策略:
  - 使用图片中心区域的 5 个前景提示点 (中心 + 上下左右)
  - 使用四角的 4 个背景提示点
  - SAM 会精准分割出"中心主体"
  - 对 mask 做形态学后处理 (膨胀 + 孔洞填充)
"""

import os
import shutil

import cv2
import numpy as np

from csrcqsf.logger import CodeTimer, logger


class MaskPreprocessor:
    """使用 SAM 对重建图片做前景提取 (背景→白色)"""
    
    @classmethod
    def preprocess_images(
        cls,
        input_dir: str,
        output_dir: str,
        min_mask_ratio: float = 0.05,
        max_mask_ratio: float = 0.85,
    ) -> dict:
        """对目录中的所有图片做前景分割
        
        Args:
            input_dir: 原始图片目录
            output_dir: 输出目录 (背景变白的图片)
            min_mask_ratio: 最小 mask 面积占比，低于此值认为分割失败
            max_mask_ratio: 最大 mask 面积占比，高于此值认为分割了整张图
            
        Returns:
            dict: {'success': bool, 'total': int, 'masked': int, 'skipped': int, 'suspicious': list}
        """
        result = {'success': False, 'total': 0, 'masked': 0, 'skipped': 0, 'suspicious': []}
        mask_ratios = {}  # filename -> mask_ratio
        
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
        
        # 加载 SAM Predictor
        predictor = cls._get_predictor()
        if predictor is None:
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
                # 输出为 PNG (支持透明通道)
                dst_name = os.path.splitext(f)[0] + '.png'
                dst_path = os.path.join(output_dir, dst_name)
                
                try:
                    image = cv2.imread(src_path)
                    if image is None:
                        logger.warning(f"无法读取图片: {f}")
                        result['skipped'] += 1
                        continue
                    
                    # RGB 转换 (SAM 需要 RGB)
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    h, w = image.shape[:2]
                    
                    # 使用 SamPredictor + 中心点提示
                    predictor.set_image(image_rgb)
                    
                    # 构建前景提示点: 中心 + 中心周围 4 个点
                    cx, cy = w // 2, h // 2
                    offset_x, offset_y = w // 6, h // 6
                    
                    foreground_points = [
                        [cx, cy],                   # 中心
                        [cx - offset_x, cy],        # 左
                        [cx + offset_x, cy],        # 右
                        [cx, cy - offset_y],        # 上
                        [cx, cy + offset_y],        # 下
                    ]
                    
                    # 构建背景提示点: 四角
                    margin_x, margin_y = w // 10, h // 10
                    background_points = [
                        [margin_x, margin_y],               # 左上
                        [w - margin_x, margin_y],            # 右上
                        [margin_x, h - margin_y],            # 左下
                        [w - margin_x, h - margin_y],        # 右下
                    ]
                    
                    input_points = np.array(foreground_points + background_points)
                    input_labels = np.array(
                        [1] * len(foreground_points) +       # 1 = foreground
                        [0] * len(background_points)         # 0 = background
                    )
                    
                    # SAM 预测
                    masks, scores, _ = predictor.predict(
                        point_coords=input_points,
                        point_labels=input_labels,
                        multimask_output=True,  # 返回 3 个候选
                    )
                    
                    if len(masks) == 0:
                        shutil.copy2(src_path, dst_path)
                        result['skipped'] += 1
                        logger.warning(f"分割无结果: {f}")
                        continue
                    
                    # 取得分最高的 mask
                    best_idx = np.argmax(scores)
                    best_mask = masks[best_idx]
                    
                    # 检查 mask 面积比
                    mask_ratio = best_mask.sum() / (h * w)
                    
                    if mask_ratio < min_mask_ratio:
                        shutil.copy2(src_path, dst_path)
                        result['skipped'] += 1
                        logger.warning(f"mask 太小 ({mask_ratio:.2%}): {f}")
                        continue
                    
                    if mask_ratio > max_mask_ratio:
                        # mask 太大可能是分割了整张图，尝试用第二高分的
                        sorted_indices = np.argsort(scores)[::-1]
                        found_good = False
                        for idx in sorted_indices[1:]:
                            alt_ratio = masks[idx].sum() / (h * w)
                            if min_mask_ratio <= alt_ratio <= max_mask_ratio:
                                best_mask = masks[idx]
                                mask_ratio = alt_ratio
                                found_good = True
                                break
                        
                        if not found_good:
                            shutil.copy2(src_path, dst_path)
                            result['skipped'] += 1
                            logger.warning(f"mask 太大 ({mask_ratio:.2%}), 跳过: {f}")
                            continue
                    
                    # 形态学后处理: 膨胀 + 孔洞填充
                    best_mask = cls._postprocess_mask(best_mask)
                    
                    # 应用 mask: 背景透明 (BGRA, alpha=0 为透明)
                    b, g, r = cv2.split(image)
                    alpha = (best_mask.astype(np.uint8)) * 255
                    masked_image = cv2.merge([b, g, r, alpha])
                    
                    cv2.imwrite(dst_path, masked_image)
                    result['masked'] += 1
                    mask_ratios[f] = mask_ratio
                    logger.info(f"分割成功 ({mask_ratio:.1%}): {f}")
                    
                except Exception as e:
                    logger.warning(f"分割失败 [{f}]: {e}")
                    shutil.copy2(src_path, dst_path)
                    result['skipped'] += 1
        
        logger.info(f"Mask 预处理完成: {result['masked']}/{result['total']} 张分割成功")
        
        # ---- 异常检测: 基于中位数找出 mask 面积异常的图片 ----
        if len(mask_ratios) >= 3:
            ratios = list(mask_ratios.values())
            median_ratio = float(np.median(ratios))
            
            for fname, ratio in mask_ratios.items():
                # 偏离中位数超过 2 倍视为可疑
                if ratio > median_ratio * 2.5 or ratio < median_ratio * 0.4:
                    result['suspicious'].append({
                        'file': fname,
                        'ratio': ratio,
                        'median': median_ratio,
                        'reason': '面积偏大' if ratio > median_ratio else '面积偏小',
                    })
            
            if result['suspicious']:
                logger.warning(f"发现 {len(result['suspicious'])} 张可疑分割:")
                for s in result['suspicious']:
                    logger.warning(f"  ⚠ {s['file']}: {s['ratio']:.1%} ({s['reason']}, 中位数 {s['median']:.1%})")
            else:
                logger.info(f"异常检测通过: 所有 mask 面积正常 (中位数 {median_ratio:.1%})")
        
        result['success'] = True
        return result
    
    @classmethod
    def _postprocess_mask(cls, mask: np.ndarray) -> np.ndarray:
        """对 mask 做形态学后处理: 膨胀 + 孔洞填充"""
        mask_uint8 = mask.astype(np.uint8) * 255
        
        # 膨胀: 扩大 mask 边缘 (保留物体边缘细节)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        mask_uint8 = cv2.dilate(mask_uint8, kernel, iterations=2)
        
        # 填充内部孔洞
        contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        mask_filled = np.zeros_like(mask_uint8)
        cv2.drawContours(mask_filled, contours, -1, 255, thickness=cv2.FILLED)
        
        return mask_filled > 0
    
    @classmethod
    def _get_predictor(cls):
        """获取 SAM Predictor (基于点提示的精确分割)"""
        try:
            import torch
            from segment_anything import SamPredictor, sam_model_registry

            from csrcqsf.settings import SAM_MODEL
            
            if not os.path.exists(SAM_MODEL):
                logger.warning(f"SAM 模型不存在: {SAM_MODEL}")
                return None
            
            device = "cuda" if torch.cuda.is_available() else "cpu"
            sam = sam_model_registry["vit_h"](checkpoint=SAM_MODEL)
            sam.to(device)
            
            predictor = SamPredictor(sam)
            
            logger.info(f"SAM Predictor 加载成功 (device={device})")
            return predictor
            
        except Exception as e:
            logger.warning(f"SAM 加载失败: {e}")
            return None
