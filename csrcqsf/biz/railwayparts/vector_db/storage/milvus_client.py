"""
Milvus 连接管理器
"""
from typing import Optional
from pymilvus import MilvusClient

from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class MilvusConnectionManager:
    """Milvus 连接单例管理器"""

    _instance: Optional[MilvusClient] = None
    _host: Optional[str] = None
    _port: Optional[int] = None

    @classmethod
    def get_client(cls, host: str = "localhost", port: int = 19530) -> MilvusClient:
        """
        获取 Milvus 客户端单例

        Args:
            host: Milvus 服务器地址
            port: Milvus 服务器端口

        Returns:
            MilvusClient 实例
        """
        if cls._instance is None or cls._host != host or cls._port != port:
            logger.info(f"Creating Milvus connection to {host}:{port}")
            cls._instance = MilvusClient(uri=f"http://{host}:{port}")
            cls._host = host
            cls._port = port
            logger.info("Milvus connection established")

        return cls._instance

    @classmethod
    def close(cls):
        """关闭连接"""
        if cls._instance is not None:
            cls._instance.close()
            cls._instance = None
            cls._host = None
            cls._port = None
            logger.info("Milvus connection closed")
