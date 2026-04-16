"""
环境变量配置加载器
用于替代 db_config.ini 和 vector_db.ini
"""

import os
from typing import Dict, Any
from pathlib import Path
from dotenv import load_dotenv
from globals_vars import WORK_DIRS, PROJECT_ROOT
# 加载环境变量
# PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _resolve_path(path: str, base_dir: Path = PROJECT_ROOT) -> str:
    """
    解析路径：如果是相对路径，则相对于base_dir；如果是绝对路径，则直接返回
    
    Args:
        path: 路径字符串
        base_dir: 基础目录（默认为项目根目录）
    
    Returns:
        解析后的绝对路径字符串
    """
    if not path:
        return path
    
    path_obj = Path(path)
    if path_obj.is_absolute():
        return str(path_obj)
    else:
        return str(base_dir / path)


def _resolve_model_path(relative_path: str, model_dir: str) -> str:
    """
    解析模型路径：相对于MODEL_DIR
    
    Args:
        relative_path: 相对路径
        model_dir: 模型根目录
    
    Returns:
        完整的模型路径
    """
    if not relative_path:
        return relative_path
    
    # 如果已经是绝对路径，直接返回
    if Path(relative_path).is_absolute():
        return relative_path
    
    # 否则拼接MODEL_DIR
    return str(Path(model_dir) / relative_path)


class VectorDBConfig:
    """向量数据库配置类"""
    
    def __init__(self):
        """从环境变量加载配置"""
        # 获取MODEL_DIR
        self.model_dir = os.getenv("MODEL_DIR", "/home/ubuntu/CV/models")
        
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
        # SigLIP模型配置（相对于MODEL_DIR）
        # ============================================
        self.siglip_model_name = os.getenv("SIGLIP_MODEL_NAME", "google/siglip-so400m-patch14-384")
        self.siglip_model_path = _resolve_model_path(
            os.getenv("SIGLIP_MODEL_PATH", "siglip2-so400m-patch14-384"),
            self.model_dir
        )
        self.siglip_vector_dim = int(os.getenv("SIGLIP_VECTOR_DIM", "1152"))
        self.siglip_collection_name = os.getenv("SIGLIP_COLLECTION_NAME", "PARTS_SIGLIP_SO400M_1152D_V1")
        self.siglip_batch_size = int(os.getenv("SIGLIP_BATCH_SIZE", "32"))
        self.siglip_device = os.getenv("SIGLIP_DEVICE", "cuda")
        
        # ============================================
        # DINOv2模型配置（相对于MODEL_DIR）
        # ============================================
        self.dinov2_model_name = os.getenv("DINOV2_MODEL_NAME", "facebook/dinov2-large")
        self.dinov2_model_path = _resolve_model_path(
            os.getenv("DINOV2_MODEL_PATH", "dinov2-large"),
            self.model_dir
        )
        self.dinov2_vector_dim = int(os.getenv("DINOV2_VECTOR_DIM", "1024"))
        self.dinov2_collection_name = os.getenv("DINOV2_COLLECTION_NAME", "PARTS_DINOV2_LARGE_1024D_V1")
        self.dinov2_patch_tokens_dir = _resolve_path(
            os.getenv("DINOV2_PATCH_TOKENS_DIR", "csrcqsf/biz/railwayparts/vector_db/patch_tokens")
        )
        self.dinov2_device = os.getenv("DINOV2_DEVICE", "cuda")
        
        # ============================================
        # SAM3模型配置（相对于MODEL_DIR）
        # ============================================
        self.sam3_model_path = _resolve_model_path(
            os.getenv("SAM3_MODEL_PATH", "sam3"),
            self.model_dir
        )
        self.sam3_mask_dilate = int(os.getenv("SAM3_MASK_DILATE", "20"))
        self.sam3_bg_color = os.getenv("SAM3_BG_COLOR", "white")
        self.sam3_device = os.getenv("SAM3_DEVICE", "cuda")
        
        # ============================================
        # 索引配置（相对于项目根目录）
        # ============================================
        self.indexing_checkpoint_file = _resolve_path(
            os.getenv("INDEXING_CHECKPOINT_FILE", "csrcqsf/biz/railwayparts/vector_db/checkpoint.json")
        )
        self.indexing_log_dir = _resolve_path(
            os.getenv("INDEXING_LOG_DIR", "csrcqsf/biz/railwayparts/vector_db/logs")
        )
        
        # ============================================
        # 本地配置
        # ============================================
        self.local_image_root = os.getenv("LOCAL_IMAGE_ROOT", "/data/railway_parts_images")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（兼容旧的INI配置格式）"""
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
                'model_name': self.siglip_model_name,
                'model_path': self.siglip_model_path,
                'vector_dim': self.siglip_vector_dim,
                'collection_name': self.siglip_collection_name,
                'batch_size': self.siglip_batch_size,
                'device': self.siglip_device,
            },
            'dinov2': {
                'model_name': self.dinov2_model_name,
                'model_path': self.dinov2_model_path,
                'vector_dim': self.dinov2_vector_dim,
                'collection_name': self.dinov2_collection_name,
                'patch_tokens_dir': self.dinov2_patch_tokens_dir,
                'device': self.dinov2_device,
            },
            'sam3': {
                'model_path': self.sam3_model_path,
                'mask_dilate': self.sam3_mask_dilate,
                'bg_color': self.sam3_bg_color,
                'device': self.sam3_device,
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
        """获取PostgreSQL连接字符串"""
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"
    
    def get_async_pg_dsn(self) -> str:
        """获取PostgreSQL异步连接字符串"""
        return f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"


# 全局配置实例
vector_db_config = VectorDBConfig()


def get_config() -> VectorDBConfig:
    """获取配置实例"""
    return vector_db_config


# 兼容旧代码的函数
def load_config_from_env() -> Dict[str, Any]:
    """
    加载配置（兼容旧的INI格式）
    返回字典格式的配置，可以像ConfigParser一样使用
    """
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
