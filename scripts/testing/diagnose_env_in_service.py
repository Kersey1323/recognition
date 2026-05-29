#!/usr/bin/env python3
"""
诊断服务中的环境变量加载情况
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import os
from dotenv import load_dotenv

print("=" * 60)
print("诊断环境变量加载")
print("=" * 60)

# 检查 .env 文件
env_file = project_root / ".env"
print(f"\n【.env 文件】")
print(f"路径: {env_file}")
print(f"存在: {env_file.exists()}")

if env_file.exists():
    print(f"大小: {env_file.stat().st_size} bytes")
    
# 加载环境变量
print(f"\n【加载环境变量】")
load_dotenv(env_file)
print("✓ dotenv 加载完成")

# 检查关键环境变量
print(f"\n【关键环境变量】")
key_vars = [
    "MODEL_DIR",
    "SIGLIP_MODEL_PATH",
    "DINOV2_MODEL_PATH",
    "SAM3_MODEL_PATH",
    "MILVUS_HOST",
    "MILVUS_PORT",
]

for var in key_vars:
    value = os.getenv(var)
    if value:
        print(f"✓ {var}: {value}")
    else:
        print(f"✗ {var}: 未设置")

# 测试配置加载
print(f"\n【测试 env_config.py】")
try:
    from csrcqsf.modules.railway_parts.vector_search.config.env_config import (
        get_config,
    )
    config = get_config()
    print(f"✓ 配置加载成功")
    print(f"  MODEL_DIR: {config.model_dir}")
    print(f"  SigLIP Path: {config.siglip_model_path}")
    print(f"  DINOv2 Path: {config.dinov2_model_path}")
    print(f"  SAM3 Path: {config.sam3_model_path}")
    print(f"  Patch Tokens Dir: {config.dinov2_patch_tokens_dir}")
except Exception as e:
    print(f"✗ 配置加载失败: {e}")
    import traceback
    traceback.print_exc()

# 测试 MilvusManager 初始化
print(f"\n【测试 MilvusManager 初始化】")
try:
    from csrcqsf.modules.railway_parts.vector_search.storage.milvus_manager import (
        MilvusManagerV2,
    )
    print("正在初始化 MilvusManager...")
    manager = MilvusManagerV2(enable_sam3=False)  # 不启用 SAM3 以加快测试
    print("✓ MilvusManager 初始化成功")
    print(f"  SigLIP Collection: {manager.siglip_collection}")
    print(f"  DINOv2 Collection: {manager.dinov2_collection}")
except Exception as e:
    print(f"✗ MilvusManager 初始化失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("诊断完成")
print("=" * 60)
