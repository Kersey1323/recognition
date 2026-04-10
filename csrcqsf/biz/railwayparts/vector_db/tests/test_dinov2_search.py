#!/usr/bin/env python3
"""
DINOv2 两阶段检索测试脚本
阶段1: 使用全局特征粗排（快速）
阶段2: 使用 patch tokens 精排（精确）
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import numpy as np
from PIL import Image
from configparser import ConfigParser

from vector_db.models.dinov2_extractor import DINOv2VectorExtractor
from vector_db.models.model_config import DINOv2Config, MilvusConfig
from vector_db.storage.collection_manager import CollectionManager
from vector_db.data.image_loader import ImageLoader
from vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class DINOv2SearchTester:
    """DINOv2 两阶段检索测试器"""

    def __init__(self, config_path='vector_db/config/vector_db.ini', db_config_path='vector_db/config/db_config.ini'):
        """初始化测试器"""
        logger.info("Initializing DINOv2 Search Tester...")

        # 加载配置
        dinov2_config = DINOv2Config.from_config(config_path)
        milvus_config = MilvusConfig.from_config(config_path)

        # 初始化模型
        self.dinov2_extractor = DINOv2VectorExtractor(
            model_name=dinov2_config.model_path,
            device=dinov2_config.device
        )

        # 初始化 Milvus
        self.collection_manager = CollectionManager(
            host=milvus_config.host,
            port=milvus_config.port
        )
        self.collection_name = dinov2_config.collection_name
        self.patch_tokens_dir = dinov2_config.patch_tokens_dir

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

    def search_two_stage(self, query_image_path: str, coarse_top_k: int = 20, fine_top_k: int = 5):
        """
        两阶段检索

        Args:
            query_image_path: 查询图像路径
            coarse_top_k: 粗排返回数量
            fine_top_k: 精排返回数量

        Returns:
            粗排结果, 精排结果
        """
        logger.info(f"Two-stage search for: {query_image_path}")

        # 加载查询图像
        query_image = Image.open(query_image_path).convert('RGB')

        # 提取查询图像的特征
        logger.info("Extracting query features...")
        query_global = self.dinov2_extractor.extract_global_vector(query_image)
        query_patch_tokens = self.dinov2_extractor.extract_patch_tokens(query_image)

        # ===== 阶段1: 粗排（使用全局特征） =====
        logger.info(f"Stage 1: Coarse ranking (top-{coarse_top_k})...")
        coarse_results = self.collection_manager.client.search(
            collection_name=self.collection_name,
            data=[query_global.tolist()],
            anns_field="global_vector",
            limit=coarse_top_k,
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url", "patch_tokens_path"]
        )[0]

        logger.info(f"Coarse ranking found {len(coarse_results)} candidates")

        # ===== 阶段2: 精排（使用 patch tokens） =====
        logger.info(f"Stage 2: Fine ranking (top-{fine_top_k})...")
        fine_results = []

        for result in coarse_results:
            patch_tokens_path = result['entity']['patch_tokens_path']

            # 加载候选图像的 patch tokens
            if not os.path.exists(patch_tokens_path):
                logger.warning(f"Patch tokens not found: {patch_tokens_path}")
                continue

            candidate_patch_tokens = np.load(patch_tokens_path)  # (1369, 1024)

            # 计算 patch-level 相似度
            # query_patch_tokens: (1369, 1024)
            # candidate_patch_tokens: (1369, 1024)
            # 使用余弦相似度
            query_norm = query_patch_tokens / (np.linalg.norm(query_patch_tokens, axis=1, keepdims=True) + 1e-8)
            candidate_norm = candidate_patch_tokens / (np.linalg.norm(candidate_patch_tokens, axis=1, keepdims=True) + 1e-8)

            # 计算每个 patch 之间的相似度矩阵
            similarity_matrix = np.dot(query_norm, candidate_norm.T)  # (1369, 1369)

            # 使用最大相似度作为精排分数（每个查询 patch 找到最相似的候选 patch）
            max_similarities = similarity_matrix.max(axis=1)  # (1369,)
            fine_score = max_similarities.mean()  # 平均最大相似度

            fine_results.append({
                'entity': result['entity'],
                'coarse_distance': result['distance'],
                'fine_score': float(fine_score)
            })

        # 按精排分数排序
        fine_results.sort(key=lambda x: x['fine_score'], reverse=True)
        fine_results = fine_results[:fine_top_k]

        logger.info(f"Fine ranking complete, top-{len(fine_results)} results")

        return coarse_results, fine_results

    def download_result_images(self, results, output_dir, result_type='coarse'):
        """
        下载检索结果图像到本地

        Args:
            results: 检索结果
            output_dir: 输出目录
            result_type: 'coarse' 或 'fine'
        """
        os.makedirs(output_dir, exist_ok=True)

        downloaded_files = []
        for i, result in enumerate(results):
            if result_type == 'coarse':
                image_url = result['entity']['image_url']
                item_name = result['entity']['item_name']
                score = result['distance']
                score_label = f"dist{score:.4f}"
            else:  # fine
                image_url = result['entity']['image_url']
                item_name = result['entity']['item_name']
                score = result['fine_score']
                score_label = f"score{score:.4f}"

            try:
                # 加载图像
                image = self.image_loader.load_image(image_url)
                if image is None:
                    logger.warning(f"Failed to load image: {image_url}")
                    continue

                # 保存到本地
                filename = f"rank{i+1}_{score_label}_{item_name}.jpg"
                filename = filename.replace('/', '_').replace('\\', '_')
                filepath = os.path.join(output_dir, filename)

                image.save(filepath)
                downloaded_files.append(filepath)
                logger.info(f"Saved: {filepath}")

            except Exception as e:
                logger.error(f"Failed to download {image_url}: {e}")

        return downloaded_files

    def print_results(self, coarse_results, fine_results):
        """打印检索结果"""
        print("\n" + "="*80)
        print("STAGE 1: Coarse Ranking Results (Global Features)")
        print("="*80)

        for i, result in enumerate(coarse_results[:10]):  # 只显示前10个
            print(f"\nRank {i+1}:")
            print(f"  Distance: {result['distance']:.4f}")
            print(f"  Item: {result['entity']['item_name']} ({result['entity']['item_code']})")
            print(f"  Image ID: {result['entity']['image_id']}")

        print("\n" + "="*80)
        print("STAGE 2: Fine Ranking Results (Patch Tokens)")
        print("="*80)

        for i, result in enumerate(fine_results):
            print(f"\nRank {i+1}:")
            print(f"  Fine Score: {result['fine_score']:.4f}")
            print(f"  Coarse Distance: {result['coarse_distance']:.4f}")
            print(f"  Item: {result['entity']['item_name']} ({result['entity']['item_code']})")
            print(f"  Image ID: {result['entity']['image_id']}")

        print("\n" + "="*80)


def main():
    """主测试函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Test DINOv2 two-stage search")
    parser.add_argument('--query', type=str, required=True,
                        help='Query image path')
    parser.add_argument('--coarse-top-k', type=int, default=20,
                        help='Number of candidates for coarse ranking')
    parser.add_argument('--fine-top-k', type=int, default=5,
                        help='Number of results for fine ranking')
    parser.add_argument('--output-dir', type=str, default='vector_db/tests/test_images/dinov2_search',
                        help='Output directory for result images')
    args = parser.parse_args()

    # 初始化测试器
    tester = DINOv2SearchTester()

    # 执行两阶段检索
    coarse_results, fine_results = tester.search_two_stage(
        query_image_path=args.query,
        coarse_top_k=args.coarse_top_k,
        fine_top_k=args.fine_top_k
    )

    # 打印结果
    tester.print_results(coarse_results, fine_results)

    # 下载粗排结果图像
    print(f"\nDownloading coarse ranking images to {args.output_dir}/coarse...")
    tester.download_result_images(
        coarse_results[:10],  # 只下载前10个
        os.path.join(args.output_dir, 'coarse'),
        result_type='coarse'
    )

    # 下载精排结果图像
    print(f"\nDownloading fine ranking images to {args.output_dir}/fine...")
    tester.download_result_images(
        fine_results,
        os.path.join(args.output_dir, 'fine'),
        result_type='fine'
    )

    print(f"\n✓ Results saved to {args.output_dir}")
    print("You can now manually inspect the results!")


if __name__ == "__main__":
    main()
