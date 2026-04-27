"""
Milvus 统一管理器
集成向量建库和检索功能
"""
import os
import numpy as np
from PIL import Image
from typing import List, Dict, Tuple, Optional, Literal

from csrcqsf.biz.railwayparts.vector_db.models.siglip_extractor import SigLIPExtractor
from csrcqsf.biz.railwayparts.vector_db.models.dinov2_extractor import DINOv2VectorExtractor
from csrcqsf.biz.railwayparts.vector_db.models.model_config import SigLIPConfig, DINOv2Config, MilvusConfig
from csrcqsf.biz.railwayparts.vector_db.storage.collection_manager import CollectionManager
from csrcqsf.biz.railwayparts.vector_db.data.image_loader import ImageLoader
from csrcqsf.biz.railwayparts.vector_db.preprocessing.sam3_preprocessor import SAM3Preprocessor
from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger
from csrcqsf.biz.railwayparts.vector_db.config.env_config import get_config

logger = setup_logger(__name__)

IMAGE_VARIANT_ORIGINAL = "original"
IMAGE_VARIANT_SAM3_SEGMENTED = "sam3_segmented"


class MilvusManagerV2:
    """Milvus 统一管理器"""

    def __init__(
        self,
        config_path: Optional[str] = None,  # 保留参数以兼容旧代码，但不再使用
        db_config_path: Optional[str] = None,  # 保留参数以兼容旧代码，但不再使用
        enable_sam3: bool = True
    ):
        """
        初始化 Milvus 管理器

        Args:
            config_path: (已废弃) 向量数据库配置文件路径，现在从环境变量读取
            db_config_path: (已废弃) 数据库连接配置文件路径，现在从环境变量读取
            enable_sam3: 是否启用 SAM3 预处理
        """
        logger.info("Initializing Milvus Manager...")
        
        # 从环境变量加载配置
        env_config = get_config()
        
        # 如果传入了旧的配置文件路径，发出警告
        if config_path or db_config_path:
            logger.warning(
                "config_path and db_config_path parameters are deprecated. "
                "Configuration is now loaded from environment variables (.env file). "
                "Please update your code to remove these parameters."
            )

        # 初始化 SigLIP 模型
        logger.info(f"Loading SigLIP model from {env_config.siglip_model_path}")
        self.siglip_extractor = SigLIPExtractor(
            model_path=env_config.siglip_model_path,
            device=env_config.siglip_device
        )
        self.siglip_collection = env_config.siglip_collection_name

        # 初始化 DINOv2 模型
        logger.info(f"Loading DINOv2 model from {env_config.dinov2_model_path}")
        self.dinov2_extractor = DINOv2VectorExtractor(
            model_name=env_config.dinov2_model_path,
            device=env_config.dinov2_device
        )
        self.dinov2_collection = env_config.dinov2_collection_name
        self.patch_tokens_dir = env_config.dinov2_patch_tokens_dir

        # 初始化 SAM3 预处理器（可选）
        self.sam3_preprocessor = None
        if enable_sam3 and env_config.sam3_model_path:
            logger.info(f"Initializing SAM3 preprocessor from {env_config.sam3_model_path}")
            try:
                self.sam3_preprocessor = SAM3Preprocessor(
                    model_path=env_config.sam3_model_path,
                    mask_dilate=env_config.sam3_mask_dilate,
                    bg_color=env_config.sam3_bg_color,
                    device=env_config.sam3_device,
                    save_debug_images=False,
                    debug_output_dir=os.path.join(env_config.indexing_log_dir, 'sam3_debug')
                )
                logger.info("SAM3 preprocessor initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize SAM3 preprocessor: {e}")
                logger.warning("SAM3 preprocessing will be disabled")

        # 初始化 Milvus Collection 管理器
        logger.info(f"Connecting to Milvus at {env_config.milvus_host}:{env_config.milvus_port}")
        self.collection_manager = CollectionManager(
            host=env_config.milvus_host,
            port=env_config.milvus_port
        )
        self.image_variant_supported = self._detect_image_variant_support()
        self.last_preprocess_outcome = None

        # 初始化图像加载器
        logger.info(f"Initializing image loader with MinIO endpoint: {env_config.minio_endpoint}")
        self.image_loader = ImageLoader(
            minio_endpoint=env_config.minio_endpoint,
            minio_access_key=env_config.minio_access_key,
            minio_secret_key=env_config.minio_secret_key,
            minio_bucket=env_config.minio_bucket,
            minio_secure=env_config.minio_secure,
            local_image_root=env_config.local_image_root
        )

        logger.info("Milvus Manager initialized successfully")
        logger.info(f"  - SigLIP Collection: {self.siglip_collection}")
        logger.info(f"  - DINOv2 Collection: {self.dinov2_collection}")
        logger.info(f"  - SAM3 Enabled: {self.sam3_preprocessor is not None}")
        logger.info(f"  - Image Variant Supported: {self.image_variant_supported}")

    def get_statistics_snapshot(self) -> dict[str, object]:
        """获取 V2 collection 的统计快照。"""
        siglip_count = self.collection_manager.get_collection_entity_count(self.siglip_collection)
        dinov2_count = self.collection_manager.get_collection_entity_count(self.dinov2_collection)
        siglip_item_ids = self.collection_manager.iter_collection_item_ids(self.siglip_collection)
        dinov2_item_ids = self.collection_manager.iter_collection_item_ids(self.dinov2_collection)
        return {
            "siglip_count": siglip_count,
            "dinov2_count": dinov2_count,
            "siglip_item_ids": siglip_item_ids,
            "dinov2_item_ids": dinov2_item_ids,
        }

    def get_item_index_state_snapshot(self) -> dict[int, dict[str, int]]:
        """按 item_id 聚合当前 V2 索引状态。"""
        siglip_counts = self.collection_manager.get_collection_item_counts(self.siglip_collection)
        dinov2_item_ids = self.collection_manager.iter_collection_item_ids(self.dinov2_collection)

        snapshot: dict[int, dict[str, int]] = {}
        for item_id, image_count in siglip_counts.items():
            snapshot[item_id] = {
                "has_v2_index": 1 if item_id in dinov2_item_ids else 0,
                "v2_indexed_image_num": image_count if item_id in dinov2_item_ids else 0,
            }

        for item_id in dinov2_item_ids:
            snapshot.setdefault(
                item_id,
                {
                    "has_v2_index": 0,
                    "v2_indexed_image_num": 0,
                },
            )

        return snapshot

    def delete_item_index(self, item_id: int) -> dict[str, int]:
        """删除指定 item_id 在 V2 collections 中的所有向量记录。"""
        return {
            "siglip_deleted": self.collection_manager.delete_by_item_id(self.siglip_collection, item_id),
            "dinov2_deleted": self.collection_manager.delete_by_item_id(self.dinov2_collection, item_id),
        }

    def _dedupe_hits_by_image_id(self, hits: List[Dict]) -> List[Dict]:
        """按源 image_id 去重，保留分数更高的一条变体命中。"""
        best_by_image_id: dict[int, Dict] = {}
        for hit in hits:
            entity = hit.get("entity", {})
            image_id = entity.get("image_id")
            if image_id is None:
                continue

            image_id_int = int(image_id)
            current = best_by_image_id.get(image_id_int)
            current_score = float(current.get("distance", float("-inf"))) if current else float("-inf")
            hit_score = float(hit.get("distance", float("-inf")))
            if current is None or hit_score > current_score:
                best_by_image_id[image_id_int] = hit

        return sorted(
            best_by_image_id.values(),
            key=lambda item: float(item.get("distance", float("-inf"))),
            reverse=True,
        )

    def _detect_image_variant_support(self) -> bool:
        """检测当前两个 V2 collection 是否都支持 image_variant 字段。"""
        checker = getattr(self.collection_manager, "collection_has_field", None)
        if checker is None:
            return True

        try:
            siglip_supported = checker(self.siglip_collection, "image_variant")
            dinov2_supported = checker(self.dinov2_collection, "image_variant")
            supported = bool(siglip_supported and dinov2_supported)
            if not supported:
                logger.warning(
                    "Milvus collections do not support image_variant; "
                    "falling back to legacy single-representation mode. "
                    "Recreate V2 collections to enable original+segmented dual-write."
                )
            return supported
        except Exception as e:
            logger.warning(
                f"Failed to inspect Milvus schema for image_variant support: {e}; "
                "falling back to legacy single-representation mode."
            )
            return False

    def _supports_image_variant(self) -> bool:
        supported = getattr(self, "image_variant_supported", None)
        if supported is not None:
            return bool(supported)
        return self._detect_image_variant_support()

    def _build_search_output_fields(self, include_patch_tokens_path: bool = False) -> list[str]:
        fields = ["item_id", "item_name", "item_code", "image_id"]
        if self._supports_image_variant():
            fields.append("image_variant")
        fields.append("image_url")
        if include_patch_tokens_path:
            fields.append("patch_tokens_path")
        return fields

    # ==================== 建库功能 ====================

    def create_collections(self):
        """创建所有 Collection"""
        logger.info("Creating collections...")
        self.collection_manager.create_siglip_collection(self.siglip_collection)
        self.collection_manager.create_dinov2_collection(self.dinov2_collection)
        logger.info("Collections created")
    
    def drop_collections(self):
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

        preprocess_outcome = None
        if self.sam3_preprocessor is not None:
            try:
                preprocess_outcome = self.sam3_preprocessor.preprocess_image_with_metadata(
                    image=image,
                    item_name=item_name,
                    image_id=image_id,
                )
                if preprocess_outcome.result_image is not None:
                    logger.debug(f"SAM3 preprocessing applied for image {image_id}")
                else:
                    logger.warning(f"SAM3 preprocessing failed for {image_id}, using original image")
            except Exception as e:
                logger.error(f"SAM3 preprocessing error for {image_id}: {e}")
        self.last_preprocess_outcome = preprocess_outcome

        variant_supported = self._supports_image_variant()
        if variant_supported:
            image_variants: list[tuple[Optional[str], Image.Image]] = [
                (IMAGE_VARIANT_ORIGINAL, image),
            ]
            if preprocess_outcome is not None and preprocess_outcome.result_image is not None:
                image_variants.append(
                    (IMAGE_VARIANT_SAM3_SEGMENTED, preprocess_outcome.result_image)
                )
        else:
            legacy_image = (
                preprocess_outcome.result_image
                if preprocess_outcome is not None and preprocess_outcome.result_image is not None
                else image
            )
            image_variants = [(None, legacy_image)]

        # SigLIP 索引
        try:
            text_vector = self.siglip_extractor.extract_text_features(description or item_name)
            siglip_records = []
            for image_variant, variant_image in image_variants:
                image_vector = self.siglip_extractor.extract_image_features(variant_image)
                record = {
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_code": item_code,
                    "image_id": image_id,
                    "image_url": image_url,
                    "description": description,
                    "image_vector": image_vector.tolist(),
                    "text_vector": text_vector.tolist(),
                    "created_at": created_at,
                }
                if variant_supported and image_variant is not None:
                    record["image_variant"] = image_variant
                siglip_records.append(record)

            self.collection_manager.insert_siglip_records(
                self.siglip_collection,
                siglip_records
            )
            siglip_success = True

        except Exception as e:
            logger.error(f"Failed to index SigLIP for image {image_id}: {e}")

        # DINOv2 索引
        try:
            dinov2_records = []
            for image_variant, variant_image in image_variants:
                global_vector = self.dinov2_extractor.extract_global_vector(variant_image)
                patch_tokens = self.dinov2_extractor.extract_patch_tokens(variant_image)
                patch_mean = np.mean(patch_tokens, axis=0)

                patch_filename = (
                    f"item_{item_id}_img_{image_id}_{image_variant}.npy"
                    if variant_supported and image_variant is not None
                    else f"item_{item_id}_img_{image_id}.npy"
                )
                patch_tokens_path = os.path.join(self.patch_tokens_dir, patch_filename)
                self.dinov2_extractor.save_patch_tokens(patch_tokens, patch_tokens_path)

                record = {
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_code": item_code,
                    "image_id": image_id,
                    "image_url": image_url,
                    "global_vector": global_vector.tolist(),
                    "patch_tokens": patch_mean.tolist(),
                    "patch_tokens_path": patch_tokens_path,
                    "created_at": created_at,
                }
                if variant_supported and image_variant is not None:
                    record["image_variant"] = image_variant
                dinov2_records.append(record)

            self.collection_manager.insert_dinov2_records(
                self.dinov2_collection,
                dinov2_records
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
            limit=top_k * 3,
            output_fields=self._build_search_output_fields()
        )[0]

        return self._dedupe_hits_by_image_id(results)[:top_k]

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
            limit=top_k * 3,
            output_fields=self._build_search_output_fields()
        )[0]

        return self._dedupe_hits_by_image_id(results)[:top_k]

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
            limit=coarse_top_k * 3,
            output_fields=self._build_search_output_fields(include_patch_tokens_path=True)
        )[0]
        coarse_results = self._dedupe_hits_by_image_id(coarse_results)

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
        return self._dedupe_hits_by_image_id(fine_results)[:fine_top_k]

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
            output_fields=self._build_search_output_fields()
        )[0]

        # DINOv2 检索
        dinov2_results = self.collection_manager.client.search(
            collection_name=self.dinov2_collection,
            data=[dinov2_global.tolist()],
            anns_field="global_vector",
            limit=coarse_top_k * 2,
            output_fields=self._build_search_output_fields(include_patch_tokens_path=True)
        )[0]

        # RRF 融合
        fused_results = self._rrf_fusion([siglip_results, dinov2_results])
        coarse_candidates = fused_results[:coarse_top_k]

        dinov2_best_by_image_id = {
            int(result["entity"]["image_id"]): result
            for result in self._dedupe_hits_by_image_id(dinov2_results)
        }

        # 阶段2: Patch Token 精排
        logger.info("  Stage 2: Patch token fine ranking...")
        fine_results = []

        for candidate in coarse_candidates:
            image_id = candidate['entity']['image_id']
            dinov2_result = dinov2_best_by_image_id.get(int(image_id))
            patch_tokens_path = None if dinov2_result is None else dinov2_result['entity']['patch_tokens_path']

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
            deduped_results = self._dedupe_hits_by_image_id(results)
            for rank, result in enumerate(deduped_results, start=1):
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
