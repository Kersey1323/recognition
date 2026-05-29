"""Environment-based configuration for railway-parts vector search."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[5]
load_dotenv(PROJECT_ROOT / ".env")


def _resolve_path(path: str, base_dir: Path = PROJECT_ROOT) -> str:
    """Resolve a relative path against the repository root."""
    if not path:
        return path

    path_obj = Path(path)
    if path_obj.is_absolute():
        return str(path_obj)
    return str(base_dir / path_obj)


class VectorDBConfig:
    """向量数据库配置类。"""

    def __init__(self):
        """从环境变量加载配置。"""

        # ============================================
        # PostgreSQL配置
        # ============================================
        self.pg_host = os.getenv("PG_HOST", "192.168.100.2")
        self.pg_port = int(os.getenv("PG_PORT", "5432"))
        self.pg_database = os.getenv("PG_DATABASE", "zcsf")
        self.pg_user = os.getenv("PG_USER", "root")
        self.pg_password = os.getenv("PG_PASSWORD", "REMOVED_CREDENTIAL")
        
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

        # ============================================
        # DINOv2 集合配置（模型推理已迁移至独立服务）
        # ============================================
        self.dinov2_collection_name = os.getenv("DINOV2_COLLECTION_NAME", "PARTS_DINOV2_LARGE_1024D_V1")
        self.dinov2_patch_tokens_dir = _resolve_path(
            os.getenv("DINOV2_PATCH_TOKENS_DIR", "state/vector_db/patch_tokens")
        )

        # ============================================
        # 索引配置（相对于项目根目录）
        # ============================================
        self.indexing_checkpoint_file = _resolve_path(
            os.getenv("INDEXING_CHECKPOINT_FILE", "state/vector_db/checkpoint.json")
        )
        self.indexing_log_dir = _resolve_path(
            os.getenv("INDEXING_LOG_DIR", "logs/vector_db")
        )
        
        # ============================================
        # 本地配置
        # ============================================
        self.local_image_root = os.getenv("LOCAL_IMAGE_ROOT", "/data/railway_parts_images")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为兼容旧 INI 结构的字典。"""
        return {
            'postgresql': {
                'host': self.pg_host,
                'port': self.pg_port,
                'database': self.pg_database,
                'user': self.pg_user,
                'password': self.pg_password,
            },
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
            },
            'dinov2': {
                'collection_name': self.dinov2_collection_name,
                'patch_tokens_dir': self.dinov2_patch_tokens_dir,
            },
            'indexing': {
                'checkpoint_file': self.indexing_checkpoint_file,
                'log_dir': self.indexing_log_dir,
            },
            'local': {
                'image_root': self.local_image_root,
            }
        }
    
    def get_pg_dsn(self) -> str:
        """获取 PostgreSQL 连接字符串。"""
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"

    def get_async_pg_dsn(self) -> str:
        """获取 PostgreSQL 异步连接字符串。"""
        return f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"


# 全局配置实例
vector_db_config = VectorDBConfig()


def get_config() -> VectorDBConfig:
    """获取配置实例。"""
    return vector_db_config


# 兼容旧代码的函数
def load_config_from_env() -> Dict[str, Any]:
    """加载兼容旧 INI 结构的配置字典。"""
    return vector_db_config.to_dict()


if __name__ == "__main__":
    # 测试配置加载
    config = get_config()
    print("=" * 60)
    print("向量数据库配置")
    print("=" * 60)
    print(f"\nPostgreSQL: {config.pg_host}:{config.pg_port}/{config.pg_database}")
    print(f"MinIO: {config.minio_endpoint}")
    print(f"Milvus: {config.milvus_host}:{config.milvus_port}")
    print(f"\nSigLIP Collection: {config.siglip_collection_name}")
    print(f"DINOv2 Collection: {config.dinov2_collection_name}")
    print(f"\nPatch Tokens Dir: {config.dinov2_patch_tokens_dir}")
    print(f"Checkpoint File: {config.indexing_checkpoint_file}")
