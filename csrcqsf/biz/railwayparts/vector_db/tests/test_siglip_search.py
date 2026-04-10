#!/usr/bin/env python3
"""
SigLIP 检索测试脚本
测试图搜图和文搜图功能
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from PIL import Image
import requests
from io import BytesIO
from configparser import ConfigParser

from vector_db.models.siglip_extractor import SigLIPExtractor
from vector_db.models.model_config import SigLIPConfig, MilvusConfig
from vector_db.storage.collection_manager import CollectionManager
from vector_db.data.image_loader import ImageLoader
from vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class SigLIPSearchTester:
    """SigLIP 检索测试器"""

    def __init__(self, config_path='vector_db/config/vector_db.ini', db_config_path='vector_db/config/db_config.ini'):
        """初始化测试器"""
        logger.info("Initializing SigLIP Search Tester...")

        # 加载配置
        siglip_config = SigLIPConfig.from_config(config_path)
        milvus_config = MilvusConfig.from_config(config_path)

        # 初始化模型
        self.siglip_extractor = SigLIPExtractor(
            model_path=siglip_config.model_path,
            device=siglip_config.device
        )

        # 初始化 Milvus
        self.collection_manager = CollectionManager(
            host=milvus_config.host,
            port=milvus_config.port
        )
        self.collection_name = siglip_config.collection_name

        # 初始化图像加载器
        db_parser = ConfigParser()
        db_parser.read(db_config_path, encoding='utf-8')
        self.image_loader = ImageLoader(
            minio_endpoint=db_parser.get('minio', 'endpoint'),
            minio_access_key=db_parser.get('minio', 'access_key'),
            minio_secret_key=db_parser.get('minio', 'secret_key'),
            minio_bucket=db_parser.get('minio', 'bucket'),
            minio_secure=db_parser.getboolean('minio', 'secure'),
            local_image_root=db_parser.get('local', 'image_root')
        )

        logger.info("Initialization complete")

    def search_by_image(self, image_path: str, top_k: int = 5):
        """
        图搜图

        Args:
            image_path: 查询图像路径
            top_k: 返回前 K 个结果

        Returns:
            检索结果列表
        """
        logger.info(f"Searching by image: {image_path}")

        # 加载查询图像
        query_image = Image.open(image_path).convert('RGB')

        # 提取图像特征
        query_vector = self.siglip_extractor.extract_image_features(query_image)

        # 在 Milvus 中检索
        results = self.collection_manager.client.search(
            collection_name=self.collection_name,
            data=[query_vector.tolist()],
            anns_field="image_vector",
            limit=top_k,
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url"]
        )

        return results[0]

    def search_by_text(self, text: str, top_k: int = 5, use_image_vector: bool = False):
        """
        文搜图

        Args:
            text: 查询文本
            top_k: 返回前 K 个结果
            use_image_vector: 是否使用 image_vector 字段（基于图像内容的语义相似度）
                            False: 使用 text_vector（基于 description 文本匹配）
                            True: 使用 image_vector（基于图像内容，适合 SAM3 分割后的图像）

        Returns:
            检索结果列表
        """
        logger.info(f"Searching by text: {text}")

        # 提取文本特征
        query_vector = self.siglip_extractor.extract_text_features(text)

        # 选择搜索字段
        anns_field = "image_vector" if use_image_vector else "text_vector"
        logger.info(f"Using vector field: {anns_field}")

        # 在 Milvus 中检索
        results = self.collection_manager.client.search(
            collection_name=self.collection_name,
            data=[query_vector.tolist()],
            anns_field=anns_field,
            limit=top_k,
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url"]
        )

        return results[0]

    def download_result_images(self, results, output_dir='vector_db/tests/test_images'):
        """
        下载检索结果图像到本地

        Args:
            results: 检索结果
            output_dir: 输出目录
        """
        os.makedirs(output_dir, exist_ok=True)

        downloaded_files = []
        for i, result in enumerate(results):
            image_url = result['entity']['image_url']
            item_name = result['entity']['item_name']
            score = result['distance']

            try:
                # 加载图像
                image = self.image_loader.load_image(image_url)
                if image is None:
                    logger.warning(f"Failed to load image: {image_url}")
                    continue

                # 保存到本地
                filename = f"rank{i+1}_score{score:.4f}_{item_name}.jpg"
                # 清理文件名中的特殊字符
                filename = filename.replace('/', '_').replace('\\', '_')
                filepath = os.path.join(output_dir, filename)

                image.save(filepath)
                downloaded_files.append(filepath)
                logger.info(f"Saved: {filepath}")

            except Exception as e:
                logger.error(f"Failed to download {image_url}: {e}")

        return downloaded_files

    def print_results(self, results):
        """打印检索结果"""
        print("\n" + "="*80)
        print("Search Results:")
        print("="*80)

        for i, result in enumerate(results):
            print(f"\nRank {i+1}:")
            print(f"  Score: {result['distance']:.4f}")
            print(f"  Item ID: {result['entity']['item_id']}")
            print(f"  Item Name: {result['entity']['item_name']}")
            print(f"  Item Code: {result['entity']['item_code']}")
            print(f"  Image ID: {result['entity']['image_id']}")
            print(f"  Image URL: {result['entity']['image_url']}")

        print("\n" + "="*80)


def main():
    """主测试函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Test SigLIP search functionality")
    parser.add_argument('--mode', type=str, required=True, choices=['image', 'text'],
                        help='Search mode: image or text')
    parser.add_argument('--query', type=str, required=True,
                        help='Query image path (for image mode) or query text (for text mode)')
    parser.add_argument('--top-k', type=int, default=5,
                        help='Number of results to return')
    parser.add_argument('--output-dir', type=str, default='vector_db/tests/test_images',
                        help='Directory to save result images')
    parser.add_argument('--use-image-vector', action='store_true',
                        help='Use image_vector field for text search (semantic similarity based on image content)')
    args = parser.parse_args()

    # 初始化测试器
    tester = SigLIPSearchTester()

    # 执行检索
    if args.mode == 'image':
        results = tester.search_by_image(args.query, top_k=args.top_k)
    else:
        results = tester.search_by_text(args.query, top_k=args.top_k, use_image_vector=args.use_image_vector)

    # 打印结果
    tester.print_results(results)

    # 下载结果图像
    logger.info(f"\nDownloading result images to {args.output_dir}...")
    downloaded_files = tester.download_result_images(results, output_dir=args.output_dir)

    print(f"\n✓ Downloaded {len(downloaded_files)} images to {args.output_dir}")
    print("\nYou can now manually inspect the results!")


if __name__ == "__main__":
    main()
