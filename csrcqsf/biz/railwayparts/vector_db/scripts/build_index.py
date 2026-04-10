#!/usr/bin/env python3
"""
批量入库脚本
"""
import sys
import argparse
from configparser import ConfigParser

# 添加项目根目录到 Python 路径
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from vector_db.models.siglip_extractor import SigLIPExtractor
from vector_db.models.dinov2_extractor import DINOv2VectorExtractor
from vector_db.models.model_config import SigLIPConfig, DINOv2Config, MilvusConfig
from vector_db.storage.collection_manager import CollectionManager
from vector_db.data.db_connector import DatabaseConnector
from vector_db.data.image_loader import ImageLoader
from vector_db.indexing.indexer import VectorIndexer
from vector_db.indexing.batch_indexer import BatchIndexer
from vector_db.preprocessing.sam3_preprocessor import SAM3Preprocessor
from vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Build vector database index")
    parser.add_argument(
        '--config',
        type=str,
        default='vector_db/config/vector_db.ini',
        help='Path to vector database configuration file'
    )
    parser.add_argument(
        '--db-config',
        type=str,
        default='vector_db/config/db_config.ini',
        help='Path to database configuration file'
    )
    parser.add_argument(
        '--item-ids',
        type=int,
        nargs='+',
        help='Specific item IDs to index'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of items to process'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from checkpoint'
    )
    parser.add_argument(
        '--clear-checkpoint',
        action='store_true',
        help='Clear checkpoint file before starting'
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Starting Vector Database Indexing")
    logger.info("=" * 60)

    # 加载配置
    logger.info("Loading configurations...")
    siglip_config = SigLIPConfig.from_config(args.config)
    dinov2_config = DINOv2Config.from_config(args.config)
    milvus_config = MilvusConfig.from_config(args.config)

    # 加载数据库配置
    db_parser = ConfigParser()
    db_parser.read(args.db_config, encoding='utf-8')

    # 初始化模型
    logger.info("Initializing models...")
    siglip_extractor = SigLIPExtractor(
        model_path=siglip_config.model_path,
        device=siglip_config.device
    )

    dinov2_extractor = DINOv2VectorExtractor(
        model_name=dinov2_config.model_path,
        device=dinov2_config.device
    )

    # 初始化 SAM3 预处理器
    sam3_preprocessor = None
    config_parser = ConfigParser()
    config_parser.read(args.config, encoding='utf-8')
    if config_parser.has_section('sam3'):
        logger.info("Initializing SAM3 preprocessor...")
        sam3_preprocessor = SAM3Preprocessor(
            model_path=config_parser.get('sam3', 'model_path'),
            mask_dilate=config_parser.getint('sam3', 'mask_dilate'),
            bg_color=config_parser.get('sam3', 'bg_color'),
            device=config_parser.get('sam3', 'device')
        )

    # 初始化存储层
    logger.info("Initializing storage...")
    collection_manager = CollectionManager(
        host=milvus_config.host,
        port=milvus_config.port
    )

    # 初始化数据访问层
    logger.info("Initializing data access...")
    db_connector = DatabaseConnector(
        host=db_parser.get('postgresql', 'host'),
        port=db_parser.getint('postgresql', 'port'),
        database=db_parser.get('postgresql', 'database'),
        user=db_parser.get('postgresql', 'user'),
        password=db_parser.get('postgresql', 'password')
    )

    image_loader = ImageLoader(
        minio_endpoint=db_parser.get('minio', 'endpoint'),
        minio_access_key=db_parser.get('minio', 'access_key'),
        minio_secret_key=db_parser.get('minio', 'secret_key'),
        minio_bucket=db_parser.get('minio', 'bucket'),
        minio_secure=db_parser.getboolean('minio', 'secure'),
        local_image_root=db_parser.get('local', 'image_root')
    )

    # 初始化入库器
    logger.info("Initializing indexer...")
    indexer = VectorIndexer(
        siglip_extractor=siglip_extractor,
        dinov2_extractor=dinov2_extractor,
        collection_manager=collection_manager,
        image_loader=image_loader,
        siglip_collection_name=siglip_config.collection_name,
        dinov2_collection_name=dinov2_config.collection_name,
        patch_tokens_dir=dinov2_config.patch_tokens_dir,
        sam3_preprocessor=sam3_preprocessor
    )

    # 加载检查点配置
    checkpoint_parser = ConfigParser()
    checkpoint_parser.read(args.config, encoding='utf-8')
    checkpoint_file = checkpoint_parser.get('indexing', 'checkpoint_file')

    batch_indexer = BatchIndexer(
        indexer=indexer,
        db_connector=db_connector,
        checkpoint_file=checkpoint_file
    )

    # 清除检查点（如果指定）
    if args.clear_checkpoint:
        batch_indexer.clear_checkpoint()

    # 执行批量入库
    logger.info("Starting batch indexing...")
    stats = batch_indexer.build_index(
        item_ids=args.item_ids,
        limit=args.limit,
        resume=args.resume
    )

    # 关闭连接
    db_connector.close()

    logger.info("=" * 60)
    logger.info("Indexing completed successfully!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
