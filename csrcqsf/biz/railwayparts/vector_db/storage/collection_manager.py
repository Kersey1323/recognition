"""
Collection 管理器
"""
from typing import List, Dict
from pymilvus import MilvusClient, DataType

from csrcqsf.biz.railwayparts.vector_db.storage.milvus_client import MilvusConnectionManager
from csrcqsf.biz.railwayparts.vector_db.utils.logger import setup_logger

logger = setup_logger(__name__)


class CollectionManager:
    """Collection 管理器"""

    def __init__(self, host: str = "localhost", port: int = 19530):
        """
        初始化 Collection 管理器

        Args:
            host: Milvus 服务器地址
            port: Milvus 服务器端口
        """
        self.client = MilvusConnectionManager.get_client(host, port)

    def collection_exists(self, collection_name: str) -> bool:
        """
        检查 Collection 是否存在

        Args:
            collection_name: Collection 名称

        Returns:
            是否存在
        """
        return self.client.has_collection(collection_name)

    def drop_collection(self, collection_name: str):
        """
        删除 Collection（谨慎使用）

        Args:
            collection_name: Collection 名称
        """
        if self.collection_exists(collection_name):
            self.client.drop_collection(collection_name)
            logger.warning(f"Collection dropped: {collection_name}")

    def create_siglip_collection(
        self,
        collection_name: str,
        vector_dim: int = 1152
    ) -> bool:
        """
        创建 SigLIP Collection

        Args:
            collection_name: Collection 名称
            vector_dim: 向量维度

        Returns:
            是否创建成功
        """
        if self.collection_exists(collection_name):
            logger.info(f"Collection already exists: {collection_name}")
            return False

        logger.info(f"Creating SigLIP collection: {collection_name}")

        # 定义 Schema
        schema = MilvusClient.create_schema(
            auto_id=True,
            enable_dynamic_field=False
        )

        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="item_id", datatype=DataType.INT64)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=200)
        schema.add_field(field_name="item_code", datatype=DataType.VARCHAR, max_length=100)
        schema.add_field(field_name="image_id", datatype=DataType.INT64)
        schema.add_field(field_name="image_url", datatype=DataType.VARCHAR, max_length=500)
        schema.add_field(field_name="description", datatype=DataType.VARCHAR, max_length=1000)
        schema.add_field(field_name="image_vector", datatype=DataType.FLOAT_VECTOR, dim=vector_dim)
        schema.add_field(field_name="text_vector", datatype=DataType.FLOAT_VECTOR, dim=vector_dim)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=50)

        # 定义索引
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="image_vector",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 1024}
        )
        index_params.add_index(
            field_name="text_vector",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 1024}
        )

        # 创建 Collection
        self.client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params
        )

        logger.info(f"SigLIP collection created: {collection_name}")
        return True

    def create_dinov2_collection(
        self,
        collection_name: str,
        vector_dim: int = 1024
    ) -> bool:
        """
        创建 DINOv2 Collection

        Args:
            collection_name: Collection 名称
            vector_dim: 向量维度

        Returns:
            是否创建成功
        """
        if self.collection_exists(collection_name):
            logger.info(f"Collection already exists: {collection_name}")
            return False

        logger.info(f"Creating DINOv2 collection: {collection_name}")

        # 定义 Schema
        schema = MilvusClient.create_schema(
            auto_id=True,
            enable_dynamic_field=False
        )

        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="item_id", datatype=DataType.INT64)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=200)
        schema.add_field(field_name="item_code", datatype=DataType.VARCHAR, max_length=100)
        schema.add_field(field_name="image_id", datatype=DataType.INT64)
        schema.add_field(field_name="image_url", datatype=DataType.VARCHAR, max_length=500)
        schema.add_field(field_name="global_vector", datatype=DataType.FLOAT_VECTOR, dim=vector_dim)
        schema.add_field(field_name="patch_tokens", datatype=DataType.FLOAT_VECTOR, dim=vector_dim)
        schema.add_field(field_name="patch_tokens_path", datatype=DataType.VARCHAR, max_length=500)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=50)

        # 定义索引
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="global_vector",
            index_type="IVF_FLAT",
            metric_type="L2",
            params={"nlist": 1024}
        )
        index_params.add_index(
            field_name="patch_tokens",
            index_type="IVF_FLAT",
            metric_type="L2",
            params={"nlist": 1024}
        )

        # 创建 Collection
        self.client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params
        )

        logger.info(f"DINOv2 collection created: {collection_name}")
        return True

    def insert_siglip_records(
        self,
        collection_name: str,
        records: List[Dict]
    ) -> List[int]:
        """
        批量插入 SigLIP 记录

        Args:
            collection_name: Collection 名称
            records: 记录列表

        Returns:
            插入的记录 ID 列表
        """
        result = self.client.insert(
            collection_name=collection_name,
            data=records
        )
        logger.debug(f"Inserted {len(records)} records to {collection_name}")
        return result["ids"]

    def insert_dinov2_records(
        self,
        collection_name: str,
        records: List[Dict]
    ) -> List[int]:
        """
        批量插入 DINOv2 记录

        Args:
            collection_name: Collection 名称
            records: 记录列表

        Returns:
            插入的记录 ID 列表
        """
        result = self.client.insert(
            collection_name=collection_name,
            data=records
        )
        logger.debug(f"Inserted {len(records)} records to {collection_name}")
        return result["ids"]
