"""
模型配置管理模块
"""
from dataclasses import dataclass
from configparser import ConfigParser
from typing import Optional


@dataclass
class SigLIPConfig:
    """SigLIP 模型配置"""
    model_name: str
    model_path: str
    vector_dim: int
    collection_name: str
    batch_size: int
    device: str

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
            model_name=parser.get('siglip', 'model_name'),
            model_path=parser.get('siglip', 'model_path'),
            vector_dim=parser.getint('siglip', 'vector_dim'),
            collection_name=parser.get('siglip', 'collection_name'),
            batch_size=parser.getint('siglip', 'batch_size'),
            device=parser.get('siglip', 'device')
        )


@dataclass
class DINOv2Config:
    """DINOv2 模型配置"""
    model_name: str
    model_path: str
    vector_dim: int
    collection_name: str
    patch_tokens_dir: str
    device: str

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
            model_name=parser.get('dinov2', 'model_name'),
            model_path=parser.get('dinov2', 'model_path'),
            vector_dim=parser.getint('dinov2', 'vector_dim'),
            collection_name=parser.get('dinov2', 'collection_name'),
            patch_tokens_dir=parser.get('dinov2', 'patch_tokens_dir'),
            device=parser.get('dinov2', 'device')
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
