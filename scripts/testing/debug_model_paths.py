#!/usr/bin/env python3
"""
调试模型路径配置
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("模型路径调试")
print("=" * 60)

# 测试环境变量
print("\n【环境变量】")
print(f"MODEL_DIR: {os.getenv('MODEL_DIR')}")
print(f"SIGLIP_MODEL_PATH: {os.getenv('SIGLIP_MODEL_PATH')}")
print(f"DINOV2_MODEL_PATH: {os.getenv('DINOV2_MODEL_PATH')}")
print(f"SAM3_MODEL_PATH: {os.getenv('SAM3_MODEL_PATH')}")

# 测试 settings.py
print("\n【settings.py 配置】")
try:
    from csrcqsf.settings import model_dir, SAM_MODEL
    print(f"model_dir: {model_dir}")
    print(f"SAM_MODEL: {SAM_MODEL}")
    print(f"SAM_MODEL exists: {Path(SAM_MODEL).exists()}")
except Exception as e:
    print(f"❌ 加载 settings.py 失败: {e}")

# 测试 env_config.py
print("\n【env_config.py 配置】")
try:
    from csrcqsf.biz.railwayparts.vector_db.config.env_config import get_config
    config = get_config()
    print(f"model_dir: {config.model_dir}")
    print(f"siglip_model_path: {config.siglip_model_path}")
    print(f"  exists: {Path(config.siglip_model_path).exists()}")
    print(f"dinov2_model_path: {config.dinov2_model_path}")
    print(f"  exists: {Path(config.dinov2_model_path).exists()}")
    print(f"sam3_model_path: {config.sam3_model_path}")
    print(f"  exists: {Path(config.sam3_model_path).exists()}")
except Exception as e:
    print(f"❌ 加载 env_config.py 失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
