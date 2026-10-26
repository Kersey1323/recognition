"""配件向量检索运行时的环境变量配置。"""

from __future__ import annotations

import os
from typing import Any, Dict

from csrcqsf.core.runtime_paths import resolve_runtime_paths


def _positive_int_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


def _score_env(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not -1 <= value <= 1:
        raise ValueError(f"{name} 必须在 -1 到 1 之间")
    return value


class VectorDBConfig:
    """向量数据库配置类。"""

    def __init__(self):
        """从环境变量加载配置。"""
        runtime_paths = resolve_runtime_paths()

        # ============================================
        # MinIO配置
        # ============================================
        self.minio_endpoint = os.getenv("MINIO_ENDPOINT", "192.168.100.2:9000")
        self.minio_access_key = os.getenv("MINIO_ACCESS_KEY", "root")
        self.minio_secret_key = os.getenv("MINIO_SECRET_KEY", "REMOVED_CREDENTIAL")
        self.minio_bucket = os.getenv("MINIO_BUCKET", "bfr-ai-files")
        self.minio_secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
        
        # ============================================
        # Milvus配置
        # ============================================
        self.milvus_host = os.getenv("MILVUS_HOST", "localhost")
        self.milvus_port = int(os.getenv("MILVUS_PORT", "19530"))
        self.milvus_user = os.getenv("MILVUS_USER", "")
        self.milvus_password = os.getenv("MILVUS_PASSWORD", "")
        
        # ============================================
        # SigLIP 集合配置（模型推理已迁移至独立服务）
        # ============================================
        self.siglip_collection_name = os.getenv("SIGLIP_COLLECTION_NAME", "PARTS_SIGLIP_SO400M_1152D_V1")
        self.siglip_group_by_item = os.getenv("SIGLIP_GROUP_BY_ITEM", "false").lower() == "true"

        # ============================================
        # DINOv2 集合配置（模型推理已迁移至独立服务）
        # ============================================
        self.dinov2_collection_name = os.getenv("DINOV2_COLLECTION_NAME", "PARTS_DINOV2_LARGE_1024D_V1")
        self.dinov2_patch_tokens_dir = str(runtime_paths.patch_tokens_dir)

        # ============================================
        # 询码自然语言描述使用独立 BGE-M3 Collection，避免与图片索引混用。
        # ============================================
        self.inquiry_text_collection_alias = os.getenv(
            "INQUIRY_TEXT_COLLECTION_ALIAS",
            "PARTS_INQUIRY_BGE_M3_CURRENT",
        )
        self.inquiry_text_embedding_dim = _positive_int_env(
            "INQUIRY_TEXT_EMBEDDING_DIM",
            1024,
        )
        self.inquiry_text_index_batch_size = _positive_int_env(
            "INQUIRY_TEXT_INDEX_BATCH_SIZE",
            128,
        )
        self.inquiry_text_search_oversample = _positive_int_env(
            "INQUIRY_TEXT_SEARCH_OVERSAMPLE",
            5,
        )
        self.inquiry_text_search_min_candidates = _positive_int_env(
            "INQUIRY_TEXT_SEARCH_MIN_CANDIDATES",
            30,
        )
        self.inquiry_text_search_max_candidates = _positive_int_env(
            "INQUIRY_TEXT_SEARCH_MAX_CANDIDATES",
            1000,
        )
        self.inquiry_text_min_score = _score_env("INQUIRY_TEXT_MIN_SCORE", 0.55)

        # ============================================
        # 索引状态与日志统一写入可持久化运行时目录，避免源码只读挂载后写入失败。
        # ============================================
        self.indexing_checkpoint_file = str(runtime_paths.indexing_checkpoint_file)
        self.indexing_log_dir = str(runtime_paths.indexing_log_dir)
        
        # ============================================
        # 本地配置
        # ============================================
        self.local_image_root = os.getenv("LOCAL_IMAGE_ROOT", "/data/railway_parts_images")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为当前运行时使用的配置字典。"""
        return {
            'minio': {
                'endpoint': self.minio_endpoint,
                'access_key': self.minio_access_key,
                'secret_key': self.minio_secret_key,
                'bucket': self.minio_bucket,
                'secure': self.minio_secure,
            },
            'milvus': {
                'host': self.milvus_host,
                'port': self.milvus_port,
                'user': self.milvus_user,
                'password': self.milvus_password,
            },
            'siglip': {
                'collection_name': self.siglip_collection_name,
                'group_by_item': self.siglip_group_by_item,
            },
            'dinov2': {
                'collection_name': self.dinov2_collection_name,
                'patch_tokens_dir': self.dinov2_patch_tokens_dir,
            },
            'inquiry_text': {
                'collection_alias': self.inquiry_text_collection_alias,
                'embedding_dim': self.inquiry_text_embedding_dim,
                'index_batch_size': self.inquiry_text_index_batch_size,
                'search_oversample': self.inquiry_text_search_oversample,
                'search_min_candidates': self.inquiry_text_search_min_candidates,
                'search_max_candidates': self.inquiry_text_search_max_candidates,
                'min_score': self.inquiry_text_min_score,
            },
            'indexing': {
                'checkpoint_file': self.indexing_checkpoint_file,
                'log_dir': self.indexing_log_dir,
            },
            'local': {
                'image_root': self.local_image_root,
            }
        }


# 全局配置实例
vector_db_config = VectorDBConfig()


def get_config() -> VectorDBConfig:
    """获取配置实例。"""
    return vector_db_config


def load_config_from_env() -> Dict[str, Any]:
    """加载当前运行时配置字典。"""
    return vector_db_config.to_dict()


if __name__ == "__main__":
    # 测试配置加载
    config = get_config()
    print("=" * 60)
    print("向量数据库配置")
    print("=" * 60)
    print(f"MinIO: {config.minio_endpoint}")
    print(f"Milvus: {config.milvus_host}:{config.milvus_port}")
    print(f"\nSigLIP Collection: {config.siglip_collection_name}")
    print(f"DINOv2 Collection: {config.dinov2_collection_name}")
    print(f"\nPatch Tokens Dir: {config.dinov2_patch_tokens_dir}")
    print(f"Checkpoint File: {config.indexing_checkpoint_file}")
