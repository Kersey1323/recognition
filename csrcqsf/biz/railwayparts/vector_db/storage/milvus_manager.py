"""
Milvus 统一管理器
集成向量建库和检索功能
"""
import os
import numpy as np
from PIL import Image
from typing import List, Dict, Tuple, Optional, Literal
from configparser import ConfigParser

from csrcqsf.biz.railwayparts.vector_db.models.siglip_extractor import SigLIPExtractor
from csrcqsf.biz.railwayparts.vector_db.models.dinov2_extractor import DINOv2VectorExtractor
from csrcqsf.biz.railwayparts.vector_db.models.model_config import SigLIPConfig, DINOv2Config, MilvusConfig
from csrcqsf.biz.railwayparts.vector_db.storage.collection_manager import CollectionManager
from csrcqsf.biz.railwayparts.vector_db.data.image_loader import ImageLoader
from csrcqsf.biz.railwayparts.vector_db.preprocessing.sam3_preprocessor import SAM3Preprocessor
from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class MilvusManagerV2:
    """Milvus 统一管理器"""

    def __init__(
        self,
        config_path: str = '/home/ubuntu/project-train/recognition/csrcqsf/biz/railwayparts/vector_db/config/vector_db.ini',
        db_config_path: str = '/home/ubuntu/project-train/recognition/csrcqsf/biz/railwayparts/vector_db/config/db_config.ini',
        enable_sam3: bool = True
    ):
        """
        初始化 Milvus 管理器

        Args:
            config_path: 向量数据库配置文件路径
            db_config_path: 数据库连接配置文件路径
            enable_sam3: 是否启用 SAM3 预处理
        """
        logger.info("Initializing Milvus Manager...")

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

        # 初始化 SAM3 预处理器（可选）
        self.sam3_preprocessor = None
        if enable_sam3:
            config_parser = ConfigParser()
            config_parser.read(config_path, encoding='utf-8')
            if config_parser.has_section('sam3'):
                logger.info("Initializing SAM3 preprocessor...")
                self.sam3_preprocessor = SAM3Preprocessor(
                    model_path=config_parser.get('sam3', 'model_path'),
                    mask_dilate=config_parser.getint('sam3', 'mask_dilate'),
                    bg_color=config_parser.get('sam3', 'bg_color'),
                    device=config_parser.get('sam3', 'device'),
                    save_debug_images=config_parser.getboolean('sam3', 'save_debug_images', fallback=False),
                    debug_output_dir=config_parser.get('sam3', 'debug_output_dir', fallback='vector_db/logs/sam3_debug')
                )
                logger.info("SAM3 preprocessor initialized")
            else:
                logger.warning("SAM3 section not found in config, SAM3 preprocessing disabled")

        # 初始化 Milvus Collection 管理器
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

        logger.info("Milvus Manager initialized successfully")

    # ==================== 建库功能 ====================

    async def create_collections(self):
        """创建所有 Collection"""
        logger.info("Creating collections...")
        self.collection_manager.create_siglip_collection(self.siglip_collection)
        self.collection_manager.create_dinov2_collection(self.dinov2_collection)
        logger.info("Collections created")
    
    async def drop_collections(self):
        """删除所有 Collection（清空向量库）"""
        logger.warning("Dropping collections...")
        
        # 删除 SigLIP 集合
        if self.collection_manager.collection_exists(self.siglip_collection):
            self.collection_manager.drop_collection(self.siglip_collection)
            logger.info(f"Dropped SigLIP collection: {self.siglip_collection}")
        else:
            logger.info(f"SigLIP collection does not exist: {self.siglip_collection}")
        
        # 删除 DINOv2 集合
        if self.collection_manager.collection_exists(self.dinov2_collection):
            self.collection_manager.drop_collection(self.dinov2_collection)
            logger.info(f"Dropped DINOv2 collection: {self.dinov2_collection}")
        else:
            logger.info(f"DINOv2 collection does not exist: {self.dinov2_collection}")
        
        logger.warning("All collections dropped")

    async def index_image(
        self,
        image: Image.Image,
        item_id: int,
        item_name: str,
        item_code: str,
        image_id: int,
        image_url: str,
        description: str = ""
    ) -> Tuple[bool, bool]:
        """
        为单张图像建立索引

        Args:
            image: PIL Image 对象
            item_id: 零件 ID
            item_name: 零件名称
            item_code: 零件编码
            image_id: 图像 ID
            image_url: 图像 URL
            description: 描述文本

        Returns:
            (siglip_success, dinov2_success)
        """
        from datetime import datetime

        created_at = datetime.now().isoformat()
        siglip_success = False
        dinov2_success = False

        # SAM3 预处理（如果启用）
        processed_image = image
        if self.sam3_preprocessor is not None:
            try:
                preprocessed = self.sam3_preprocessor.preprocess_image(image, item_name, image_id)
                if preprocessed is not None:
                    processed_image = preprocessed
                    logger.debug(f"SAM3 preprocessing applied for image {image_id}")
                else:
                    logger.warning(f"SAM3 preprocessing failed for {image_id}, using original image")
            except Exception as e:
                logger.error(f"SAM3 preprocessing error for {image_id}: {e}")

        # SigLIP 索引
        try:
            image_vector = self.siglip_extractor.extract_image_features(processed_image)
            text_vector = self.siglip_extractor.extract_text_features(description or item_name)

            siglip_record = {
                "item_id": item_id,
                "item_name": item_name,
                "item_code": item_code,
                "image_id": image_id,
                "image_url": image_url,
                "description": description,
                "image_vector": image_vector.tolist(),
                "text_vector": text_vector.tolist(),
                "created_at": created_at
            }

            self.collection_manager.insert_siglip_records(
                self.siglip_collection,
                [siglip_record]
            )
            siglip_success = True

        except Exception as e:
            logger.error(f"Failed to index SigLIP for image {image_id}: {e}")

        # DINOv2 索引
        try:
            global_vector = self.dinov2_extractor.extract_global_vector(processed_image)
            patch_tokens = self.dinov2_extractor.extract_patch_tokens(processed_image)
            patch_mean = np.mean(patch_tokens, axis=0)

            # 保存 patch tokens
            patch_tokens_path = os.path.join(
                self.patch_tokens_dir,
                f"item_{item_id}_img_{image_id}.npy"
            )
            self.dinov2_extractor.save_patch_tokens(patch_tokens, patch_tokens_path)

            dinov2_record = {
                "item_id": item_id,
                "item_name": item_name,
                "item_code": item_code,
                "image_id": image_id,
                "image_url": image_url,
                "global_vector": global_vector.tolist(),
                "patch_tokens": patch_mean.tolist(),
                "patch_tokens_path": patch_tokens_path,
                "created_at": created_at
            }

            self.collection_manager.insert_dinov2_records(
                self.dinov2_collection,
                [dinov2_record]
            )
            dinov2_success = True

        except Exception as e:
            logger.error(f"Failed to index DINOv2 for image {image_id}: {e}")

        return siglip_success, dinov2_success

    # ==================== 检索功能 ====================

    # TODO 使用文本向量取匹配图像；当前使用的是文本完全匹配
    async def search_by_text(
        self,
        text: str,
        top_k: int = 5
    ) -> List[Dict]:
        """
        文本检索（仅使用 SigLIP）

        Args:
            text: 查询文本
            top_k: 返回结果数量

        Returns:
            检索结果列表
        """
        logger.info(f"Text search: {text}")

        # 提取文本特征
        text_vector = self.siglip_extractor.extract_text_features(text)

        # 在 Milvus 中检索
        results = self.collection_manager.client.search(
            collection_name=self.siglip_collection,
            data=[text_vector.tolist()],
            anns_field="text_vector",
            limit=top_k,
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url"]
        )[0]

        return results

    async def search_by_image(
        self,
        image: Image.Image,
        top_k: int = 5,
        mode: Literal["siglip", "dinov2", "hybrid"] = "hybrid",
        coarse_top_k: int = 30,
        alpha: float = 0.6
    ) -> List[Dict]:
        """
        图像检索

        Args:
            image: PIL Image 对象
            top_k: 返回结果数量
            mode: 检索模式
                - "siglip": 仅使用 SigLIP
                - "dinov2": 仅使用 DINOv2 两阶段检索
                - "hybrid": 混合检索（默认）
            coarse_top_k: 粗排候选数量（仅用于 hybrid 和 dinov2 模式）
            alpha: 加权系数（仅用于 hybrid 模式）

        Returns:
            检索结果列表
        """
        if mode == "siglip":
            return self._search_by_image_siglip(image, top_k)
        elif mode == "dinov2":
            return self._search_by_image_dinov2(image, coarse_top_k, top_k)
        elif mode == "hybrid":
            return self._search_by_image_hybrid(image, coarse_top_k, top_k, alpha)
        else:
            raise ValueError(f"Invalid mode: {mode}")

    def _search_by_image_siglip(
        self,
        image: Image.Image,
        top_k: int
    ) -> List[Dict]:
        """SigLIP 图像检索"""
        logger.info(f"Image search with SigLIP (top-{top_k})")

        # SAM3 预处理查询图像（如果启用）
        processed_image = image
        if self.sam3_preprocessor is not None:
            try:
                # 对查询图像不保存调试图像，使用通用名称
                preprocessed = self.sam3_preprocessor.preprocess_image(image, "query_object", None)
                if preprocessed is not None:
                    processed_image = preprocessed
                    logger.debug("SAM3 preprocessing applied to query image")
            except Exception as e:
                logger.warning(f"SAM3 preprocessing failed for query image: {e}")

        # 提取图像特征
        image_vector = self.siglip_extractor.extract_image_features(processed_image)

        # 在 Milvus 中检索
        results = self.collection_manager.client.search(
            collection_name=self.siglip_collection,
            data=[image_vector.tolist()],
            anns_field="image_vector",
            limit=top_k,
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url"]
        )[0]

        return results

    def _search_by_image_dinov2(
        self,
        image: Image.Image,
        coarse_top_k: int,
        fine_top_k: int
    ) -> List[Dict]:
        """DINOv2 两阶段图像检索"""
        logger.info(f"Image search with DINOv2 two-stage (coarse: {coarse_top_k}, fine: {fine_top_k})")

        # SAM3 预处理查询图像（如果启用）
        processed_image = image
        if self.sam3_preprocessor is not None:
            try:
                preprocessed = self.sam3_preprocessor.preprocess_image(image, "query_object", None)
                if preprocessed is not None:
                    processed_image = preprocessed
                    logger.debug("SAM3 preprocessing applied to query image")
            except Exception as e:
                logger.warning(f"SAM3 preprocessing failed for query image: {e}")

        # 提取查询图像特征
        query_global = self.dinov2_extractor.extract_global_vector(processed_image)
        query_patch_tokens = self.dinov2_extractor.extract_patch_tokens(processed_image)

        # 阶段1: 粗排
        logger.info("  Stage 1: Coarse ranking...")
        coarse_results = self.collection_manager.client.search(
            collection_name=self.dinov2_collection,
            data=[query_global.tolist()],
            anns_field="global_vector",
            limit=coarse_top_k,
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url", "patch_tokens_path"]
        )[0]

        # 阶段2: 精排
        logger.info("  Stage 2: Fine ranking...")
        fine_results = []

        for result in coarse_results:
            patch_tokens_path = result['entity']['patch_tokens_path']

            if not os.path.exists(patch_tokens_path):
                logger.warning(f"Patch tokens not found: {patch_tokens_path}")
                continue

            candidate_patch_tokens = np.load(patch_tokens_path)

            # 计算 patch-level 相似度
            query_norm = query_patch_tokens / (np.linalg.norm(query_patch_tokens, axis=1, keepdims=True) + 1e-8)
            candidate_norm = candidate_patch_tokens / (np.linalg.norm(candidate_patch_tokens, axis=1, keepdims=True) + 1e-8)

            similarity_matrix = np.dot(query_norm, candidate_norm.T)
            max_similarities = similarity_matrix.max(axis=1)
            fine_score = max_similarities.mean()

            fine_results.append({
                'entity': result['entity'],
                'distance': float(fine_score),
                'coarse_distance': result['distance']
            })

        # 按精排分数排序
        fine_results.sort(key=lambda x: x['distance'], reverse=True)
        return fine_results[:fine_top_k]

    def _search_by_image_hybrid(
        self,
        image: Image.Image,
        coarse_top_k: int,
        fine_top_k: int,
        alpha: float
    ) -> List[Dict]:
        """混合图像检索（SigLIP + DINOv2 RRF 融合 + Patch 精排）"""
        logger.info(f"Image search with hybrid mode (coarse: {coarse_top_k}, fine: {fine_top_k}, alpha: {alpha})")

        # SAM3 预处理查询图像（如果启用）
        processed_image = image
        if self.sam3_preprocessor is not None:
            try:
                preprocessed = self.sam3_preprocessor.preprocess_image(image, "query_object", None)
                if preprocessed is not None:
                    processed_image = preprocessed
                    logger.debug("SAM3 preprocessing applied to query image")
            except Exception as e:
                logger.warning(f"SAM3 preprocessing failed for query image: {e}")

        # 提取查询图像特征
        siglip_vector = self.siglip_extractor.extract_image_features(processed_image)
        dinov2_global = self.dinov2_extractor.extract_global_vector(processed_image)
        query_patch_tokens = self.dinov2_extractor.extract_patch_tokens(processed_image)

        # 阶段1: RRF 融合粗排
        logger.info("  Stage 1: RRF fusion...")

        # SigLIP 检索
        siglip_results = self.collection_manager.client.search(
            collection_name=self.siglip_collection,
            data=[siglip_vector.tolist()],
            anns_field="image_vector",
            limit=coarse_top_k * 2,
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url"]
        )[0]

        # DINOv2 检索
        dinov2_results = self.collection_manager.client.search(
            collection_name=self.dinov2_collection,
            data=[dinov2_global.tolist()],
            anns_field="global_vector",
            limit=coarse_top_k * 2,
            output_fields=["item_id", "item_name", "item_code", "image_id", "image_url", "patch_tokens_path"]
        )[0]

        # RRF 融合
        fused_results = self._rrf_fusion([siglip_results, dinov2_results])
        coarse_candidates = fused_results[:coarse_top_k]

        # 阶段2: Patch Token 精排
        logger.info("  Stage 2: Patch token fine ranking...")
        fine_results = []

        for candidate in coarse_candidates:
            image_id = candidate['entity']['image_id']

            # 从 DINOv2 结果中获取 patch_tokens_path
            patch_tokens_path = None
            for dinov2_result in dinov2_results:
                if dinov2_result['entity']['image_id'] == image_id:
                    patch_tokens_path = dinov2_result['entity']['patch_tokens_path']
                    break

            if patch_tokens_path is None or not os.path.exists(patch_tokens_path):
                logger.warning(f"Patch tokens not found for image_id: {image_id}")
                continue

            candidate_patch_tokens = np.load(patch_tokens_path)

            # 计算 patch-level 相似度
            query_norm = query_patch_tokens / (np.linalg.norm(query_patch_tokens, axis=1, keepdims=True) + 1e-8)
            candidate_norm = candidate_patch_tokens / (np.linalg.norm(candidate_patch_tokens, axis=1, keepdims=True) + 1e-8)

            similarity_matrix = np.dot(query_norm, candidate_norm.T)
            max_similarities = similarity_matrix.max(axis=1)
            patch_score = max_similarities.mean()

            # 加权合并分数
            rrf_score = candidate['rrf_score']
            final_score = alpha * rrf_score + (1 - alpha) * patch_score

            fine_results.append({
                'entity': candidate['entity'],
                'distance': float(final_score),
                'rrf_score': float(rrf_score),
                'patch_score': float(patch_score)
            })

        # 按最终分数排序
        fine_results.sort(key=lambda x: x['distance'], reverse=True)
        return fine_results[:fine_top_k]

    def _rrf_fusion(
        self,
        results_list: List[List],
        k: int = 60
    ) -> List[Dict]:
        """
        RRF (Reciprocal Rank Fusion) 算法融合多个检索结果

        Args:
            results_list: 多个检索结果列表
            k: RRF 常数

        Returns:
            融合后的结果列表
        """
        rrf_scores = {}

        for results in results_list:
            for rank, result in enumerate(results, start=1):
                image_id = result['entity']['image_id']
                rrf_score = 1.0 / (k + rank)

                if image_id not in rrf_scores:
                    rrf_scores[image_id] = {
                        'entity': result['entity'],
                        'rrf_score': 0.0
                    }

                rrf_scores[image_id]['rrf_score'] += rrf_score

        # 转换为列表并排序
        fused_results = list(rrf_scores.values())
        fused_results.sort(key=lambda x: x['rrf_score'], reverse=True)

        return fused_results
