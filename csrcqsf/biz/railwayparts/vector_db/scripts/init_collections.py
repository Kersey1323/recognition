#!/usr/bin/env python3
"""
Collection 初始化脚本
"""
import sys
import argparse
from configparser import ConfigParser

# 添加项目根目录到 Python 路径
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from vector_db.storage.collection_manager import CollectionManager
from vector_db.models.model_config import SigLIPConfig, DINOv2Config, MilvusConfig
from vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Initialize Milvus Collections")
    parser.add_argument(
        '--config',
        type=str,
        default='vector_db/config/vector_db.ini',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--drop',
        action='store_true',
        help='Drop existing collections before creating (DANGEROUS)'
    )
    args = parser.parse_args()

    # 加载配置
    logger.info(f"Loading configuration from: {args.config}")
    siglip_config = SigLIPConfig.from_config(args.config)
    dinov2_config = DINOv2Config.from_config(args.config)
    milvus_config = MilvusConfig.from_config(args.config)

    # 创建 Collection 管理器
    manager = CollectionManager(
        host=milvus_config.host,
        port=milvus_config.port
    )

    # 删除现有 Collections（如果指定）
    if args.drop:
        logger.warning("Dropping existing collections...")
        response = input("Are you sure? This will delete all data! (yes/no): ")
        if response.lower() == 'yes':
            manager.drop_collection(siglip_config.collection_name)
            manager.drop_collection(dinov2_config.collection_name)
            logger.info("Collections dropped")
        else:
            logger.info("Drop operation cancelled")
            return

    # 创建 SigLIP Collection
    logger.info(f"Creating SigLIP collection: {siglip_config.collection_name}")
    success = manager.create_siglip_collection(
        collection_name=siglip_config.collection_name,
        vector_dim=siglip_config.vector_dim
    )
    if success:
        logger.info("✓ SigLIP collection created successfully")
    else:
        logger.info("✓ SigLIP collection already exists")

    # 创建 DINOv2 Collection
    logger.info(f"Creating DINOv2 collection: {dinov2_config.collection_name}")
    success = manager.create_dinov2_collection(
        collection_name=dinov2_config.collection_name,
        vector_dim=dinov2_config.vector_dim
    )
    if success:
        logger.info("✓ DINOv2 collection created successfully")
    else:
        logger.info("✓ DINOv2 collection already exists")

    logger.info("=" * 60)
    logger.info("Collection initialization completed!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
