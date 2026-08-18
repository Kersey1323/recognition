"""
Milvus 统一管理器
集成向量建库和检索功能
"""
import os
import uuid
import numpy as np
from PIL import Image
from typing import List, Dict, Tuple, Optional, Literal

from csrcqsf.modules.railway_parts.vector_search.config.env_config import get_config
from csrcqsf.modules.railway_parts.vector_search.repositories.image_loader import (
    ImageLoader,
)
from csrcqsf.modules.railway_parts.vector_search.storage.collection_manager import (
    CollectionManager,
)
from csrcqsf.modules.railway_parts.vector_search.utils.logger import setup_logger
from csrcqsf.infra.external.model_client import get_model_client

logger = setup_logger(__name__)

IMAGE_VARIANT_ORIGINAL = "original"
IMAGE_VARIANT_SEGMENTED = "segmented"
LEGACY_PATCH_TOKENS_MARKER = os.path.join(
    "csrcqsf", "biz", "railwayparts", "vector_db", "patch_tokens"
) + os.sep


class MilvusManagerV2:
    """Milvus 统一管理器"""

    def __init__(
        self,
        config_path: Optional[str] = None,
        db_config_path: Optional[str] = None,
    ):
        """
        初始化 Milvus 管理器

        模型推理已迁移至独立的模型服务（MODEL_SERVICE_URL），
        本地不再加载 SigLIP/DINOv2 模型。
        """
        logger.info("Initializing Milvus Manager...")

        env_config = get_config()

        if config_path or db_config_path:
            logger.warning(
                "config_path and db_config_path parameters are deprecated. "
                "Configuration is now loaded from environment variables (.env file)."
            )

        self.model_client = get_model_client()
        self.siglip_collection = env_config.siglip_collection_name
        self.dinov2_collection = env_config.dinov2_collection_name
        self.patch_tokens_dir = env_config.dinov2_patch_tokens_dir

        # 初始化 Milvus Collection 管理器
        logger.info(f"Connecting to Milvus at {env_config.milvus_host}:{env_config.milvus_port}")
        self.collection_manager = CollectionManager(
            host=env_config.milvus_host,
            port=env_config.milvus_port
        )
        self.image_variant_supported = self._detect_image_variant_support()
        self.patch_token_key_supported = self._detect_patch_token_key_support()

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

        logger.info("Milvus Manager initialized successfully (models via remote service)")
        logger.info(f"  - SigLIP Collection: {self.siglip_collection}")
        logger.info(f"  - DINOv2 Collection: {self.dinov2_collection}")
        logger.info(f"  - Image Variant Supported: {self.image_variant_supported}")
        logger.info(f"  - Patch Token Key Supported: {self.patch_token_key_supported}")

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

    def delete_item_image_index(self, item_id: int, image_id: int) -> dict[str, int]:
        """删除指定 item_id + image_id 在 V2 collections 中的向量记录。"""
        siglip_deleted = self.collection_manager.delete_by_item_image_id(
            self.siglip_collection,
            item_id,
            image_id,
        )
        dinov2_deleted = self.collection_manager.delete_by_item_image_id(
            self.dinov2_collection,
            item_id,
            image_id,
        )
        return {
            "siglip_deleted": siglip_deleted,
            "dinov2_deleted": dinov2_deleted,
            "total_deleted": siglip_deleted + dinov2_deleted,
        }

    def delete_item_patch_tokens(self, item_id: int) -> int:
        """删除配件重建前遗留的全部原图和分割图 patch tokens。"""
        deleted = 0
        if not os.path.isdir(self.patch_tokens_dir):
            return deleted
        prefix = f"item_{item_id}_img_"
        for filename in os.listdir(self.patch_tokens_dir):
            if filename.startswith(prefix) and filename.endswith(".npy"):
                os.remove(os.path.join(self.patch_tokens_dir, filename))
                deleted += 1
        return deleted

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
                    "Recreate V2 collections to persist the original image variant explicitly."
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

    def _detect_patch_token_key_support(self) -> bool:
        checker = getattr(self.collection_manager, "collection_has_field", None)
        if checker is None:
            return True

        try:
            return bool(checker(self.dinov2_collection, "patch_token_key"))
        except Exception as e:
            logger.warning(
                f"Failed to inspect Milvus schema for patch_token_key support: {e}; "
                "falling back to legacy patch_tokens_path mode."
            )
            return False

    def _supports_patch_token_key(self) -> bool:
        supported = getattr(self, "patch_token_key_supported", None)
        if supported is not None:
            return bool(supported)
        return self._detect_patch_token_key_support()

    def _build_patch_token_key(self, item_id: int, image_id: int, image_variant: Optional[str]) -> str:
        if self._supports_image_variant() and image_variant:
            return f"item_{item_id}_img_{image_id}_{image_variant}.npy"
        return f"item_{item_id}_img_{image_id}.npy"

    def _build_patch_tokens_path(self, patch_token_key: str) -> str:
        if os.path.isabs(patch_token_key):
            return patch_token_key
        return os.path.join(self.patch_tokens_dir, patch_token_key)

    def _map_legacy_patch_tokens_path(self, legacy_path: str) -> Optional[str]:
        normalized = str(legacy_path).replace("\\", os.sep)
        marker_index = normalized.find(LEGACY_PATCH_TOKENS_MARKER)
        if marker_index < 0:
            return None
        relative_part = normalized[marker_index + len(LEGACY_PATCH_TOKENS_MARKER):]
        if relative_part == "":
            return None
        return os.path.join(self.patch_tokens_dir, relative_part)

    def _resolve_patch_tokens_path(self, entity: Dict) -> Optional[str]:
        patch_token_key = entity.get("patch_token_key")
        if patch_token_key:
            candidate = self._build_patch_tokens_path(str(patch_token_key))
            if os.path.exists(candidate):
                return candidate

        legacy_path = entity.get("patch_tokens_path")
        if legacy_path:
            mapped_path = self._map_legacy_patch_tokens_path(str(legacy_path))
            if mapped_path and os.path.exists(mapped_path):
                return mapped_path
        if legacy_path and os.path.exists(str(legacy_path)):
            return str(legacy_path)

        if patch_token_key:
            return self._build_patch_tokens_path(str(patch_token_key))
        if legacy_path:
            mapped_path = self._map_legacy_patch_tokens_path(str(legacy_path))
            if mapped_path:
                return mapped_path
        if legacy_path:
            return str(legacy_path)
        return None

    def _build_search_output_fields(self, include_patch_tokens_path: bool = False) -> list[str]:
        fields = ["item_id", "item_name", "item_code", "image_id"]
        if self._supports_image_variant():
            fields.append("image_variant")
        fields.append("image_url")
        if include_patch_tokens_path:
            if self._supports_patch_token_key():
                fields.append("patch_token_key")
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

        variant_supported = self._supports_image_variant()
        if variant_supported:
            image_variants: list[tuple[Optional[str], Image.Image]] = [
                (IMAGE_VARIANT_ORIGINAL, image),
            ]
        else:
            image_variants = [(None, image)]

        # SigLIP 索引
        try:
            text_vector = await self.model_client.siglip_text_features(description or item_name)
            siglip_records = []
            for image_variant, variant_image in image_variants:
                image_vector = await self.model_client.siglip_image_features(variant_image)
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
                global_vector = await self.model_client.dinov2_global_vector(variant_image)
                patch_tokens = await self.model_client.dinov2_patch_tokens(variant_image)
                patch_mean = np.mean(patch_tokens, axis=0)

                patch_token_key = self._build_patch_token_key(item_id, image_id, image_variant)
                patch_tokens_path = self._build_patch_tokens_path(patch_token_key)
                os.makedirs(os.path.dirname(patch_tokens_path), exist_ok=True)
                np.save(patch_tokens_path, patch_tokens)

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
                if self._supports_patch_token_key():
                    record["patch_token_key"] = patch_token_key
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

    async def index_precomputed_features(
        self,
        *,
        item_id: int,
        item_name: str,
        item_code: str,
        image_id: int,
        image_url: str,
        description: str,
        siglip_image_vector: np.ndarray,
        siglip_text_vector: np.ndarray,
        dinov2_global_vector: np.ndarray,
        dinov2_patch_tokens: np.ndarray,
        image_variant: str = IMAGE_VARIANT_SEGMENTED,
    ) -> Tuple[bool, bool]:
        """将模型服务一次性返回的分割图特征写入两套 V2 索引。"""
        from datetime import datetime

        created_at = datetime.now().isoformat()
        variant_supported = self._supports_image_variant()
        siglip_success = False
        dinov2_success = False

        siglip_record = {
            "item_id": item_id,
            "item_name": item_name,
            "item_code": item_code,
            "image_id": image_id,
            "image_url": image_url,
            "description": description,
            "image_vector": np.asarray(siglip_image_vector).tolist(),
            "text_vector": np.asarray(siglip_text_vector).tolist(),
            "created_at": created_at,
        }
        if variant_supported:
            siglip_record["image_variant"] = image_variant
        try:
            self.collection_manager.insert_siglip_records(
                self.siglip_collection,
                [siglip_record],
            )
            siglip_success = True
        except Exception as exc:
            logger.error(
                f"Failed to index precomputed SigLIP for image {image_id}: {exc}"
            )

        try:
            patch_tokens = np.asarray(dinov2_patch_tokens, dtype=np.float32)
            patch_token_key = self._build_patch_token_key(
                item_id,
                image_id,
                image_variant if variant_supported else None,
            )
            patch_tokens_path = self._build_patch_tokens_path(patch_token_key)
            os.makedirs(os.path.dirname(patch_tokens_path), exist_ok=True)
            temporary_path = f"{patch_tokens_path}.tmp-{uuid.uuid4().hex}"
            try:
                with open(temporary_path, "wb") as temporary_file:
                    np.save(temporary_file, patch_tokens)
                os.replace(temporary_path, patch_tokens_path)
            finally:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)

            dinov2_record = {
                "item_id": item_id,
                "item_name": item_name,
                "item_code": item_code,
                "image_id": image_id,
                "image_url": image_url,
                "global_vector": np.asarray(dinov2_global_vector).tolist(),
                "patch_tokens": np.mean(patch_tokens, axis=0).tolist(),
                "patch_tokens_path": patch_tokens_path,
                "created_at": created_at,
            }
            if self._supports_patch_token_key():
                dinov2_record["patch_token_key"] = patch_token_key
            if variant_supported:
                dinov2_record["image_variant"] = image_variant
            self.collection_manager.insert_dinov2_records(
                self.dinov2_collection,
                [dinov2_record],
            )
            dinov2_success = True
        except Exception as exc:
            logger.error(
                f"Failed to index precomputed DINOv2 for image {image_id}: {exc}"
            )

        return siglip_success, dinov2_success

    # ==================== 检索功能 ====================

    @staticmethod
    def _build_item_filter(item_ids: list[int] | None) -> str:
        if item_ids is None:
            return ""
        normalized_ids = sorted({int(item_id) for item_id in item_ids})
        return f"item_id IN [{','.join(str(item_id) for item_id in normalized_ids)}]"

    @classmethod
    def _item_filter_kwargs(cls, item_ids: list[int] | None) -> dict[str, str]:
        item_filter = cls._build_item_filter(item_ids)
        return {"filter": item_filter} if item_filter else {}

    # TODO 使用文本向量取匹配图像；当前使用的是文本完全匹配
    async def search_by_text(
        self,
        text: str,
        top_k: int = 5,
        item_ids: list[int] | None = None,
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
        text_vector = await self.model_client.siglip_text_features(text)

        # 在 Milvus 中检索
        results = self.collection_manager.client.search(
            collection_name=self.siglip_collection,
            data=[text_vector.tolist()],
            anns_field="text_vector",
            limit=top_k * 3,
            output_fields=self._build_search_output_fields(),
            **self._item_filter_kwargs(item_ids),
        )[0]

        return self._dedupe_hits_by_image_id(results)[:top_k]

    async def search_by_image(
        self,
        image: Image.Image,
        top_k: int = 5,
        mode: Literal["siglip", "dinov2", "hybrid"] = "hybrid",
        coarse_top_k: int = 30,
        alpha: float = 0.6,
        item_ids: list[int] | None = None,
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
            return await self._search_by_image_siglip(image, top_k, item_ids)
        elif mode == "dinov2":
            return await self._search_by_image_dinov2(
                image, coarse_top_k, top_k, item_ids
            )
        elif mode == "hybrid":
            return await self._search_by_image_hybrid(
                image, coarse_top_k, top_k, alpha, item_ids
            )
        else:
            raise ValueError(f"Invalid mode: {mode}")

    async def _search_by_image_siglip(
        self,
        image: Image.Image,
        top_k: int,
        item_ids: list[int] | None = None,
    ) -> List[Dict]:
        """SigLIP 图像检索"""
        logger.info(f"Image search with SigLIP (top-{top_k})")

        # 提取图像特征
        image_vector = await self.model_client.siglip_image_features(image)

        # 在 Milvus 中检索
        results = self.collection_manager.client.search(
            collection_name=self.siglip_collection,
            data=[image_vector.tolist()],
            anns_field="image_vector",
            limit=top_k * 3,
            output_fields=self._build_search_output_fields(),
            **self._item_filter_kwargs(item_ids),
        )[0]

        return self._dedupe_hits_by_image_id(results)[:top_k]

    async def _search_by_image_dinov2(
        self,
        image: Image.Image,
        coarse_top_k: int,
        fine_top_k: int,
        item_ids: list[int] | None = None,
    ) -> List[Dict]:
        """DINOv2 两阶段图像检索"""
        logger.info(f"Image search with DINOv2 two-stage (coarse: {coarse_top_k}, fine: {fine_top_k})")

        # 提取查询图像特征
        query_global = await self.model_client.dinov2_global_vector(image)
        query_patch_tokens = await self.model_client.dinov2_patch_tokens(image)

        # 阶段1: 粗排
        logger.info("  Stage 1: Coarse ranking...")
        coarse_results = self.collection_manager.client.search(
            collection_name=self.dinov2_collection,
            data=[query_global.tolist()],
            anns_field="global_vector",
            limit=coarse_top_k * 3,
            output_fields=self._build_search_output_fields(include_patch_tokens_path=True),
            **self._item_filter_kwargs(item_ids),
        )[0]
        coarse_results = self._dedupe_hits_by_image_id(coarse_results)

        # 阶段2: 精排
        logger.info("  Stage 2: Fine ranking...")
        fine_results = []

        for result in coarse_results:
            patch_tokens_path = self._resolve_patch_tokens_path(result["entity"])

            if patch_tokens_path is None or not os.path.exists(patch_tokens_path):
                logger.warning(f"Patch tokens not found: {patch_tokens_path}")
                fine_results.append({
                    "entity": result["entity"],
                    "distance": float(result["distance"]),
                    "coarse_distance": float(result["distance"]),
                    "fine_rerank_skipped": True,
                })
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
                'coarse_distance': result['distance'],
                'fine_rerank_skipped': False,
            })

        # 按精排分数排序
        fine_results.sort(key=lambda x: x['distance'], reverse=True)
        return self._dedupe_hits_by_image_id(fine_results)[:fine_top_k]

    async def _search_by_image_hybrid(
        self,
        image: Image.Image,
        coarse_top_k: int,
        fine_top_k: int,
        alpha: float,
        item_ids: list[int] | None = None,
    ) -> List[Dict]:
        """混合图像检索（SigLIP + DINOv2 RRF 融合 + Patch 精排）"""
        logger.info(f"Image search with hybrid mode (coarse: {coarse_top_k}, fine: {fine_top_k}, alpha: {alpha})")

        # 提取查询图像特征
        siglip_vector = await self.model_client.siglip_image_features(image)
        dinov2_global = await self.model_client.dinov2_global_vector(image)
        query_patch_tokens = await self.model_client.dinov2_patch_tokens(image)

        # 阶段1: RRF 融合粗排
        logger.info("  Stage 1: RRF fusion...")

        # SigLIP 检索
        siglip_results = self.collection_manager.client.search(
            collection_name=self.siglip_collection,
            data=[siglip_vector.tolist()],
            anns_field="image_vector",
            limit=coarse_top_k * 2,
            output_fields=self._build_search_output_fields(),
            **self._item_filter_kwargs(item_ids),
        )[0]

        # DINOv2 检索
        dinov2_results = self.collection_manager.client.search(
            collection_name=self.dinov2_collection,
            data=[dinov2_global.tolist()],
            anns_field="global_vector",
            limit=coarse_top_k * 2,
            output_fields=self._build_search_output_fields(include_patch_tokens_path=True),
            **self._item_filter_kwargs(item_ids),
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
            patch_tokens_path = (
                None
                if dinov2_result is None
                else self._resolve_patch_tokens_path(dinov2_result["entity"])
            )

            if patch_tokens_path is None or not os.path.exists(patch_tokens_path):
                logger.warning(f"Patch tokens not found for image_id: {image_id}")
                fine_results.append({
                    "entity": candidate["entity"],
                    "distance": float(candidate["rrf_score"]),
                    "rrf_score": float(candidate["rrf_score"]),
                    "patch_score": None,
                    "fine_rerank_skipped": True,
                })
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
                'patch_score': float(patch_score),
                'fine_rerank_skipped': False,
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


MilvusManager = MilvusManagerV2
