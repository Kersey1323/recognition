#!/usr/bin/env python3
"""
测试模型推理是否正常
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from PIL import Image
import numpy as np
from csrcqsf.modules.railway_parts.vector_search.config.env_config import get_config

print("=" * 60)
print("测试模型推理")
print("=" * 60)

# 加载配置
config = get_config()
print(f"\n【配置信息】")
print(f"SigLIP Model Path: {config.siglip_model_path}")
print(f"DINOv2 Model Path: {config.dinov2_model_path}")
print(f"SAM3 Model Path: {config.sam3_model_path}")
print(f"Patch Tokens Dir: {config.dinov2_patch_tokens_dir}")

# 测试 SigLIP
print(f"\n【测试 SigLIP】")
try:
    from csrcqsf.modules.railway_parts.vector_search.extractors.siglip_extractor import (
        SigLIPExtractor,
    )
    
    print("加载 SigLIP 模型...")
    siglip = SigLIPExtractor(
        model_path=config.siglip_model_path,
        device=config.siglip_device
    )
    print("✓ SigLIP 模型加载成功")
    
    # 创建测试图像
    test_image = Image.new('RGB', (224, 224), color='red')
    print("提取图像特征...")
    image_vector = siglip.extract_image_features(test_image)
    print(f"✓ 图像特征提取成功，维度: {image_vector.shape}")
    
    print("提取文本特征...")
    text_vector = siglip.extract_text_features("测试文本")
    print(f"✓ 文本特征提取成功，维度: {text_vector.shape}")
    
except Exception as e:
    print(f"✗ SigLIP 测试失败: {e}")
    import traceback
    traceback.print_exc()

# 测试 DINOv2
print(f"\n【测试 DINOv2】")
try:
    from csrcqsf.modules.railway_parts.vector_search.extractors.dinov2_extractor import (
        DINOv2VectorExtractor,
    )
    
    print("加载 DINOv2 模型...")
    dinov2 = DINOv2VectorExtractor(
        model_name=config.dinov2_model_path,
        device=config.dinov2_device
    )
    print("✓ DINOv2 模型加载成功")
    
    # 创建测试图像
    test_image = Image.new('RGB', (224, 224), color='blue')
    print("提取全局特征...")
    global_vector = dinov2.extract_global_vector(test_image)
    print(f"✓ 全局特征提取成功，维度: {global_vector.shape}")
    
    print("提取 patch tokens...")
    patch_tokens = dinov2.extract_patch_tokens(test_image)
    print(f"✓ Patch tokens 提取成功，维度: {patch_tokens.shape}")
    
except Exception as e:
    print(f"✗ DINOv2 测试失败: {e}")
    import traceback
    traceback.print_exc()

# 测试 SAM3
print(f"\n【测试 SAM3】")
try:
    from csrcqsf.modules.railway_parts.vector_search.preprocessing.sam3_preprocessor import (
        SAM3Preprocessor,
    )
    
    print("加载 SAM3 模型...")
    sam3 = SAM3Preprocessor(
        model_path=config.sam3_model_path,
        mask_dilate=config.sam3_mask_dilate,
        bg_color=config.sam3_bg_color,
        device=config.sam3_device,
        save_debug_images=False
    )
    print("✓ SAM3 模型加载成功")
    
    # 创建测试图像
    test_image = Image.new('RGB', (224, 224), color='green')
    print("预处理图像...")
    processed = sam3.preprocess_image(test_image, "test_item", 999)
    if processed is not None:
        print(f"✓ 图像预处理成功，尺寸: {processed.size}")
    else:
        print("⚠ 图像预处理返回 None（可能未检测到对象）")
    
except Exception as e:
    print(f"✗ SAM3 测试失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
