"""
模型配置管理模块
"""
from dataclasses import dataclass
from configparser import ConfigParser


@dataclass
class SigLIPConfig:
    """SigLIP collection 配置。模型推理由独立模型服务负责。"""
    vector_dim: int
    collection_name: str
    batch_size: int

    @classmethod
    def from_config(cls, config_path: str) -> "SigLIPConfig":
        """
        从配置文件加载 SigLIP 配置

        Args:
            config_path: 配置文件路径

        Returns:
            SigLIPConfig 实例
        """
        parser = ConfigParser()
        parser.read(config_path, encoding='utf-8')

        return cls(
            vector_dim=parser.getint('siglip', 'vector_dim'),
            collection_name=parser.get('siglip', 'collection_name'),
            batch_size=parser.getint('siglip', 'batch_size'),
        )


@dataclass
class DINOv2Config:
    """DINOv2 collection 配置。模型推理由独立模型服务负责。"""
    vector_dim: int
    collection_name: str
    patch_tokens_dir: str

    @classmethod
    def from_config(cls, config_path: str) -> "DINOv2Config":
        """
        从配置文件加载 DINOv2 配置

        Args:
            config_path: 配置文件路径

        Returns:
            DINOv2Config 实例
        """
        parser = ConfigParser()
        parser.read(config_path, encoding='utf-8')

        return cls(
            vector_dim=parser.getint('dinov2', 'vector_dim'),
            collection_name=parser.get('dinov2', 'collection_name'),
            patch_tokens_dir=parser.get('dinov2', 'patch_tokens_dir'),
        )


@dataclass
class MilvusConfig:
    """Milvus 连接配置"""
    host: str
    port: int
    user: str
    password: str

    @classmethod
    def from_config(cls, config_path: str) -> "MilvusConfig":
        """
        从配置文件加载 Milvus 配置

        Args:
            config_path: 配置文件路径

        Returns:
            MilvusConfig 实例
        """
        parser = ConfigParser()
        parser.read(config_path, encoding='utf-8')

        return cls(
            host=parser.get('milvus', 'host'),
            port=parser.getint('milvus', 'port'),
            user=parser.get('milvus', 'user'),
            password=parser.get('milvus', 'password')
        )
