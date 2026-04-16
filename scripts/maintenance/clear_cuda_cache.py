#!/usr/bin/env python3
"""
清理 CUDA 缓存
用于解决 CUDA 相关错误
"""

import torch
import gc

print("清理 CUDA 缓存...")

if torch.cuda.is_available():
    print(f"CUDA 可用: {torch.cuda.is_available()}")
    print(f"CUDA 设备数量: {torch.cuda.device_count()}")
    print(f"当前设备: {torch.cuda.current_device()}")
    print(f"设备名称: {torch.cuda.get_device_name(0)}")
    
    # 清理缓存
    torch.cuda.empty_cache()
    gc.collect()
    
    print("✅ CUDA 缓存已清理")
    
    # 显示内存使用情况
    print(f"\n内存使用情况:")
    print(f"  已分配: {torch.cuda.memory_allocated(0) / 1024**3:.2f} GB")
    print(f"  已保留: {torch.cuda.memory_reserved(0) / 1024**3:.2f} GB")
else:
    print("❌ CUDA 不可用")
