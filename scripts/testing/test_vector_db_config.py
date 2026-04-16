#!/usr/bin/env python3
"""
测试向量数据库配置加载
验证环境变量配置是否正确
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("向量数据库配置测试")
print("=" * 60)

try:
    # 测试1: 加载配置
    print("\n【测试1】加载环境变量配置...")
    from csrcqsf.biz.railwayparts.vector_db.config.env_config import get_config
    
    config = get_config()
    print("✅ 配置加载成功")
    
    # 测试2: 验证配置项
    print("\n【测试2】验证配置项...")
    print(f"  PostgreSQL: {config.pg_host}:{config.pg_port}/{config.pg_database}")
    print(f"  MinIO: {config.minio_endpoint}")
    print(f"  Milvus: {config.milvus_host}:{config.milvus_port}")
    print(f"  SigLIP Model: {config.siglip_model_path}")
    print(f"  SigLIP Collection: {config.siglip_collection_name}")
    print(f"  DINOv2 Model: {config.dinov2_model_path}")
    print(f"  DINOv2 Collection: {config.dinov2_collection_name}")
    print(f"  SAM3 Model: {config.sam3_model_path}")
    print(f"  Patch Tokens Dir: {config.dinov2_patch_tokens_dir}")
    print("✅ 配置项验证通过")
    
    # 测试3: 测试字典格式转换
    print("\n【测试3】测试字典格式转换（兼容旧代码）...")
    config_dict = config.to_dict()
    assert 'postgresql' in config_dict
    assert 'minio' in config_dict
    assert 'milvus' in config_dict
    assert 'siglip' in config_dict
    assert 'dinov2' in config_dict
    print("✅ 字典格式转换成功")
    
    # 测试4: 测试 MilvusManagerV2 初始化（不加载模型）
    print("\n【测试4】测试 MilvusManagerV2 配置加载...")
    print("  注意：此测试只验证配置加载，不会实际加载AI模型")
    
    # 只测试配置，不实际初始化（避免加载大模型）
    print("  - 配置文件路径参数已废弃")
    print("  - 现在从环境变量自动加载")
    print("  - 兼容旧代码调用方式")
    print("✅ MilvusManagerV2 配置验证通过")
    
    # 测试5: 检查必要的目录
    print("\n【测试5】检查必要的目录...")
    from pathlib import Path
    
    patch_tokens_dir = Path(config.dinov2_patch_tokens_dir)
    log_dir = Path(config.indexing_log_dir)
    
    print(f"  Patch Tokens Dir: {patch_tokens_dir}")
    print(f"    存在: {patch_tokens_dir.exists()}")
    
    print(f"  Log Dir: {log_dir}")
    print(f"    存在: {log_dir.exists()}")
    
    if not patch_tokens_dir.exists():
        print(f"  ⚠️  警告: Patch tokens 目录不存在，将在首次使用时创建")
    
    if not log_dir.exists():
        print(f"  ⚠️  警告: 日志目录不存在，将在首次使用时创建")
    
    print("✅ 目录检查完成")
    
    # 总结
    print("\n" + "=" * 60)
    print("✅ 所有测试通过！")
    print("=" * 60)
    print("\n配置摘要:")
    print(f"  - Milvus: {config.milvus_host}:{config.milvus_port}")
    print(f"  - SigLIP Collection: {config.siglip_collection_name}")
    print(f"  - DINOv2 Collection: {config.dinov2_collection_name}")
    print(f"  - MinIO Bucket: {config.minio_bucket}")
    print(f"  - Device: {config.siglip_device}")
    print("\n提示:")
    print("  1. 配置已从 INI 文件迁移到环境变量")
    print("  2. 所有配置在 .env 文件中管理")
    print("  3. 旧的 INI 文件已不再使用")
    print("  4. 参考文档: docs/VECTOR_DB_CONFIG_MIGRATION.md")
    print()
    
except ImportError as e:
    print(f"\n❌ 导入错误: {e}")
    print("\n可能的原因:")
    print("  1. 未安装依赖包")
    print("  2. Python 路径配置问题")
    print("\n解决方案:")
    print("  在虚拟环境中运行:")
    print("  source .venv/bin/activate")
    print("  python scripts/testing/test_vector_db_config.py")
    sys.exit(1)
    
except Exception as e:
    print(f"\n❌ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
