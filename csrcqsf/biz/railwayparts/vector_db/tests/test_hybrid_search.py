#!/usr/bin/env python3
"""
混合检索测试脚本
第一阶段：SigLIP + DINOv2 全局特征 RRF 融合粗排
第二阶段：DINOv2 Patch Token 局部特征精排
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import numpy as np
from PIL import Image
from configparser import ConfigParser
from typing import List, Dict, Tuple

from vector_db.models.siglip_extractor import SigLIPExtractor
from vector_db.models.dinov2_extractor import DINOv2VectorExtractor
from vector_db.models.model_config import SigLIPConfig, DINOv2Config, MilvusConfig
from vector_db.storage.collection_manager import CollectionManager
from vector_db.data.image_loader import ImageLoader
from vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class HybridSearchTester:
    """混合检索测试器：SigLIP + DINOv2 两阶段检索"""

    def __init__(self, config_path='vector_db/config/vector_db.ini', db_config_path='vector_db/config/db_config.ini'):
        """初始化测试器"""
        logger.info("Initializing Hybrid Search Tester...")

        # 加载配置
        siglip_config = SigLIPConfig.from_config(config_path)
        dinov2_config = DINOv2Config.from_config(config_path)
        milvus_config = MilvusConfig.from_config(config_path)

        # 初始化 SigLIP 模型
        self.siglip_extractor = SigLIPExtractor(
            model_path=siglip_config.model_path,
            device=siglip_config.device
        )
        self.siglip_collection = siglip_config.collection_name

        # 初始化 DINOv2 模型
        self.dinov2_extractor = DINOv2VectorExtractor(
            model_name=dinov2_config.model_path,
            device=dinov2_config.device
        )
        self.dinov2_collection = dinov2_config.collection_name
        self.patch_tokens_dir = dinov2_config.patch_tokens_dir

        # 初始化 Milvus
        self.collection_manager = CollectionManager(
            host=milvus_config.host,
            port=milvus_config.port
        )

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

    def rrf_fusion(self, results_list: List[List], k: int = 60) -> List[Dict]:
        """
        RRF (Reciprocal Rank Fusion) 算法融合多个检索结果

        Args:
            results_list: 多个检索结果列表
            k: RRF 常数（默认 60）

        Returns:
            融合后的结果列表，按 RRF 分数降序排列
        """
        # 收集所有候选项的 RRF 分数
        rrf_scores = {}

        for results in results_list:
            for rank, result in enumerate(results, start=1):
                image_id = result['entity']['image_id']
                rrf_score = 1.0 / (k + rank)

                if image_id not in rrf_scores:
                    rrf_scores[image_id] = {
                        'entity': result['entity'],
                        'rrf_score': 0.0,
                        'ranks': []
                    }

                rrf_scores[image_id]['rrf_score'] += rrf_score
                rrf_scores[image_id]['ranks'].append(rank)

        # 转换为列表并排序
        fused_results = list(rrf_scores.values())
        fused_results.sort(key=lambda x: x['rrf_score'], reverse=True)

        return fused_results

    def search_hybrid_two_stage(
        self,
        query_image_path: str,
        coarse_top_k: int = 30,
        fine_top_k: int = 5,
        alpha: float = 0.6
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        混合两阶段检索

        Args:
            query_image_path: 查询图像路径
            coarse_top_k: 粗排返回数量（RRF 融合后）
            fine_top_k: 精排返回数量
            alpha: 加权系数，最终分数 = alpha * rrf_score + (1-alpha) * patch_score

        Returns:
            (粗排结果, 精排结果)
        """
        logger.info(f"Hybrid two-stage search for: {query_image_path}")

        # 加载查询图像
        query_image = Image.open(query_image_path).convert('RGB')

        # ===== 提取查询图像的特征 =====
        logger.info("Extracting query features...")

        # SigLIP 图像特征
        siglip_vector = self.siglip_extractor.extract_image_features(query_image)

        # DINOv2 全局特征和 patch tokens
        dinov2_global = self.dinov2_extractor.extract_global_vector(query_image)
        query_patch_tokens = self.dinov2_extractor.extract_patch_tokens(query_image)

        # ===== 阶段1: 粗排（RRF 融合 SigLIP + DINOv2） =====
        logger.info(f"Stage 1: Coarse ranking with RRF fusion (top-{coarse_top_k})...")

        # SigLIP 检索
        logger.info("  - Searching with SigLIP...")
        siglip_results = self.collection_manager.client.search(
            collection_name=self.siglip_collection,
            data=[siglip_vector.tolist()],
            anns_field="image_vector",
            limit=coarse_top_k * 2,  # 多检索一些用于融合
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url"]
        )[0]

        # DINOv2 检索
        logger.info("  - Searching with DINOv2...")
        dinov2_results = self.collection_manager.client.search(
            collection_name=self.dinov2_collection,
            data=[dinov2_global.tolist()],
            anns_field="global_vector",
            limit=coarse_top_k * 2,
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url", "patch_tokens_path"]
        )[0]

        # RRF 融合
        logger.info("  - Fusing results with RRF...")
        fused_results = self.rrf_fusion([siglip_results, dinov2_results])
        coarse_results = fused_results[:coarse_top_k]

        logger.info(f"Coarse ranking found {len(coarse_results)} candidates after RRF fusion")

        # ===== 阶段2: 精排（DINOv2 Patch Token 匹配） =====
        logger.info(f"Stage 2: Fine ranking with patch tokens (top-{fine_top_k})...")
        fine_results = []

        for result in coarse_results:
            # 从 DINOv2 结果中找到对应的 patch_tokens_path
            patch_tokens_path = None
            for dinov2_result in dinov2_results:
                if dinov2_result['entity']['image_id'] == result['entity']['image_id']:
                    patch_tokens_path = dinov2_result['entity']['patch_tokens_path']
                    break

            if patch_tokens_path is None or not os.path.exists(patch_tokens_path):
                logger.warning(f"Patch tokens not found for image_id: {result['entity']['image_id']}")
                continue

            # 加载候选图像的 patch tokens
            candidate_patch_tokens = np.load(patch_tokens_path)  # (1369, 1024)

            # 计算 patch-level 相似度
            query_norm = query_patch_tokens / (np.linalg.norm(query_patch_tokens, axis=1, keepdims=True) + 1e-8)
            candidate_norm = candidate_patch_tokens / (np.linalg.norm(candidate_patch_tokens, axis=1, keepdims=True) + 1e-8)

            # 相似度矩阵：每个查询 patch 找到最相似的候选 patch
            similarity_matrix = np.dot(query_norm, candidate_norm.T)  # (1369, 1369)
            max_similarities = similarity_matrix.max(axis=1)  # (1369,)
            patch_score = max_similarities.mean()  # 局部物理得分

            # 加权合并：RRF 分数 + Patch 分数
            rrf_score = result['rrf_score']
            final_score = alpha * rrf_score + (1 - alpha) * patch_score

            fine_results.append({
                'entity': result['entity'],
                'rrf_score': float(rrf_score),
                'patch_score': float(patch_score),
                'final_score': float(final_score),
                'ranks': result['ranks']
            })

        # 按最终分数排序
        fine_results.sort(key=lambda x: x['final_score'], reverse=True)
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
                score = result['rrf_score']
                score_label = f"rrf{score:.4f}"
            else:  # fine
                image_url = result['entity']['image_url']
                item_name = result['entity']['item_name']
                score = result['final_score']
                score_label = f"final{score:.4f}"

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
        print("STAGE 1: Coarse Ranking Results (RRF Fusion: SigLIP + DINOv2)")
        print("="*80)

        for i, result in enumerate(coarse_results[:10]):  # 只显示前10个
            print(f"\nRank {i+1}:")
            print(f"  RRF Score: {result['rrf_score']:.4f}")
            print(f"  Source Ranks: {result['ranks']}")
            print(f"  Item: {result['entity']['item_name']} ({result['entity']['item_code']})")
            print(f"  Image ID: {result['entity']['image_id']}")

        print("\n" + "="*80)
        print("STAGE 2: Fine Ranking Results (Patch Token Matching)")
        print("="*80)

        for i, result in enumerate(fine_results):
            print(f"\nRank {i+1}:")
            print(f"  Final Score: {result['final_score']:.4f}")
            print(f"    ├─ RRF Score: {result['rrf_score']:.4f}")
            print(f"    └─ Patch Score: {result['patch_score']:.4f}")
            print(f"  Item: {result['entity']['item_name']} ({result['entity']['item_code']})")
            print(f"  Image ID: {result['entity']['image_id']}")

        print("\n" + "="*80)


def main():
    """主测试函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Test hybrid two-stage search (SigLIP + DINOv2)")
    parser.add_argument('--query', type=str, required=True,
                        help='Query image path')
    parser.add_argument('--coarse-top-k', type=int, default=30,
                        help='Number of candidates for coarse ranking (RRF fusion)')
    parser.add_argument('--fine-top-k', type=int, default=5,
                        help='Number of results for fine ranking')
    parser.add_argument('--alpha', type=float, default=0.6,
                        help='Weight for RRF score (final = alpha*rrf + (1-alpha)*patch)')
    parser.add_argument('--output-dir', type=str, default='vector_db/tests/test_images/hybrid_search',
                        help='Output directory for result images')
    args = parser.parse_args()

    # 初始化测试器
    tester = HybridSearchTester()

    # 执行混合两阶段检索
    coarse_results, fine_results = tester.search_hybrid_two_stage(
        query_image_path=args.query,
        coarse_top_k=args.coarse_top_k,
        fine_top_k=args.fine_top_k,
        alpha=args.alpha
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
